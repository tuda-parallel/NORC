# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import argparse
import itertools
import os
import re
import sys
import zipfile

from norc.helpers.util import data_selection, measurement_info, open_experiment_source
from norc.core.score import compute_scores


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a measurement orchestration script for an arbitrary program using NORC-selected HW counters"
    )

    parser.add_argument(
        "experiment_root",
        help="NORC experiment directory (contains result/.deviations/)"
    )
    parser.add_argument(
        "template_script",
        help="Path to sbatch or shell script template (may contain @@var@@ placeholders)"
    )

    counter_group = parser.add_argument_group("counter selection (AND-combined)")
    counter_group.add_argument(
        "--top",
        type=int,
        default=10,
        help="Select top N counters by resilience (default: 10)"
    )
    counter_group.add_argument(
        "--min-resilience",
        type=float,
        default=0.9,
        help="Minimum resilience score 0.0-1.0 (default: 0.9)"
    )
    counter_group.add_argument(
        "-c", "--contribution",
        type=float,
        default=0,
        help="Min callpath contribution %% for scoring (default: 0)"
    )
    counter_group.add_argument(
        "-v", "--visits",
        type=int,
        default=0,
        help="Min visits for scoring (default: 0)"
    )

    var_group = parser.add_argument_group("parameters")
    var_group.add_argument(
        "--var",
        action="append",
        default=[],
        help="Values for placeholder, e.g. --var n=1,2,4 (repeatable, includes ntasks)"
    )

    sbatch_group = parser.add_argument_group("script type")
    sbatch_control = sbatch_group.add_mutually_exclusive_group()
    sbatch_control.add_argument(
        "--sbatch",
        action="store_true",
        help="Treat template as sbatch script (overrides auto-detection)"
    )
    sbatch_control.add_argument(
        "--no-sbatch",
        action="store_true",
        help="Treat template as regular shell script (overrides auto-detection)"
    )

    output_group = parser.add_argument_group("output")
    output_group.add_argument(
        "-o", "--output",
        default="measure.sh",
        help="Output wrapper script path (default: measure.sh)"
    )
    output_group.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Repetitions per parameter combination (default: 1)"
    )
    output_group.add_argument(
        "--prefix",
        help="Optional prefix for result directory names (Extra-P standard)"
    )
    output_group.add_argument(
        "--no-log-capture",
        action="store_true",
        help="Do not redirect job/template stdout+stderr into logs/ "
             "(leaves #SBATCH -o/-e directives in the template as written)"
    )

    return parser.parse_args(argv)


def is_sbatch_script(template_path):
    """Check if the template script is an sbatch script."""
    try:
        with open(template_path, 'r') as f:
            first_line = f.readline()
            return first_line.startswith("#!/bin/bash") and "#SBATCH" in f.read()
    except (OSError, IOError):
        return False


def read_template(template_path):
    """Read the template script."""
    try:
        with open(template_path, 'r') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading template: {e}", file=sys.stderr)
        sys.exit(1)


def check_scorep_conflicts(template):
    """Check for conflicting SCOREP environment variables in template.

    Returns list of conflicting variable names found.
    Ignores commented lines.
    """
    critical_vars = [
        "SCOREP_EXPERIMENT_DIRECTORY",
        "SCOREP_METRIC_PAPI",
        "SCOREP_ENABLE_PROFILING",
    ]

    conflicts = []
    for var in critical_vars:
        # Match export or direct assignment patterns, but not in comments
        # Negative lookbehind to exclude lines that start with # (after whitespace)
        pattern = rf'^(?![\s]*#).*(?:export\s+{var}\s*=|^{var}\s*=)'
        if re.search(pattern, template, re.MULTILINE):
            conflicts.append(var)

    return conflicts


def extract_variables(template):
    """Extract all @@var@@ placeholders from template."""
    return set(re.findall(r'@@(\w+)@@', template))


def extract_shell_variables(template):
    """Extract shell variable assignments from template.

    Looks for lines like: var=value, var="value", export var=value, etc.
    Ignores variable references and SBATCH directives.

    Returns:
        Set of variable names that are defined in the template.
    """
    shell_vars = set()
    for line in template.split('\n'):
        # Skip comments and SBATCH directives
        if line.strip().startswith('#'):
            continue
        # Match variable assignments: var=value (but not comparisons or references)
        match = re.match(r'^\s*(?:export\s+)?(\w+)\s*=', line)
        if match:
            shell_vars.add(match.group(1))
    return shell_vars


_ENV_VAR_PREFIXES = ("SLURM_",)
_ENV_VAR_NAMES = {
    "PATH", "HOME", "USER", "PWD", "OLDPWD", "SHELL", "LANG", "LC_ALL",
    "HOSTNAME", "TMPDIR", "LOGNAME", "TERM", "LD_LIBRARY_PATH", "MAIL",
}


def extract_used_variables(template):
    """Extract $var / ${var} shell variable references from the template.

    Ignores comments, positional/special shell parameters (e.g. $?, $$, $1),
    and known runtime/environment variables (e.g. $SLURM_NTASKS, $PATH) that
    are provided by the execution environment rather than the user.

    Returns:
        Set of referenced variable names.
    """
    used = set()
    for line in template.split('\n'):
        if line.strip().startswith('#'):
            continue
        for match in re.finditer(r'\$\{?([A-Za-z_]\w*)\}?', line):
            name = match.group(1)
            if name.startswith(_ENV_VAR_PREFIXES) or name in _ENV_VAR_NAMES:
                continue
            used.add(name)
    return used


def check_undefined_variables(used_vars, shell_vars):
    """Check for $var references that are never assigned in the template.

    Args:
        used_vars: Set of $var references found in template (from extract_used_variables)
        shell_vars: Set of shell variables defined in template (from extract_shell_variables)

    Returns:
        Set of variable names that are referenced but never assigned.
    """
    return used_vars - shell_vars


def check_unassigned_variables(template_vars, assigned_vars, shell_vars=None):
    """Check for template variables that are not assigned values.

    A variable counts as assigned if it is passed via --var, or if it is
    already assigned directly in the template (a shell variable).

    Args:
        template_vars: Set of variables found in template (from extract_variables)
        assigned_vars: List of var specs from --var arguments (e.g., ["n=1,2", "t=2,4"])
        shell_vars: Set of shell variables defined in template (from extract_shell_variables)

    Returns:
        Set of unassigned variable names, or empty set if all assigned.
    """
    assigned_names = set()
    for spec in assigned_vars:
        name = spec.split("=", 1)[0]
        assigned_names.add(name)

    if shell_vars:
        assigned_names |= shell_vars

    unassigned = template_vars - assigned_names
    return unassigned


def check_predefined_variables(template_vars, shell_vars):
    """Check for template variables that are already defined in the shell script.

    Variables already defined in the template cannot be used as placeholders
    since they will be overridden by the assignment in the template.

    Args:
        template_vars: Set of placeholder variables (from extract_variables)
        shell_vars: Set of shell variables defined in template (from extract_shell_variables)

    Returns:
        Set of variable names that are both placeholders and pre-defined.
    """
    return template_vars & shell_vars


def select_counters(sgp, top_n, min_resilience):
    sorted_counters = sorted(
        sgp.scores.items(),
        key=lambda it: it[1].rel_resilience,
        reverse=True
    )
    selected = []
    for key, sc in sorted_counters:
        info = measurement_info.from_key(key)
        if len(selected) < top_n and sc.rel_resilience >= min_resilience:
            selected.append((info.counter, sc))
    return selected


def expand_combinations(var_specs):
    """Expand --var specifications into all combinations."""
    if not var_specs:
        return [{}]

    var_dict = {}
    for spec in var_specs:
        name, values_str = spec.split("=", 1)
        values = values_str.split(",")
        var_dict[name] = values

    var_names = sorted(var_dict.keys())
    var_lists = [var_dict[name] for name in var_names]

    combinations = []
    for combo_values in itertools.product(*var_lists):
        combo = {var_names[i]: combo_values[i] for i in range(len(var_names))}
        combinations.append(combo)
    return combinations


def substitute_template(template, combo):
    """Substitute variables in the template with combo values."""
    result = template
    for var_name, var_value in combo.items():
        result = result.replace(f"@@{var_name}@@", var_value)
    return result


def modify_sbatch_ntasks(template, ntasks_value):
    """Modify the #SBATCH --ntasks line if ntasks is present in combo."""
    if "ntasks" in template:
        # Replace #SBATCH --ntasks=... line
        return re.sub(
            r'#SBATCH --ntasks=[^\n]*',
            f'#SBATCH --ntasks={ntasks_value}',
            template
        )
    return template


FIND_NON_OVERLAPPING_SETS_FUNC = """\
# Groups counters into the fewest sets that can be measured together in a
# single run (via SCOREP_METRIC_PAPI's comma-separated list), using
# papi_event_chooser to test which counters do not conflict for the same
# hardware counter registers. Falls back to a set of one if a counter is
# incompatible with every other remaining counter.
find_non_overlapping_sets() {
    local counters=("$@")
    local sets=()

    while [ "${#counters[@]}" -gt 0 ]; do
        local max_set=()
        local j=0

        for ((j = 0; j < ${#counters[@]}; j++)); do
            subset=("${counters[@]:0:j+1}")
            if papi_event_chooser PRESET "${subset[@]}" >/dev/null 2>&1; then
                if [ "${#subset[@]}" -gt "${#max_set[@]}" ]; then
                    max_set=("${subset[@]}")
                fi
            else
                break
            fi
        done

        if [ "${#max_set[@]}" -eq 0 ]; then
            max_set=("${counters[0]}")
            j=1
        fi

        sets+=("${max_set[*]}")
        counters=("${counters[@]:j}")
    done

    counter_sets=("${sets[@]}")
}"""


def parse_metrics_cfg(path):
    """Parse a metrics.cfg file into counter groups.

    metrics.cfg holds one comma-separated, pre-computed non-overlapping
    counter group per line, as produced by find_non_overlapping_sets() in
    acquisition/util/config_assistent.sh. Lines are '#'-comment-able.

    Returns:
        List of groups (each a list of counter names), or [] if the file
        does not exist or contains no usable groups.
    """
    try:
        with open(path, 'r') as f:
            return _parse_metrics_cfg_lines(f)
    except (OSError, IOError):
        return []


def _parse_metrics_cfg_lines(lines):
    groups = []
    for line in lines:
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        groups.append([c.strip() for c in line.split(',') if c.strip()])
    return groups


def parse_metrics_cfg_from_tree(tree, path):
    """Same as parse_metrics_cfg, but reads through an ExperimentTree so a zipped
    experiment_root works exactly like a directory one."""
    if not tree.exists(path):
        return []
    with tree.open_binary(path) as f:
        text = f.read().decode("utf-8", errors="replace")
    return _parse_metrics_cfg_lines(text.splitlines())


def group_counters_via_metrics_cfg(counters, cfg_groups):
    """Group counters using pre-computed groups from metrics.cfg.

    Any selected counter not covered by cfg_groups is measured individually.

    Returns:
        List of groups (each a list of counter names).
    """
    remaining = list(counters)
    sets = []
    for cfg_group in cfg_groups:
        cfg_set = set(cfg_group)
        matched = [c for c in remaining if c in cfg_set]
        if matched:
            sets.append(matched)
        remaining = [c for c in remaining if c not in cfg_set]

    for c in remaining:
        sets.append([c])

    return sets


def render_counter_comment(selected_counters):
    """Render comment with counter information."""
    lines = [
        "# HW counters selected by NORC resilience analysis"
    ]
    for rank, (counter, sc) in enumerate(selected_counters, 1):
        # Add PAPI_ prefix if not present (was stripped during analysis parsing)
        counter_name = f"PAPI_{counter}" if not counter.startswith("PAPI_") else counter
        lines.append(
            f"# Rank {rank}: {counter_name}  "
            f"(resilience={sc.rel_resilience:.4f}, "
            f"deviation={sc.deviation():.4f}%, "
            f"susceptibility={sc.susceptibility:.4f})"
        )
    return "\n".join(lines)


def render_execution_block(indent, is_sbatch, capture_logs):
    """Render the lines that submit/run one measurement and clean up its template copy.

    When capture_logs is set, redirects stdout+stderr into logs/. For sbatch,
    this passes --output/--error on the sbatch command line, which overrides
    any #SBATCH -o/-e directive in the template script itself; the sbatch
    submission command's own output (e.g. "Submitted batch job N") is
    captured separately since it isn't part of the job's output.
    """
    lines = []

    if capture_logs:
        lines.append(f'{indent}LOG_FILE="logs/$(basename "$RESULT_DIR").log"')

    if is_sbatch:
        if capture_logs:
            lines.append(f'{indent}sbatch --output="$LOG_FILE" --error="$LOG_FILE" "$TEMPLATE_FILE" > "$LOG_FILE.submit" 2>&1')
        else:
            lines.append(f'{indent}sbatch "$TEMPLATE_FILE"')
    else:
        if capture_logs:
            lines.append(f'{indent}bash "$TEMPLATE_FILE" > "$LOG_FILE" 2>&1')
        else:
            lines.append(f'{indent}bash "$TEMPLATE_FILE"')

    lines.append(f'{indent}[ $? -eq 0 ] && rm "$TEMPLATE_FILE"')
    return lines


def render_orchestration_script(args, selected_counters, fallback_counter_sets, combinations, template, is_sbatch):
    """Render the orchestration wrapper script."""
    lines = []

    lines.append("#!/bin/bash")
    lines.append("")
    lines.append(render_counter_comment(selected_counters))
    lines.append("")
    lines.append("set -e  # exit on error")
    lines.append("")
    lines.append(f"TEMPLATE_SCRIPT=\"{args.template_script}\"")
    lines.append("")

    # Add PAPI_ prefix if not present (was stripped during analysis parsing)
    counter_list = " ".join(
        f'"{f"PAPI_{c}" if not c.startswith("PAPI_") else c}"'
        for c, _ in selected_counters
    )
    lines.append(f'COUNTERS=({counter_list})')
    lines.append(f"ITERATIONS={args.iterations}")
    lines.append("")

    # Fallback groups computed at generation time from metrics.cfg, used when
    # papi_event_chooser is unavailable at run time.
    fallback_list = " ".join(f'"{" ".join(group)}"' for group in fallback_counter_sets)
    lines.append(f'COUNTER_SETS_FALLBACK=({fallback_list})')
    lines.append("")

    lines.append(FIND_NON_OVERLAPPING_SETS_FUNC)
    lines.append("")
    lines.append('if command -v papi_event_chooser >/dev/null 2>&1; then')
    lines.append('    find_non_overlapping_sets "${COUNTERS[@]}"')
    lines.append('else')
    lines.append('    echo "Warning: papi_event_chooser not found; using counter groupings computed from metrics.cfg at generation time" >&2')
    lines.append('    counter_sets=("${COUNTER_SETS_FALLBACK[@]}")')
    lines.append('fi')
    lines.append("")

    if combinations and combinations[0]:
        var_names = sorted(combinations[0].keys())
        for var_name in var_names:
            var_values = sorted(set(c[var_name] for c in combinations))
            value_list=" ".join(var_values)
            lines.append(f'{var_name.upper()}_VALUES=({value_list})')
        lines.append("")

    lines.append("mkdir -p logs result temp_templates")
    lines.append("")

    capture_logs = not args.no_log_capture

    # Build the nested loop structure
    if not combinations or not combinations[0]:
        # No variables, just iterate over counters and iterations
        lines.append("for COUNTER_SET in \"${counter_sets[@]}\"; do")
        lines.append("    for iter in $(seq 1 $ITERATIONS); do")
        lines.append("        RESULT_DIR=\"result/r${iter}\"")
        lines.append("        export SCOREP_METRIC_PAPI=\"${COUNTER_SET// /,}\"")
        lines.append("        export SCOREP_EXPERIMENT_DIRECTORY=\"${RESULT_DIR}.tmp\"")
        lines.append("")
        lines.append("        TEMPLATE_FILE=\"temp_templates/template_r${iter}.sh\"")
        lines.append("        cp \"$TEMPLATE_SCRIPT\" \"$TEMPLATE_FILE\"")
        lines.append("        chmod +x \"$TEMPLATE_FILE\"")
        lines.extend(render_execution_block("        ", is_sbatch, capture_logs))
        lines.append("    done")
        lines.append("done")
    else:
        var_names = sorted(combinations[0].keys())
        indent = 0

        for var_name in var_names:
            lines.append("    " * indent + f"for {var_name} in \"${{{var_name.upper()}_VALUES[@]}}\"; do")
            indent += 1

        lines.append("    " * indent + "rep=1")
        lines.append("    " * indent + "for COUNTER_SET in \"${counter_sets[@]}\"; do")
        indent += 1
        lines.append("    " * indent + "for iter in $(seq 1 $ITERATIONS); do")
        indent += 1

        # Build Extra-P directory name
        param_parts = [f"{name}=${{{name}}}" for name in var_names]
        param_str = ".".join(param_parts)
        if args.prefix:
            result_dir = f"{args.prefix}.{param_str}.r${{rep}}"
        else:
            result_dir = f"{param_str}.r${{rep}}"

        lines.append("    " * indent + f"RESULT_DIR=\"result/{result_dir}\"")
        lines.append("    " * indent + "export SCOREP_METRIC_PAPI=\"${COUNTER_SET// /,}\"")
        lines.append("    " * indent + "export SCOREP_EXPERIMENT_DIRECTORY=\"${RESULT_DIR}.tmp\"")
        lines.append("")
        lines.append("    " * indent + "TEMPLATE_FILE=\"temp_templates/template_${rep}_iter${iter}.sh\"")
        lines.append("    " * indent + "cp \"$TEMPLATE_SCRIPT\" \"$TEMPLATE_FILE\"")
        lines.append("    " * indent + "chmod +x \"$TEMPLATE_FILE\"")
        lines.append("")

        # Variable substitution
        lines.append("    " * indent + "# Substitute variables in template")
        for var_name in var_names:
            lines.append("    " * indent + f"sed -i \"s/@@{var_name}@@/${var_name}/g\" \"$TEMPLATE_FILE\"")

        lines.append("")
        lines.extend(render_execution_block("    " * indent, is_sbatch, capture_logs))
        lines.append("    " * indent + "rep=$((rep + 1))")
        lines.append("")

        indent -= 1
        lines.append("    " * indent + "done")
        indent -= 1
        lines.append("    " * indent + "done")

        for _ in var_names:
            indent -= 1
            lines.append("    " * indent + "done")

    lines.append("")
    lines.append("echo 'Orchestration complete. Results in result/ directory.'")

    return "\n".join(lines)


def main(argv=None):
    args = parse_args(argv)

    is_zip_root = os.path.isfile(args.experiment_root) and zipfile.is_zipfile(args.experiment_root)
    if not os.path.isdir(args.experiment_root) and not is_zip_root:
        print(f"Error: experiment_root '{args.experiment_root}' not found", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(args.template_script):
        print(f"Error: template_script '{args.template_script}' not found", file=sys.stderr)
        sys.exit(1)

    # Determine if template is sbatch-based: explicit flags override auto-detection
    if args.sbatch:
        is_sbatch = True
    elif args.no_sbatch:
        is_sbatch = False
    else:
        is_sbatch = is_sbatch_script(args.template_script)

    # Read the template to check for variables
    template = read_template(args.template_script)
    template_vars = extract_variables(template)
    shell_vars = extract_shell_variables(template)

    # Check for variables that are both placeholders and pre-defined in template
    predefined = check_predefined_variables(template_vars, shell_vars)
    if predefined:
        print(
            f"Warning: Template uses variables that are already defined in the script:\n"
            f"  {', '.join(sorted(predefined))}\n"
            f"These variables will not be substituted because they are set in the template.\n"
            f"Use different placeholder names or remove the variable assignments from the template.",
            file=sys.stderr
        )

    # Check for conflicting SCOREP environment variables
    conflicts = check_scorep_conflicts(template)
    if conflicts:
        print(
            f"Error: Template script contains conflicting SCOREP variables:\n"
            f"  {', '.join(conflicts)}\n"
            f"These are set by the orchestration wrapper and must be removed from the template.\n"
            f"The wrapper will automatically set these for each measurement.",
            file=sys.stderr
        )
        sys.exit(1)

    # Check for unassigned template variables
    unassigned = check_unassigned_variables(template_vars, args.var, shell_vars)
    if unassigned:
        print(
            f"Error: Template contains unassigned variables:\n"
            f"  {', '.join(sorted(unassigned))}\n"
            f"All template variables must be assigned using --var.\n"
            f"Examples:\n"
            + "\n".join(f"  --var {var}=value1,value2" for var in sorted(unassigned)),
            file=sys.stderr
        )
        sys.exit(1)

    # Check for $var / ${var} references that are never assigned in the template
    used_vars = extract_used_variables(template)
    undefined = check_undefined_variables(used_vars, shell_vars)
    if undefined:
        print(
            f"Error: Template references variables that are never assigned:\n"
            f"  {', '.join(sorted(undefined))}\n"
            f"Assign these directly in the template (e.g. {sorted(undefined)[0]}=value).",
            file=sys.stderr
        )
        sys.exit(1)

    # Load scores
    selection = data_selection()
    selection.lump_benchmarks = True
    selection.lump_noise = True
    selection.lump_params = True
    selection.lump_resources = True
    selection.lump_systems = True
    selection.contrib_threshold = args.contribution
    selection.visit_threshold = args.visits

    try:
        sgp = compute_scores(args.experiment_root, selection)
    except Exception as e:
        print(f"Error computing scores: {e}", file=sys.stderr)
        sys.exit(1)

    if not sgp.scores:
        print("Error: no scores computed from experiment", file=sys.stderr)
        sys.exit(1)

    # Select counters
    selected_counters = select_counters(sgp, args.top, args.min_resilience)
    if not selected_counters:
        print(
            f"Error: no counters selected with --top {args.top} and "
            f"--min-resilience {args.min_resilience}",
            file=sys.stderr
        )
        sys.exit(1)

    # Expand variable combinations
    combinations = expand_combinations(args.var)

    # Validate that --var ntasks requires sbatch (if needed)
    has_ntasks_var = any("ntasks=" in spec for spec in args.var)
    if has_ntasks_var and not is_sbatch:
        print(
            "Warning: varying ntasks (--var ntasks=...) in a shell script will have no effect\n"
            "  (ntasks is only meaningful for sbatch/srun)\n",
            file=sys.stderr
        )

    # Compute the fallback counter grouping from metrics.cfg, used by the
    # generated script when papi_event_chooser isn't available at run time.
    counters_with_prefix = [
        f"PAPI_{c}" if not c.startswith("PAPI_") else c
        for c, _ in selected_counters
    ]
    with open_experiment_source(args.experiment_root) as tree:
        metrics_cfg_path = os.path.join(tree.root, "config", "metrics.cfg")
        cfg_groups = parse_metrics_cfg_from_tree(tree, metrics_cfg_path)
    if cfg_groups:
        fallback_counter_sets = group_counters_via_metrics_cfg(counters_with_prefix, cfg_groups)
    else:
        print(
            f"Warning: no counter groupings found in {metrics_cfg_path}; "
            "the papi_event_chooser fallback will measure each counter individually.",
            file=sys.stderr
        )
        fallback_counter_sets = [[c] for c in counters_with_prefix]

    # Render the orchestration script
    script_content = render_orchestration_script(
        args, selected_counters, fallback_counter_sets, combinations, template, is_sbatch
    )

    # Write the output script
    try:
        with open(args.output, "w") as f:
            f.write(script_content)
        os.chmod(args.output, 0o755)
    except Exception as e:
        print(f"Error writing output: {e}", file=sys.stderr)
        sys.exit(1)

    # Print summary
    print(f"Generated orchestration script: {args.output}")
    print(f"Template: {args.template_script} ({'sbatch' if is_sbatch else 'shell'})")
    print(f"Template variables found: {sorted(template_vars) if template_vars else 'none'}")
    print(f"Selected {len(selected_counters)} counter(s): {', '.join(c for c, _ in selected_counters)}")
    print(f"Parameter combinations: {len(combinations)}")
    max_runs = len(combinations) * len(selected_counters) * args.iterations
    print(
        f"Max runs (before grouping compatible counters via papi_event_chooser): {max_runs}"
    )


if __name__ == "__main__":
    main()