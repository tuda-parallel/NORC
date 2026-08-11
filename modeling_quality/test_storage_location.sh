#!/bin/bash
# Self-check for submit_calibration_job.sh's storage-location logic (default
# to <experiment_root>/modeling_quality/, --local / --experiment-root
# overrides). Exercises the same arg-parsing + exec_dir snippet without
# running a real job.
set -euo pipefail

MQ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve() {
  # Mirrors submit_calibration_job.sh's parsing for everything after <system>.
  local_storage=false
  explicit_experiment_root=""
  experiment_root=""
  remaining=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --local) local_storage=true; shift ;;
      --experiment-root) explicit_experiment_root="$2"; shift 2 ;;
      --counters|--counters-file) shift 2 ;;
      *) if [ -z "$experiment_root" ] && [[ "$1" != --* ]]; then experiment_root="$1"; fi; remaining+=("$1"); shift ;;
    esac
  done

  if [ "$local_storage" = true ]; then
    echo "$MQ_DIR/exec"
  elif [ -n "$experiment_root" ]; then
    echo "$experiment_root/modeling_quality"
  elif [ -n "$explicit_experiment_root" ]; then
    echo "$explicit_experiment_root/modeling_quality"
  else
    echo "$MQ_DIR/exec"
  fi
}

assert_eq() {
  if [ "$1" != "$2" ]; then
    echo "FAIL: expected '$2', got '$1'" >&2
    exit 1
  fi
}

assert_eq "$(resolve /exp)" "/exp/modeling_quality"
assert_eq "$(resolve /exp --local)" "$MQ_DIR/exec"
assert_eq "$(resolve --counters PAPI_TOT_INS)" "$MQ_DIR/exec"
assert_eq "$(resolve --counters PAPI_TOT_INS --experiment-root /exp2)" "/exp2/modeling_quality"
assert_eq "$(resolve --counters-file f.list --experiment-root /exp3 --local)" "$MQ_DIR/exec"

echo ok
