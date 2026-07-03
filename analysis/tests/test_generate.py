# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
import pickle
import tempfile
import unittest
from pathlib import Path

import numpy as np

from norc.core.generate import (
    check_predefined_variables,
    check_scorep_conflicts,
    check_unassigned_variables,
    check_undefined_variables,
    expand_combinations,
    extract_shell_variables,
    extract_used_variables,
    extract_variables,
    group_counters_via_metrics_cfg,
    is_sbatch_script,
    parse_metrics_cfg,
    select_counters,
)
from norc.core.score import score, score_group
from norc.helpers.util import callpath_data


class MockCallpath:
    """Mock callpath for testing."""
    def __init__(self, name, visits, contribution, deviations):
        self.name = name
        self.visits = visits
        self.contribution = contribution
        self.deviations = deviations


class TestExtractVariables(unittest.TestCase):
    """Test variable extraction from templates."""

    def test_extract_single_variable(self):
        template = "prog --size @@n@@"
        vars = extract_variables(template)
        self.assertEqual(vars, {"n"})

    def test_extract_multiple_variables(self):
        template = "prog --size @@n@@ --threads @@t@@ --ntasks @@ntasks@@"
        vars = extract_variables(template)
        self.assertEqual(vars, {"n", "t", "ntasks"})

    def test_extract_no_variables(self):
        template = "prog --static-arg"
        vars = extract_variables(template)
        self.assertEqual(vars, set())


class TestExtractShellVariables(unittest.TestCase):
    """Test shell variable extraction from templates."""

    def test_simple_assignment(self):
        template = "num_neurons=50000\nsteps=100"
        vars = extract_shell_variables(template)
        self.assertEqual(vars, {"num_neurons", "steps"})

    def test_export_statement(self):
        template = "export PATH=/usr/bin\nexport HOME=/home/user"
        vars = extract_shell_variables(template)
        self.assertEqual(vars, {"PATH", "HOME"})

    def test_quoted_values(self):
        template = 'name="John Doe"\nvalue="test value"'
        vars = extract_shell_variables(template)
        self.assertEqual(vars, {"name", "value"})

    def test_ignores_comments(self):
        template = "# var=commented\nvar=real"
        vars = extract_shell_variables(template)
        self.assertEqual(vars, {"var"})

    def test_ignores_sbatch_directives(self):
        template = "#SBATCH --ntasks=4\nvar=value"
        vars = extract_shell_variables(template)
        self.assertEqual(vars, {"var"})

    def test_no_variables(self):
        template = "#!/bin/bash\nsrun ./prog"
        vars = extract_shell_variables(template)
        self.assertEqual(vars, set())


class TestCheckPredefinedVariables(unittest.TestCase):
    """Test detection of variables that are both placeholders and pre-defined."""

    def test_no_conflicts(self):
        template_vars = {"n", "t"}
        shell_vars = {"size", "threads"}
        conflicts = check_predefined_variables(template_vars, shell_vars)
        self.assertEqual(conflicts, set())

    def test_with_conflicts(self):
        template_vars = {"n", "size", "threads"}
        shell_vars = {"size", "threads", "steps"}
        conflicts = check_predefined_variables(template_vars, shell_vars)
        self.assertEqual(conflicts, {"size", "threads"})

    def test_partial_overlap(self):
        template_vars = {"num_neurons", "steps"}
        shell_vars = {"num_neurons", "steps", "ranks"}
        conflicts = check_predefined_variables(template_vars, shell_vars)
        self.assertEqual(conflicts, {"num_neurons", "steps"})


class TestCheckUnassignedVariables(unittest.TestCase):
    """Test unassigned variable detection."""

    def test_all_assigned(self):
        template_vars = {"n", "t", "size"}
        assigned_vars = ["n=1,2", "t=2,4", "size=small,large"]
        unassigned = check_unassigned_variables(template_vars, assigned_vars)
        self.assertEqual(unassigned, set())

    def test_some_unassigned(self):
        template_vars = {"n", "t", "size", "threads"}
        assigned_vars = ["n=1,2", "t=2,4"]
        unassigned = check_unassigned_variables(template_vars, assigned_vars)
        self.assertEqual(unassigned, {"size", "threads"})

    def test_no_template_vars(self):
        template_vars = set()
        assigned_vars = ["n=1,2", "t=2,4"]
        unassigned = check_unassigned_variables(template_vars, assigned_vars)
        self.assertEqual(unassigned, set())

    def test_no_assigned_vars(self):
        template_vars = {"n", "t", "size"}
        assigned_vars = []
        unassigned = check_unassigned_variables(template_vars, assigned_vars)
        self.assertEqual(unassigned, {"n", "t", "size"})

    def test_assigned_via_shell_vars(self):
        template_vars = {"n", "t", "size"}
        assigned_vars = ["n=1,2"]
        shell_vars = {"t", "size"}
        unassigned = check_unassigned_variables(template_vars, assigned_vars, shell_vars)
        self.assertEqual(unassigned, set())

    def test_partially_assigned_via_shell_vars(self):
        template_vars = {"n", "t", "size", "threads"}
        assigned_vars = ["n=1,2"]
        shell_vars = {"t"}
        unassigned = check_unassigned_variables(template_vars, assigned_vars, shell_vars)
        self.assertEqual(unassigned, {"size", "threads"})


class TestExtractUsedVariables(unittest.TestCase):
    """Test extraction of $var / ${var} shell references."""

    def test_simple_reference(self):
        template = "srun ./prog --size $n"
        self.assertEqual(extract_used_variables(template), {"n"})

    def test_braced_reference(self):
        template = "srun ./prog --size ${n}"
        self.assertEqual(extract_used_variables(template), {"n"})

    def test_ignores_comments(self):
        template = "# $commented\nsrun ./prog --size $n"
        self.assertEqual(extract_used_variables(template), {"n"})

    def test_ignores_env_and_slurm_vars(self):
        template = "srun ./prog --ranks $SLURM_NTASKS --home $HOME --size $n"
        self.assertEqual(extract_used_variables(template), {"n"})

    def test_no_references(self):
        template = "srun ./prog --static-arg"
        self.assertEqual(extract_used_variables(template), set())


class TestCheckUndefinedVariables(unittest.TestCase):
    """Test detection of $var references that are never assigned."""

    def test_all_defined(self):
        used_vars = {"n", "t"}
        shell_vars = {"n", "t", "size"}
        self.assertEqual(check_undefined_variables(used_vars, shell_vars), set())

    def test_some_undefined(self):
        used_vars = {"n", "t", "size"}
        shell_vars = {"n"}
        self.assertEqual(check_undefined_variables(used_vars, shell_vars), {"t", "size"})

    def test_no_used_vars(self):
        self.assertEqual(check_undefined_variables(set(), {"n"}), set())


class TestParseMetricsCfg(unittest.TestCase):
    """Test parsing of metrics.cfg counter groupings."""

    def test_single_group(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cfg', delete=False) as f:
            f.write("PAPI_TOT_INS,PAPI_BR_INS\n")
            f.flush()
            groups = parse_metrics_cfg(f.name)
        self.assertEqual(groups, [["PAPI_TOT_INS", "PAPI_BR_INS"]])

    def test_multiple_groups(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cfg', delete=False) as f:
            f.write("PAPI_TOT_INS,PAPI_BR_INS\n")
            f.write("PAPI_LD_INS\n")
            f.flush()
            groups = parse_metrics_cfg(f.name)
        self.assertEqual(groups, [["PAPI_TOT_INS", "PAPI_BR_INS"], ["PAPI_LD_INS"]])

    def test_ignores_comments_and_blank_lines(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cfg', delete=False) as f:
            f.write("# a comment\n")
            f.write("\n")
            f.write("PAPI_TOT_INS\n")
            f.flush()
            groups = parse_metrics_cfg(f.name)
        self.assertEqual(groups, [["PAPI_TOT_INS"]])

    def test_missing_file(self):
        groups = parse_metrics_cfg("/nonexistent/metrics.cfg")
        self.assertEqual(groups, [])


class TestGroupCountersViaMetricsCfg(unittest.TestCase):
    """Test grouping selected counters using pre-computed metrics.cfg groups."""

    def test_all_counters_covered(self):
        counters = ["PAPI_TOT_INS", "PAPI_BR_INS"]
        cfg_groups = [["PAPI_TOT_INS", "PAPI_BR_INS"]]
        sets = group_counters_via_metrics_cfg(counters, cfg_groups)
        self.assertEqual(sets, [["PAPI_TOT_INS", "PAPI_BR_INS"]])

    def test_partial_match_drops_unselected_counters(self):
        counters = ["PAPI_TOT_INS"]
        cfg_groups = [["PAPI_TOT_INS", "PAPI_BR_INS"]]
        sets = group_counters_via_metrics_cfg(counters, cfg_groups)
        self.assertEqual(sets, [["PAPI_TOT_INS"]])

    def test_uncovered_counter_measured_individually(self):
        counters = ["PAPI_TOT_INS", "PAPI_LD_INS"]
        cfg_groups = [["PAPI_TOT_INS", "PAPI_BR_INS"]]
        sets = group_counters_via_metrics_cfg(counters, cfg_groups)
        self.assertEqual(sets, [["PAPI_TOT_INS"], ["PAPI_LD_INS"]])

    def test_no_cfg_groups_yields_singletons(self):
        counters = ["PAPI_TOT_INS", "PAPI_BR_INS"]
        sets = group_counters_via_metrics_cfg(counters, [])
        self.assertEqual(sets, [["PAPI_TOT_INS"], ["PAPI_BR_INS"]])


class TestIsSbatchScript(unittest.TestCase):
    """Test sbatch script detection."""

    def test_sbatch_script(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("#!/bin/bash\n")
            f.write("#SBATCH --ntasks=4\n")
            f.write("srun ./prog\n")
            f.flush()
            self.assertTrue(is_sbatch_script(f.name))

    def test_shell_script(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write("#!/bin/bash\n")
            f.write("./prog\n")
            f.flush()
            self.assertFalse(is_sbatch_script(f.name))


class TestScorePConflictDetection(unittest.TestCase):
    """Test SCOREP environment variable conflict detection."""

    def test_no_conflicts(self):
        template = "#!/bin/bash\nsrun ./prog\n"
        conflicts = check_scorep_conflicts(template)
        self.assertEqual(conflicts, [])

    def test_export_scorep_experiment_directory(self):
        template = "#!/bin/bash\nexport SCOREP_EXPERIMENT_DIRECTORY=/tmp/exp\nsrun ./prog\n"
        conflicts = check_scorep_conflicts(template)
        self.assertIn("SCOREP_EXPERIMENT_DIRECTORY", conflicts)

    def test_direct_assignment_scorep_metric_papi(self):
        template = "#!/bin/bash\nSCOREP_METRIC_PAPI=PAPI_TOT_INS\nsrun ./prog\n"
        conflicts = check_scorep_conflicts(template)
        self.assertIn("SCOREP_METRIC_PAPI", conflicts)

    def test_multiple_conflicts(self):
        template = """#!/bin/bash
export SCOREP_EXPERIMENT_DIRECTORY=/tmp/exp
export SCOREP_METRIC_PAPI=PAPI_TOT_INS
export SCOREP_ENABLE_PROFILING=true
srun ./prog
"""
        conflicts = check_scorep_conflicts(template)
        self.assertEqual(len(conflicts), 3)
        self.assertIn("SCOREP_EXPERIMENT_DIRECTORY", conflicts)
        self.assertIn("SCOREP_METRIC_PAPI", conflicts)
        self.assertIn("SCOREP_ENABLE_PROFILING", conflicts)

    def test_comments_ignored(self):
        template = """#!/bin/bash
# export SCOREP_EXPERIMENT_DIRECTORY=/tmp/exp
srun ./prog
"""
        conflicts = check_scorep_conflicts(template)
        self.assertEqual(conflicts, [])


class TestExpandCombinations(unittest.TestCase):
    """Test parameter combination expansion."""

    def test_single_variable(self):
        combos = expand_combinations(["n=1,2,4"])
        self.assertEqual(len(combos), 3)
        self.assertEqual(combos[0], {"n": "1"})
        self.assertEqual(combos[1], {"n": "2"})
        self.assertEqual(combos[2], {"n": "4"})

    def test_multiple_variables(self):
        combos = expand_combinations(["n=1,2", "t=2,4"])
        self.assertEqual(len(combos), 4)  # 2 * 2
        self.assertIn({"n": "1", "t": "2"}, combos)
        self.assertIn({"n": "2", "t": "4"}, combos)

    def test_no_variables(self):
        combos = expand_combinations([])
        self.assertEqual(len(combos), 1)
        self.assertEqual(combos[0], {})


class TestSelectCounters(unittest.TestCase):
    """Test counter selection logic."""

    def setUp(self):
        """Create mock score_group for testing."""
        class MockScore:
            def __init__(self, resilience, deviation):
                self.rel_resilience = resilience
                self._deviation = deviation
                self.susceptibility = 0.01

            def deviation(self):
                return self._deviation

        self.sgp = score_group()
        self.sgp.scores = {
            ("bench", "sys", "M2S2", "PAPI_TOT_INS"): MockScore(0.92, 1.23),
            ("bench", "sys", "M2S2", "PAPI_BR_INS"): MockScore(0.85, 2.10),
            ("bench", "sys", "M2S2", "PAPI_LD_INS"): MockScore(0.78, 2.50),
        }

    def test_select_top_1(self):
        selected = select_counters(self.sgp, 1, 0.0)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0], "PAPI_TOT_INS")

    def test_select_top_2(self):
        selected = select_counters(self.sgp, 2, 0.0)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0][0], "PAPI_TOT_INS")
        self.assertEqual(selected[1][0], "PAPI_BR_INS")

    def test_select_with_min_resilience(self):
        selected = select_counters(self.sgp, 3, 0.75)
        self.assertEqual(len(selected), 3)  # All meet threshold

        selected = select_counters(self.sgp, 3, 0.85)
        self.assertEqual(len(selected), 2)  # Only PAPI_TOT_INS and PAPI_BR_INS

        selected = select_counters(self.sgp, 3, 0.95)
        self.assertEqual(len(selected), 0)  # None meet threshold


class TestNorcGenerateIntegration(unittest.TestCase):
    """Integration test using submit_job.sh template."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_dir = Path(self.temp_dir)

        # Get the path to submit_job.sh
        tests_dir = Path(__file__).parent
        self.template_script = tests_dir / "submit_job.sh"
        self.assertTrue(
            self.template_script.exists(),
            f"Template script not found: {self.template_script}"
        )

        # submit_job2.sh uses @@var@@ placeholders (ranks, num_neurons)
        self.template_script2 = tests_dir / "submit_job2.sh"
        self.assertTrue(
            self.template_script2.exists(),
            f"Template script not found: {self.template_script2}"
        )

        # Create a mock experiment structure
        self.exp_root = self.test_dir / "test_exp"
        self.exp_root.mkdir(parents=True)
        deviations_dir = self.exp_root / "result" / ".deviations"
        deviations_dir.mkdir(parents=True)

        # Create mock measurement data
        self._create_mock_measurements(deviations_dir)

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def _create_mock_measurements(self, deviations_dir):
        """Create minimal mock measurement data."""
        # Convention: {benchmark}.{params}.{noise_pattern}.{system}.{res_cfg}.{counter}.pickle
        # Create mock measurement for noiseless (reference)
        callpath_ref = MockCallpath(
            name="main",
            visits=1000,
            contribution=50.0,
            deviations=np.array([0.3, 0.2, 0.25, 0.3, 0.2])
        )
        meas_ref = [callpath_ref]
        ref_file = deviations_dir / "minife.x20y20z20.NO_NOISE.dp-cn.omp.PAPI_TOT_INS.pickle"
        with open(ref_file, 'wb') as f:
            pickle.dump(meas_ref, f)

        # Create mock measurement for noisy
        callpath_noisy = MockCallpath(
            name="main",
            visits=1000,
            contribution=50.0,
            deviations=np.array([1.0, 1.5, 0.8, 1.2, 0.9])
        )
        meas_noisy = [callpath_noisy]
        noisy_file = deviations_dir / "minife.x20y20z20.ALL_NOISE.dp-cn.omp.PAPI_TOT_INS.pickle"
        with open(noisy_file, 'wb') as f:
            pickle.dump(meas_noisy, f)

    def test_template_is_sbatch(self):
        """Verify that submit_job.sh is detected as sbatch."""
        self.assertTrue(is_sbatch_script(str(self.template_script)))

    def test_template_variables(self):
        """Verify submit_job.sh contains expected variables."""
        with open(self.template_script, 'r') as f:
            template = f.read()

        # The template uses shell variables like $num_neurons, but we
        # can also test if it can be extended with {placeholder} style vars
        self.assertIn("num_neurons", template)
        self.assertIn("steps", template)

    def test_generate_command_basic(self):
        """Test basic norc_generate command."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure.sh"

        # Build the arguments
        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        # Run the command
        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        # Verify output script was created
        self.assertTrue(output_script.exists(), "Output script not created")

        # Verify it's executable
        self.assertTrue(os.access(output_script, os.X_OK), "Output script not executable")

    def test_reject_undefined_shell_variable(self):
        """Verify that templates referencing an unassigned $var are rejected."""
        from norc.core.generate import main

        # Create a template that references $num_neurons via shell syntax
        # without ever assigning it.
        template_undefined = self.test_dir / "template_undefined.sh"
        with open(template_undefined, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("steps=100\n")
            f.write("srun ./prog --steps $steps --num-neurons $num_neurons\n")

        output_script = self.test_dir / "measure_undefined.sh"

        argv = [
            str(self.exp_root),
            str(template_undefined),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        with self.assertRaises(SystemExit) as context:
            main(argv)

        self.assertNotEqual(context.exception.code, 0)

    def test_reject_submit_job2_missing_var(self):
        """Verify submit_job2.sh is rejected when @@num_neurons@@ isn't assigned."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_job2_missing.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script2),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
            # Note: Missing --var num_neurons=...
        ]

        with self.assertRaises(SystemExit) as context:
            main(argv)

        self.assertNotEqual(context.exception.code, 0)

    def test_generate_submit_job2_with_variables(self):
        """Test norc_generate against submit_job2.sh with all placeholders assigned."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_job2.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script2),
            "-o", str(output_script),
            "--var", "ranks=4,8",
            "--var", "num_neurons=1000,2000",
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        self.assertTrue(output_script.exists())

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn("RANKS_VALUES=", content, "Variable array not in script")
        self.assertIn("NUM_NEURONS_VALUES=", content, "Variable array not in script")
        self.assertIn("sed -i \"s/@@ranks@@/$ranks/g\"", content, "Placeholder substitution not in script")
        self.assertIn("sed -i \"s/@@num_neurons@@/$num_neurons/g\"", content, "Placeholder substitution not in script")

    def test_generate_with_variables(self):
        """Test norc_generate with parameter variables."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_vars.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--var", "n=1,2",
            "--var", "t=2,4",
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        self.assertTrue(output_script.exists())

        # Verify the script contains the expected loop structure
        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn("N_VALUES=", content, "Variable array not in script")
        self.assertIn("T_VALUES=", content, "Variable array not in script")
        self.assertIn("for n in", content, "Loop variable not in script")
        self.assertIn("for t in", content, "Loop variable not in script")

    def test_generate_with_prefix(self):
        """Test norc_generate with Extra-P prefix."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_prefix.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--var", "n=1,2",
            "--prefix", "myapp",
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch",
            "--iterations", "2"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn("myapp.n=", content, "Prefix not in result directory")

    def test_counter_grouping_in_output(self):
        """Verify the generated script groups counters via find_non_overlapping_sets."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_grouping.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn("find_non_overlapping_sets()", content)
        self.assertIn('if command -v papi_event_chooser >/dev/null 2>&1; then', content)
        self.assertIn('find_non_overlapping_sets "${COUNTERS[@]}"', content)
        self.assertIn('COUNTER_SETS_FALLBACK=("PAPI_TOT_INS")', content)
        self.assertIn('counter_sets=("${COUNTER_SETS_FALLBACK[@]}")', content)
        self.assertIn('for COUNTER_SET in "${counter_sets[@]}"; do', content)
        self.assertIn('export SCOREP_METRIC_PAPI="${COUNTER_SET// /,}"', content)

    def test_counter_grouping_fallback_from_metrics_cfg(self):
        """Verify the fallback grouping is computed from metrics.cfg at generation time."""
        from norc.core.generate import main

        # metrics.cfg groups PAPI_TOT_INS with a counter that wasn't selected;
        # generate.py should keep only the selected counter in the group.
        config_dir = self.exp_root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        with open(config_dir / "metrics.cfg", 'w') as f:
            f.write("PAPI_TOT_INS,PAPI_BR_INS\n")

        output_script = self.test_dir / "measure_metrics_cfg.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn('COUNTER_SETS_FALLBACK=("PAPI_TOT_INS")', content)

    def test_log_capture_default_no_sbatch(self):
        """Verify stdout+stderr of local (bash) runs is redirected into logs/ by default."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_log_bash.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn('LOG_FILE="logs/$(basename "$RESULT_DIR").log"', content)
        self.assertIn('bash "$TEMPLATE_FILE" > "$LOG_FILE" 2>&1', content)

    def test_log_capture_default_sbatch(self):
        """Verify sbatch job output is redirected into logs/ via --output/--error by default."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_log_sbatch.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0"
            # No --no-sbatch: is_sbatch is auto-detected from submit_job.sh
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn(
            'sbatch --output="$LOG_FILE" --error="$LOG_FILE" "$TEMPLATE_FILE" > "$LOG_FILE.submit" 2>&1',
            content
        )

    def test_no_log_capture_override(self):
        """Verify --no-log-capture disables log redirection entirely."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_no_log.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch",
            "--no-log-capture"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertNotIn("LOG_FILE", content)
        self.assertIn('bash "$TEMPLATE_FILE"\n', content)

    def test_counter_comment_in_output(self):
        """Verify selected counters are listed in output script."""
        from norc.core.generate import main

        output_script = self.test_dir / "measure_comment.sh"

        argv = [
            str(self.exp_root),
            str(self.template_script),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        with open(output_script, 'r') as f:
            content = f.read()

        self.assertIn("NORC resilience analysis", content)
        self.assertIn("PAPI_TOT_INS", content)

    def test_reject_unassigned_variables(self):
        """Verify that templates with unassigned variables are rejected."""
        from norc.core.generate import main

        # Create a template with variables
        template_with_vars = self.test_dir / "template_with_vars.sh"
        with open(template_with_vars, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("#SBATCH --ntasks=4\n")
            f.write("./prog --size @@problem_size@@ --threads @@threads@@\n")

        output_script = self.test_dir / "measure_unassigned.sh"

        argv = [
            str(self.exp_root),
            str(template_with_vars),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
            # Note: Missing --var problem_size=... and --var threads=...
        ]

        # Should exit with error due to unassigned variables
        with self.assertRaises(SystemExit) as context:
            main(argv)

        self.assertNotEqual(context.exception.code, 0)

    def test_accept_all_assigned_variables(self):
        """Verify that templates with all variables assigned are accepted."""
        from norc.core.generate import main

        # Create a template with variables
        template_with_vars = self.test_dir / "template_assigned.sh"
        with open(template_with_vars, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("#SBATCH --ntasks=4\n")
            f.write("./prog --size @@size@@ --threads @@threads@@\n")

        output_script = self.test_dir / "measure_assigned.sh"

        argv = [
            str(self.exp_root),
            str(template_with_vars),
            "-o", str(output_script),
            "--var", "size=small,large",
            "--var", "threads=2,4",
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        try:
            main(argv)
        except SystemExit as e:
            if e.code != 0:
                self.fail(f"norc_generate failed with exit code {e.code}")

        # Should succeed and create output script
        self.assertTrue(output_script.exists())

    def test_reject_conflicting_scorep_vars(self):
        """Verify that templates with SCOREP conflicts are rejected."""
        from norc.core.generate import main

        # Create a template with conflicting SCOREP variables
        bad_template = self.test_dir / "bad_template.sh"
        with open(bad_template, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("#SBATCH --ntasks=4\n")
            f.write("export SCOREP_EXPERIMENT_DIRECTORY=/tmp/exp\n")
            f.write("srun ./prog\n")

        output_script = self.test_dir / "measure_bad.sh"

        argv = [
            str(self.exp_root),
            str(bad_template),
            "-o", str(output_script),
            "--top", "1",
            "--min-resilience", "0",
            "--no-sbatch"
        ]

        # Should exit with error
        with self.assertRaises(SystemExit) as context:
            main(argv)

        self.assertNotEqual(context.exception.code, 0)


if __name__ == '__main__':
    unittest.main()