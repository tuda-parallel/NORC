#!/bin/bash
# Submit the PolyBench Phase-3a modeling-quality calibration as a SLURM job.
#
# Reuses acquisition's actual per-system config instead of a NORC-modeling-quality-
# owned job template: config/systems/<system>/system.sh picks PARTITION/BUDGET/
# CORES_PER_NODE/JOB_TEMPLATE, and the SBATCH header is lifted straight out of
# config/job_templates/$JOB_TEMPLATE.sh (+ that system's batch_prefix), the same
# template acquisition/runner/benchmark_util.sh's job_from_template() uses -- so
# if the user has tuned it for their cluster (partition, hint flags, mem, ...),
# calibration jobs pick that up automatically. Only the SBATCH header is reused;
# the rest of those templates is acquisition's own NOIGENA-noise benchmark loop,
# which doesn't apply to this single-shot calibration run.
#
# This script only *reads* under acquisition/, with one exception: if Phase 4's
# `extrap` dependency is missing from acquisition's build venv
# ($ACQUISITION/tmp/.venv, created unconditionally by acquisition/install.sh),
# it asks for interactive confirmation before installing it there -- never
# installs anything without that confirmation, and skips Phase 4 for this run
# if you decline or the venv doesn't exist. Nothing else under acquisition/ is
# ever modified, so the regular acquisition pipeline is untouched.
#
# Usage:
#   ./submit_calibration_job.sh <system> <experiment_root> [extra run_benchmarks.py args...]
#   ./submit_calibration_job.sh <system> --counters PAPI_A,PAPI_B,... [extra args...]
#   ./submit_calibration_job.sh <system> --counters-file counters.list [extra args...]
#   ./submit_calibration_job.sh <system> --resume exec_dir [extra args...]
#
#   <system>          One of NORC/acquisition/config/systems/* (e.g. local, gh,
#                     dp-cn-seq). Picks PARTITION/BUDGET/CORES_PER_NODE/JOB_TEMPLATE.
#   <experiment_root> NORC experiment root to score for the Phase-2 resilience
#                     cutoff (same argument norc_redundancy takes), via
#                     generate_papi_counters.py.
#   --counters        Skip that scoring step entirely and measure exactly this
#                     comma-separated counter list (the "PAPI_" prefix is
#                     added if missing, same as generate_papi_counters.py).
#   --counters-file   Skip scoring and use this papi_counters.list-format file
#                     as-is (one "PAPI_XXX", entry per line, // comments OK).
#   --resume          Continue a previous run instead of starting a new one:
#                     reuses exec_dir (an exec/polybench.<system>.<timestamp>/
#                     dir from a prior call) as-is -- same papi_counters.list,
#                     same --output-dir -- so run_benchmarks.py finds that
#                     run's results.jsonl and skips whatever's already OK in
#                     it (e.g. after a timed-out job) instead of redoing it.
#   extra args        Forwarded to run_benchmarks.py (e.g. --multipliers, --benchmarks).
#
# Env overrides:
#   POLYBENCH_DIR     Path to the NORC-side PolyBench dir (default: the vendored
#                     benchmarks/polybench, containing run_benchmarks.py and the
#                     PolyBenchC-4.2.1-OpenMP checkout; override if using a
#                     different one).
#   SLURM_TIME        Job time budget, HH:MM:SS. Default: estimated from
#                     run_benchmarks.py --estimate-only (worst-case timeout
#                     budget across every benchmark/multiplier/mode combo,
#                     +20% margin), falling back to 02:00:00 if that fails.

set -euo pipefail

MQ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORC_ROOT="$(dirname "$MQ_DIR")"
ACQ_DIR="$NORC_ROOT/acquisition"
POLYBENCH_DIR="${POLYBENCH_DIR:-$MQ_DIR/benchmarks/polybench}"

print_usage() {
  echo "Usage: $0 <system> <experiment_root> [extra run_benchmarks.py args...]" >&2
  echo "       $0 <system> --counters PAPI_A,PAPI_B,... [extra args...]" >&2
  echo "       $0 <system> --counters-file counters.list [extra args...]" >&2
  echo "       $0 <system> --resume exec_dir [extra args...]" >&2
}

if [ $# -lt 2 ]; then
  print_usage
  exit 1
fi
system="$1"
case "$system" in
  --*)
    echo "error: '$system' looks like a flag, but <system> is required first -- did you forget it?" >&2
    print_usage
    exit 1
    ;;
esac
shift
case "$1" in
  --counters)
    counters_csv="$2"
    shift 2
    ;;
  --counters-file)
    counters_file_src="$2"
    if [ ! -f "$counters_file_src" ]; then
      echo "error: --counters-file '$counters_file_src' does not exist" >&2
      exit 1
    fi
    shift 2
    ;;
  --resume)
    if [ ! -d "$2" ]; then
      echo "error: --resume '$2' does not exist" >&2
      exit 1
    fi
    # Must be absolute: the job script cd's into $POLYBENCH_DIR before using
    # this, so a relative path (e.g. copy-pasted from `ls exec/`) would
    # silently resolve against the wrong directory once the job's cwd changes.
    resume_dir="$(cd "$2" && pwd)"
    if [ ! -f "$resume_dir/papi_counters.list" ]; then
      echo "error: --resume '$resume_dir' has no papi_counters.list -- not a prior submit_calibration_job.sh run?" >&2
      exit 1
    fi
    shift 2
    ;;
  *)
    experiment_root="$1"
    shift
    ;;
esac
extra_args=("$@")

system_dir="$ACQ_DIR/config/systems/$system"
if [ ! -f "$system_dir/system.sh" ]; then
  echo "error: no such system '$system' (looked in $system_dir/system.sh)" >&2
  echo "available systems: $(ls "$ACQ_DIR/config/systems")" >&2
  exit 1
fi

if [ ! -d "$POLYBENCH_DIR" ]; then
  echo "error: PolyBench checkout not found at '$POLYBENCH_DIR' -- set POLYBENCH_DIR" >&2
  exit 1
fi

# config_done is acquisition/install.sh's own marker that its config assistant
# has run -- if it's missing, acquisition was never installed/configured on
# this system at all, and everything below (system.sh's CORES_PER_NODE, the
# job template, the PAPI/compiler environment) would be guesswork.
if [ ! -f "$ACQ_DIR/config/config_done" ]; then
  echo "error: '$ACQ_DIR/config/config_done' not found -- acquisition needs to be installed" \
       "first (run acquisition/install.sh)" >&2
  exit 1
fi

# Reuse the same PARTITION/BUDGET/CORES_PER_NODE/JOB_TEMPLATE conventions the
# regular acquisition pipeline uses (config/systems/<system>/system.sh).
# shellcheck disable=SC1090
source "$system_dir/system.sh"

job_template="$ACQ_DIR/config/job_templates/$JOB_TEMPLATE.sh"
if [ ! -f "$job_template" ]; then
  echo "error: system '$system' names JOB_TEMPLATE='$JOB_TEMPLATE', but '$job_template' does not exist" >&2
  exit 1
fi

if [ -n "${resume_dir:-}" ]; then
  # Reuse the prior run's exec dir as-is: same papi_counters.list, and
  # crucially the same --output-dir, so run_benchmarks.py finds that run's
  # results.jsonl and skips whatever's already OK in it instead of redoing it.
  exec_dir="$resume_dir"
  counters_file="$exec_dir/papi_counters.list"
  echo "Resuming $exec_dir"
else
  exec_dir="$MQ_DIR/exec/polybench.$system.$(date +%Y%m%d_%H%M%S)"
  counters_file="$exec_dir/papi_counters.list"
fi
mkdir -p "$exec_dir/status_out" "$exec_dir/status_err" "$exec_dir/results"

if [ -n "${resume_dir:-}" ]; then
  : # counters_file already exists in $resume_dir, nothing to generate
elif [ -n "${counters_csv:-}" ]; then
  # Same "PAPI_" prefix convention as generate_papi_counters.py's to_papi_name(),
  # so "TOT_CYC" and "PAPI_TOT_CYC" both work.
  {
    echo "// Explicit --counters list, no norc.core.score involved"
    IFS=',' read -ra names <<<"$counters_csv"
    for name in "${names[@]}"; do
      [ -z "$name" ] && continue
      case "$name" in
        PAPI_*) echo "\"$name\"," ;;
        *) echo "\"PAPI_$name\"," ;;
      esac
    done
  } > "$counters_file"
elif [ -n "${counters_file_src:-}" ]; then
  cp "$counters_file_src" "$counters_file"
else
  # Scoring the experiment root is plain Python/file-I/O over already-computed
  # measurements -- no need to burn a cluster node allocation on it, so it runs
  # here at submission time rather than as a step inside the job.
  python3 "$MQ_DIR/generate_papi_counters.py" "$experiment_root" --ranked -o "$counters_file"
fi

# Size the SLURM --time request from the same worst-case budget the job itself
# will use (every combo timing out, at --omp-threads/--papi-counters-file/
# --timeout/etc as actually passed) rather than a guess -- --estimate-only
# does the counting/discovery without compiling or running anything, so this
# is cheap even though it re-runs the same benchmark discovery the job does.
if [ -n "${SLURM_TIME:-}" ]; then
  time_budget="$SLURM_TIME"
else
  estimate_output=$(python3 "$POLYBENCH_DIR/run_benchmarks.py" \
    --papi-counters-file "$counters_file" "${extra_args[@]}" --estimate-only)
  estimated_seconds=$(echo "$estimate_output" | awk -F= '/^ESTIMATED_SECONDS=/{print $2}')
  if [ -z "$estimated_seconds" ]; then
    echo "[WARN] could not estimate a time budget (see output above) -- falling back to 02:00:00" >&2
    time_budget="02:00:00"
  else
    # +20% margin on top of that worst-case budget.
    padded_seconds=$(( estimated_seconds * 12 / 10 ))
    days=$((padded_seconds / 86400))
    hours=$((padded_seconds % 86400 / 3600))
    minutes=$((padded_seconds % 3600 / 60))
    seconds=$((padded_seconds % 60))
    if [ "$days" -gt 0 ]; then
      time_budget=$(printf '%d-%02d:%02d:%02d' "$days" "$hours" "$minutes" "$seconds")
    else
      time_budget=$(printf '%02d:%02d:%02d' "$hours" "$minutes" "$seconds")
    fi
    echo "Estimated worst-case budget: ${estimated_seconds}s -> requesting --time=$time_budget (+20% margin)"
  fi
fi

# Phase 4 (compare_to_ground_truth.py) needs `extrap`, which isn't one of this
# project's required dependencies. Check for it in acquisition's own build venv
# (install.sh always creates $TMP_DIR/.venv there, regardless of system) rather
# than silently installing anything -- this runs interactively at submission
# time on the login node, not inside the (non-interactive) job, specifically so
# we can ask before touching that venv.
acq_venv_python="$ACQ_DIR/tmp/.venv/bin/python"
run_phase4=false
if [ -x "$acq_venv_python" ]; then
  if "$acq_venv_python" -c "import extrap" >/dev/null 2>&1; then
    run_phase4=true
  else
    echo "extrap is not installed in acquisition's build venv ($acq_venv_python)."
    read -r -p "Install it now (runs '$acq_venv_python -m pip install extrap')? [y/N] " reply
    if [[ "$reply" =~ ^[Yy]$ ]]; then
      "$acq_venv_python" -m pip install extrap
      run_phase4=true
    else
      echo "Skipping Phase 4 (compare_to_ground_truth.py) for this run."
    fi
  fi
else
  echo "[WARN] acquisition build venv not found at '$acq_venv_python' (run acquisition/install.sh " \
       "first) -- skipping Phase 4 (compare_to_ground_truth.py)" >&2
fi

jobscript="$exec_dir/job.sh"

{
  echo "#!/bin/bash"
  echo

  # Same batch_prefix convention as job_from_template(): a system may add its
  # own SBATCH lines (e.g. --hint) on top of the job template's.
  system_batch_prefix="$ACQ_DIR/config/systems/$system/batch_prefix"
  if [ -f "$system_batch_prefix" ]; then
    cat "$system_batch_prefix"
    echo
  fi

  # Lift just the leading SBATCH header (directives/comments/blank lines) out
  # of acquisition's own job template -- everything after that is its
  # NOIGENA-noise benchmark loop, which this single calibration run has no use
  # for. "#RUNNER ARRAY" is a marker for acquisition's own runner, not us.
  awk '/^#RUNNER ARRAY/ {next} /^#SBATCH/ || /^#/ || /^[[:space:]]*$/ {print; next} {exit}' "$job_template"

  # The lifted header only requests --ntasks-per-node 1 (it's written for
  # acquisition's multi-task noise+benchmark split, collapsed to 1 task here)
  # plus --exclusive. Unlike acquisition's jobs, ours is a single process that
  # spawns OMP_NUM_THREADS=$CORES_PER_NODE threads itself, so request those
  # cores explicitly instead of relying on --exclusive alone to imply them.
  echo "#SBATCH --cpus-per-task=$CORES_PER_NODE"
  echo

  # Source acquisition's environment BEFORE `set -euo pipefail` (below) and
  # before anything else: third-party module systems / Spack's setup-env.sh
  # are notorious for benign nonzero returns or referencing variables that
  # don't exist yet, which would otherwise abort the job right here under -e.
  #
  # Two pieces, both needed:
  #  - config/modules.sh: the actual, current `module load ...` commands.
  #    acquisition/runner/run_benchmarks.sh sources a copy of this
  #    (experiment/config/modules.sh, made at install time) before submitting
  #    real acquisition jobs; we use the source file directly instead, since
  #    that copy only exists while an experiment/ dir is still around (deleted
  #    e.g. by acquisition's own -f/force-rebuild, or just cleaned up by hand).
  #    A module load can set CPATH/LIBRARY_PATH/PAPI_ROOT/etc, none of which
  #    env.sh (next) captures.
  #  - build/env.sh: a PATH/LD_LIBRARY_PATH snapshot frozen at install time,
  #    plus (if USE_SPACK) sourcing Spack's setup-env.sh + `spack load mpi` --
  #    this is what makes `spack location -i papi` resolve at all.
  acq_modules_script="$ACQ_DIR/config/modules.sh"
  if [ -f "$acq_modules_script" ]; then
    printf 'source "%s"\n' "$acq_modules_script"
  else
    echo "echo \"[WARN] '$acq_modules_script' not found (run acquisition/install.sh first) --\" \\"
    echo "     \"module-loaded PAPI/compiler resolution will fall back to whatever is already on PATH\" >&2"
  fi
  acq_env_script="$ACQ_DIR/build/env.sh"
  if [ -f "$acq_env_script" ]; then
    printf 'source "%s"\n' "$acq_env_script"
  else
    echo "echo \"[WARN] '$acq_env_script' not found (run acquisition/install.sh first) --\" \\"
    echo "     \"Spack-based PAPI/compiler resolution will fall back to whatever is already on PATH\" >&2"
  fi
  echo

  echo "set -euo pipefail"
  echo
  echo 'echo "=== Phase 3a PolyBench modeling-quality calibration ==="'
  echo 'echo "Host: $(hostname)"'
  echo 'echo "Start: $(date)"'
  echo
  echo "cd \"$POLYBENCH_DIR\""
  echo
  echo "# Run PolyBench's own orchestrator, restricted to the counters already"
  echo "# selected pre-submission (see counters_file below), via the"
  echo "# --papi-counters-file flag (additive change to run_benchmarks.py, reuses"
  echo "# the existing write_custom_polybench_source mechanism --all-papi-presets"
  echo "# already relies on). Build artifacts land under this run's own exec dir"
  echo "# too, instead of the shared benchmarks/polybench/pb_run/build default."
  printf 'python3 run_benchmarks.py --papi-counters-file "%s" --omp-threads %s --output-dir "%s/results" --build-dir "%s/build" %s\n' \
    "$counters_file" "$CORES_PER_NODE" "$exec_dir" "$exec_dir" "${extra_args[*]}"
  echo
  echo "# Phase 4: model each metric's growth with Extra-P and compare it against"
  echo "# GROUND_TRUTH.txt's known complexity, writing into this run's results/"
  echo "# dir instead of next to the scripts."
  printf 'python3 to_extrap.py "%s/results/results.json" "%s/results/results_extrap.json"\n' \
    "$exec_dir" "$exec_dir"
  if [ "$run_phase4" = true ]; then
    printf '"%s" compare_to_ground_truth.py --results-dir "%s/results"\n' \
      "$acq_venv_python" "$exec_dir"
  else
    echo "echo \"[SKIP] compare_to_ground_truth.py (extrap unavailable, see submission-time output)\" >&2"
  fi
  echo
  echo 'echo "End: $(date)"'
  echo 'echo "=== Done ==="'
} > "$jobscript"

sed -i \
  -e "s|§benchmark|polybench-calibration|g" \
  -e "s|§partition|${PARTITION:-}|g" \
  -e "s|§budget|${BUDGET:-}|g" \
  -e "s|§time|$time_budget|g" \
  -e "s|§status_out|$exec_dir/status_out|g" \
  -e "s|§status_err|$exec_dir/status_err|g" \
  -e "s|§nodes|1|g" \
  -e "s|§total_tasks|1|g" \
  -e "s|§global_tasks|1|g" \
  "$jobscript"
chmod +x "$jobscript"

echo "Job script: $jobscript"
echo "Results will land in: $exec_dir/results"

if [ "$system" = "local" ]; then
  # Mirrors acquisition's -l/--local mode: no real scheduler, run directly.
  echo "system 'local' has no scheduler -- running job.sh directly."
  bash "$jobscript"
else
  # Same submission convention as acquisition/runner/run_benchmarks.sh's
  # run_arrays(): a plain sbatch with --dependency=singleton. No --array,
  # since this is a single-task calibration run, not a job-array sweep.
  batch_output=$(sbatch --dependency=singleton "$jobscript")
  echo "$batch_output"
  job_id=$(echo "$batch_output" | awk '/Submitted batch job/{print $NF}')
  echo "Submitted as job $job_id"
fi
