#!/bin/bash
#set -x
# Data acquisition script for config_assistent.sh in the NORC performance measurement pipeline.
#
# Copyright (c) 2026 TU Darmstadt, Germany
# Version: v0.2
# Date: 2025-08-08
#
# Licensed under the BSD 3-Clause License.
# For more information, see the LICENSE file in the project root:
# https://github.com/tuda-parallel/NORC/blob/main/LICENSE
app_name="NORC"

export NEWT_COLORS='
root=white,blue
shadow=black,black
title=red,lightgray
window=lightgray,lightgray
border=blue,lightgray
textbox=black,lightgray
button=white,red
compactbutton=red,lightgray
entry=black,cyan
disentry=cyan,white
'

has_whiptail=false
if whiptail --version >/dev/null; then
  has_whiptail=true
fi

dimensions() {
  tsize=${#1}
  read -a ttysize <<<$(stty size)
  border=6
  if [ $tsize -lt $((ttysize[1] - $border)) ]; then
    width=$((tsize + border))
  else
    width=$((ttysize[1] - border))
  fi
  if [ $width -gt 120 ]; then
    width=120
  fi
  height=$((tsize / width + border + 4 + $(echo "$1" | wc -l)))
  echo $height $width
}

yes_no() {
  if $has_whiptail; then
    TERM=xterm whiptail --title "$app_name configuration assistant" --yesno "$1" $(dimensions "$1") --defaultno
    return $?
  fi

  read -p "$1 [y,N] " -n 1 -r
  echo # (optional) move to a new line
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    return 0
  else
    return 1
  fi
}

infobox() {
  if $has_whiptail; then
    whiptail --title "$app_name configuration assistant" --infobox "$1" $(dimensions "$1")
  fi
  echo "$1"
}

msgbox() {
  if $has_whiptail; then
    whiptail --title "$app_name configuration assistant" --msgbox "$1" $(dimensions "$1")
  fi
  echo "$1"
}

text_input() {
  if $has_whiptail; then
    REPLY=$(whiptail --title "$app_name configuration assistant" --inputbox "$1" $(dimensions "$1") "$2" 3>&1 1>&2 2>&3)
    return $?
  fi

  if [ "$#" -lt 2 ]; then
    read -p "$1" -r
  else
    read -p "$1 [default: $2]" -r
    if [ -z "${REPLY}" ]; then
      REPLY=$2
    fi
  fi
  echo # (optional) move to a new line
  return 0
}

multiline_input() {
  if $has_whiptail; then
    local tmpfile
    tmpfile=$(mktemp)
    if [ -n "$2" ]; then
      printf '%s\n' "$2" >"$tmpfile"
    fi
    REPLY=$(whiptail --title "$app_name configuration assistant" --editbox "$tmpfile" $(dimensions "$1") 3>&1 1>&2 2>&3)
    local status=$?
    rm -f "$tmpfile"
    return $status
  fi

  echo "$1"
  if [ -n "$2" ]; then
    echo "Current value:"
    echo "$2"
  fi
  echo "(Enter one line at a time. Finish with an empty line.)"
  local lines=()
  while IFS= read -r line; do
    [ -z "$line" ] && break
    lines+=("$line")
  done
  REPLY=$(printf '%s\n' "${lines[@]}")
  return 0
}

choosebox() {
  if $has_whiptail; then
    IFS=" " read -r -a size <<<"$(dimensions "$1")"
    #echo "${size[@]}"
    REPLY=$(whiptail --title "$app_name configuration assistant" --menu "$1" $((size[0] + $#)) $((size[1] + 10)) $# "${@:2}" 3>&1 1>&2 2>&3)
    return $?
  fi

  raw_entries=("${@:2}")
  entries=()
  for ((i = 0; i < ${#raw_entries[@]}; i += 2)); do
    entries+=("${raw_entries[i]}")
  done
  echo "$1"
  select option in "${entries[@]}"; do
    if [[ -n "$option" ]]; then
      REPLY=$option
      return 0
    else
      echo "Invalid selection. Please try again."
    fi
  done

}

choose_multiple() {
  if $has_whiptail; then
    IFS=" " read -r -a size <<<"$(dimensions "$1")"
    read -a ttysize <<<"$(stty size)"
    item_count=$(($# / 3))

    # Cap the dialog to the terminal size instead of growing without bound with the item count;
    # whiptail scrolls the list internally when its height is smaller than the item count.
    box_height=$((size[0] + item_count))
    max_height=$((ttysize[0] - 2))
    if [ $box_height -gt $max_height ]; then
      box_height=$max_height
    fi

    box_width=$((size[1] + 10))
    max_width=$((ttysize[1] - 2))
    if [ $box_width -gt $max_width ]; then
      box_width=$max_width
    fi

    list_height=$((box_height - size[0]))
    if [ $list_height -lt 1 ]; then
      list_height=1
    fi

    result=$(whiptail --title "$app_name configuration assistant" --checklist "$1" $box_height $box_width $list_height "${@:2}" 3>&1 1>&2 2>&3)
    ec=$?
    REPLY=($(echo $result | tr -d '"'))
    return $ec
  fi

  raw_entries=("${@:2}")
  options=()
  for ((i = 0; i < ${#raw_entries[@]}; i += 3)); do
    options+=("${raw_entries[i]}")
  done
  options+=("Done")
  # Array to store selected options
  selected_items=()

  # Display the menu and allow the user to select options
  while true; do
    echo "Please choose one or more options (choose 'Done' to finish):"

    # Display the menu
    select option in "${options[@]}"; do
      if [[ "$option" == "Done" ]]; then
        REPLY=("${selected_items[@]}")
        echo "You finished selecting."
        break 2
      elif [[ -n "$option" ]]; then
        # Add selected option to the array if it's a valid selection
        selected_items+=("$option")
        echo "You selected: ${selected_items[*]}"
        break
      else
        echo "Invalid selection. Please try again."
      fi
    done
  done
}

find_non_overlapping_sets() {
  local counters=("$@")
  local used_counters=()
  local sets=()

  while [ "${#counters[@]}" -gt 0 ]; do
    local max_set=()

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
      break
    fi

    sets+=("${max_set[*]}")
    used_counters+=("${max_set[@]}")

    # Remove used counters from the list
    counters=("${counters[@]:j}")
  done

  counter_sets=("${sets[@]}")
}

config_dir="$PWD/config"

# Runs $1 (a bash command or script body) either directly or, if use_sbatch_detection
# is set, as a synchronous sbatch job on a compute node. Login nodes frequently expose
# different (or no) hardware counters than compute nodes, so PAPI's detection commands
# need to run on the same kind of node the benchmarks will actually execute on.
run_detection() {
  local body="$1"
  # Each papi_event_chooser call reinitializes PAPI and probes hardware-counter
  # multiplexing from scratch, so it can take several seconds on its own. Callers
  # that invoke it many times (e.g. once per selected counter) should pass a time
  # budget in seconds via $2; otherwise a short default suffices.
  local time_budget_seconds="${2:-300}"

  if ! $use_sbatch_detection; then
    bash -c "$body"
    return $?
  fi

  local time_limit
  time_limit=$(printf '%02d:%02d:%02d' $((time_budget_seconds / 3600)) $(((time_budget_seconds % 3600) / 60)) $((time_budget_seconds % 60)))

  # /tmp is typically local, per-node scratch on cluster compute nodes, not shared
  # with the submission host, so the job's output would be invisible once it lands
  # on a different node. Use shared project storage instead.
  local job_dir
  job_dir=$(mktemp -d "$BASE_DIR/.norc_detect.XXXXXX")
  local job_script="$job_dir/detect.sh"
  local out_file="$job_dir/detect.out"

  {
    echo "#!/bin/bash"
    echo "#SBATCH --partition=$detection_partition"
    echo "#SBATCH --account=$detection_budget"
    echo "#SBATCH --job-name=NORC-counter-detection"
    echo "#SBATCH --nodes=1"
    echo "#SBATCH --ntasks=1"
    echo "#SBATCH --time=$time_limit"
    echo "#SBATCH --output=$out_file"
    if [ -n "$detection_prefix" ]; then
      echo "$detection_prefix"
    fi
    if [ -f "$BASE_DIR/$INSTALL_DIR/env.sh" ]; then
      echo "source \"$BASE_DIR/$INSTALL_DIR/env.sh\""
    fi
    echo "$body"
  } >"$job_script"

  if ! sbatch --wait "$job_script" >"$job_dir/submit.log" 2>&1; then
    msgbox "Failed to run the counter detection job:\n$(cat "$job_dir/submit.log")"
    rm -rf "$job_dir"
    return 1
  fi

  cat "$out_file" 2>/dev/null
  rm -rf "$job_dir"
}

# configuring metrics to measure
if [ "$1" == "metrics" ]; then
  BASE_DIR="${BASE_DIR:-$PWD}"
  INSTALL_DIR="${INSTALL_DIR:-build}"

  use_sbatch_detection=false
  detection_partition=""
  detection_budget=""
  detection_prefix=""

  if command -v sbatch >/dev/null 2>&1; then
    if yes_no "Detected SLURM. Hardware counters are often only accessible on compute nodes. Do you want to run the counter detection as an sbatch job?"; then
      use_sbatch_detection=true

      detection_systems=()
      for system in "$config_dir"/systems/*/; do
        detection_systems+=("$(basename "$system")")
        detection_systems+=("")
      done

      if [ "${#detection_systems[@]}" -gt 0 ] && choosebox "Choose a system configuration to submit the detection job with:" "${detection_systems[@]}"; then
        detection_system=$REPLY
        source "$config_dir/systems/$detection_system/system.sh"
        detection_partition=$PARTITION
        detection_budget=$BUDGET
        if [ -f "$config_dir/systems/$detection_system/batch_prefix" ]; then
          detection_prefix=$(cat "$config_dir/systems/$detection_system/batch_prefix")
        fi
      else
        if ! text_input "Please specify a partition for the counter detection job."; then
          exit 1
        fi
        detection_partition=$REPLY
        if ! text_input "Please specify a billing account for the counter detection job."; then
          exit 1
        fi
        detection_budget=$REPLY
      fi
    fi
  fi

  available_metrics=()
  avail_output=$(run_detection "papi_avail --check")
  num_hardware_counters=$(grep "Number Hardware Counters" <<<"$avail_output" | awk -F': ' '{print $2}')
  counter_list=$(grep "PAPI_" <<<"$avail_output")

  while IFS= read -r line; do
    first_element=$(echo "$line" | awk '{print $1}')
    last_element=$(echo "$line" | awk '{$1=$2=$3=""; print $0}' | sed 's/^ *//')
    available_metrics+=("$first_element")
    available_metrics+=("$last_element")
    available_metrics+=("ON")
  done <<<"$counter_list"

  if choose_multiple "Please select the hardware counter presets to analyze from the list below. Your system has $num_hardware_counters raw hardware counters simultaneously available. If you use more the runs will be split up." "${available_metrics[@]}"; then
    selected_counters=("${REPLY[@]}")

    if $use_sbatch_detection; then
      # Run the whole set-partitioning algorithm in a single remote job instead of
      # submitting one job per papi_event_chooser call, which would be far too slow.
      remote_script=$(
        declare -f find_non_overlapping_sets
        printf 'find_non_overlapping_sets'
        printf ' %q' "${selected_counters[@]}"
        printf '\n'
        echo 'printf "%s\n" "${counter_sets[@]}"'
      )
      # Roughly bounded by two papi_event_chooser calls per selected counter (one
      # that succeeds and one that probes the next group's boundary), each of
      # which can take several seconds, plus a fixed baseline for job startup.
      detection_time_budget=$((60 + 10 * ${#selected_counters[@]}))
      counter_sets_raw=$(run_detection "$remote_script" "$detection_time_budget")
      mapfile -t counter_sets <<<"$counter_sets_raw"
    else
      find_non_overlapping_sets "${selected_counters[@]}"
    fi

    true >"$config_dir/metrics.cfg"
    for counter_set in "${counter_sets[@]}"; do
      tr -s '[:blank:]' ',' <<<"${counter_set[*]}" >>"$config_dir/metrics.cfg"
    done
    exit 0
  fi
  exit 1
fi

# start of main configuration

use_modules=false
use_spack=false
modules=""
pre_load_command=""
spack_version_suffix=""

load_modules() {
  if ! text_input "$app_name needs the following components: Score-P (8 or higher) with PAPI support, CMake, and SIONlib.\nPlease enter the list of modules to load:"; then
    exit 1
  fi
  infobox "Trying to load modules."
  (module load $REPLY)
  return $?
}

if command -v module --version >/dev/null 2>&1; then
  if yes_no "A module system has been found. Do you want to use it?"; then
    use_modules=true
    while ! load_modules; do
      :
    done
    modules=$REPLY
  fi
else
  if yes_no "No module system has been found. Do you want to use spack to install the dependencies?"; then
    use_spack=true
    if text_input "Do you want to specify a suffix for the spack installation (e.g., %gcc@12)?"; then
      spack_version_suffix=$REPLY
    fi
  fi
fi

if $use_spack || $use_modules; then
  :
else
  if scorep-info config-summary | grep "PAPI support:[[:space:]]*yes" >/dev/null; then
    infobox "Found compatible Score-P installation."
  else
    if ! text_input "$app_name needs the following components: Score-P (8 or higher) with PAPI support\nPlease enter the command to load a compatible Score-P version:"; then
      exit 1
    fi
    pre_load_command=$REPLY
    while ! ($pre_load_command && (scorep-info config-summary | grep "PAPI support:[[:space:]]*yes")) >/dev/null; do
      if ! text_input "$app_name needs the following components: Score-P (8 or higher) with PAPI support\nPlease enter the command to load a compatible Score-P version:"; then
        exit 1
      fi
      pre_load_command=$REPLY
    done
  fi
fi

num_build_jobs=$(getconf _NPROCESSORS_ONLN)
if ! text_input "Please enter number of build jobs to use." $num_build_jobs; then
  exit 1
fi

# Installation restricts the PATH it runs with to avoid ambiguity from unrelated directories on it.
# By default every directory of the current CLEAN_PATH is kept; the user can deselect specific ones.
declare -A seen_path_dirs
path_entries=()
IFS=':' read -r -a raw_path_entries <<<"$CLEAN_PATH"
for dir in "${raw_path_entries[@]}"; do
  if [ -n "$dir" ] && [ -z "${seen_path_dirs[$dir]}" ]; then
    seen_path_dirs[$dir]=1
    path_entries+=("$dir")
  fi
done

path_options=()
for dir in "${path_entries[@]}"; do
  path_options+=("$dir" "" "ON")
done

if choose_multiple "Select which directories of your current PATH to keep during installation." "${path_options[@]}"; then
  clean_path=$(
    IFS=:
    echo "${REPLY[*]}"
  )
else
  exit 1
fi

# Make sure sbatch stays reachable even if its directory was deselected above, since job submission depends on it.
sbatch_path=$(command -v sbatch)
if [ -n "$sbatch_path" ]; then
  sbatch_dir=$(dirname "$sbatch_path")
  case ":$clean_path:" in
  *":$sbatch_dir:"*) ;;
  *) clean_path="$clean_path:$sbatch_dir" ;;
  esac
fi

cat >"$config_dir/build_settings.sh" <<EOL
#!/bin/bash
# Generated with configuration assistant

#########################BUILD OPTIONS######################
export BUILD_JOBS=${num_build_jobs}
export USE_SPACK=${use_spack}
export SPACK_VERSION_SUFFIX=${spack_version_suffix}
export CLEAN_PATH="${clean_path}"

###########################SCORE-P##########################
export SCOREP_VERSION="8.3"

EOL

#create modules file
if $use_modules; then
  cat >"$config_dir/modules.sh" <<EOL
#!/bin/bash -x
# Generated with configuration assistant
module load ${modules}
EOL
elif $use_spack; then
  cat >"$config_dir/modules.sh" <<EOL
#!/bin/bash -x
# Generated with configuration assistant
EOL
else
  cat >"$config_dir/modules.sh" <<EOL
#!/bin/bash -x
# Generated with configuration assistant
module load ${pre_load_command}
EOL
fi

local_execution=false
if ! command -v sbatch >/dev/null 2>&1; then
  msgbox "Could not detect SLURM. Changing to local execution."
  local_execution=true
else
  if yes_no "Detected SLURM. Do you want to use local execution instead?"; then
    local_execution=true
  fi
fi

if $local_execution; then
  touch "$config_dir/force_local_run"
elif [ -f "$config_dir/force_local_run" ]; then
  rm "$config_dir/force_local_run"
fi

job_template=""
cores_per_node=8
partition=""
account=""

systems=()
for system in "$config_dir"/systems/*/; do
  systems+=("$(basename "$system")")
  systems+=("")
done
systems+=("[new]")
systems+=("Create new system configuration")
while true; do
  if ! choosebox "Choose a configuration for your system or create a new one:" "${systems[@]}"; then
    exit 1
  fi
  if [ "$REPLY" == "[new]" ]; then
    if ! text_input "Please enter name"; then
      continue
    fi
    system_name=$REPLY
    cores_per_node=$(getconf _NPROCESSORS_ONLN)
    if ! text_input "Please enter number cores per rank/node." $cores_per_node; then
      continue
    fi
    cores_per_node=$REPLY

    job_templates=()
    for jt in "$config_dir"/job_templates/*.sh; do
      name="$(basename "$jt" ".sh")"
      echo ""
      if [[ $local_execution == false || "$name" == *local ]]; then
        job_templates+=("$name")
        job_templates+=("")
      fi
    done
    if ! choosebox "Please select a job template." "${job_templates[@]}"; then
      continue
    fi
    job_template=$REPLY
    if ! $local_execution; then
      if ! text_input "Please specify a partition for the execution."; then
        continue
      fi
      partition=$REPLY

      if ! text_input "Please specify a billing account for the execution."; then
        continue
      fi
      account=$REPLY

      if ! multiline_input "You can optionally specify additional sbatch prefixes, one per line (e.g., #SBATCH --hint=multithread)."; then
        continue
      fi
      batch_prefix=$REPLY
    fi

    system_dir="$config_dir/systems/$system_name"
    mkdir -p "$system_dir"
    cat >"$system_dir/system.sh" <<EOL
#!/bin/bash
# Generated with configuration assistant
export CORES_PER_NODE=${cores_per_node}
export JOB_TEMPLATE="${job_template}"
EOL
    if ! $local_execution; then
      cat >>"$system_dir/system.sh" <<EOL
export PARTITION="${partition}"
export BUDGET="${account}"
EOL
      echo "$batch_prefix" >"$system_dir/batch_prefix"
    fi
    break
  else
    system_name=$REPLY
    break
  fi
done

if ! $local_execution; then
  infobox "Submitting a test job to sbatch using the configured job template to verify the configuration."

  # Reuse the same job-generation logic run_benchmarks.sh uses, so the test job is built exactly like a real one.
  runner_dir="$(cd "$(dirname "$0")/../runner" && pwd)"
  source <(sed '/^source \.\/macros\.sh$/d' "$runner_dir/benchmark_util.sh")

  test_benchmark="norc_config_test"
  test_res_cfg="n1p1t1"
  export STATUS_DIR="$config_dir/../status_test"
  rm -rf "$STATUS_DIR" "exec/${test_benchmark}.${system_name}.${test_res_cfg}"
  mkdir -p "$STATUS_DIR/jobs" \
    "$STATUS_DIR/out/${test_benchmark}/${system_name}${test_res_cfg}" \
    "$STATUS_DIR/err/${test_benchmark}/${system_name}${test_res_cfg}"

  job_from_template "$system_name" "$test_benchmark" 1 1 1

  # Absolutized because the job runs with its scratch dir as CWD, from where a relative path would resolve wrong.
  exec_dir="$(pwd)/$(execution_directory "$system_name" "$test_benchmark" "$test_res_cfg")"
  export ARRAY_DIR="$exec_dir/array"
  mkdir -p "$ARRAY_DIR" "$exec_dir/timings"

  experiment_directory="$exec_dir/timings/test_experiment"
  mkdir -p "${experiment_directory}.tmp"
  cat >"$ARRAY_DIR/0" <<EOL
export EXPERIMENT_DIRECTORY="$experiment_directory"
export NOISE_PATTERN=NO_NOISE
export PARAMSET_NAME=test
export BENCHMARK_PARAMS=""
export SCOREP_METRIC_PAPI=""
EOL

  sed -i "s/§time/$(slurmify_time 120)/g" "$exec_dir/job.sh"

  # There is no real "norc_config_test" binary -- this job only exists to verify that
  # sbatch/srun submission itself works, so run something that's always available instead.
  sed -i "s/\"$test_benchmark\"/true/g" "$exec_dir/job.sh"

  pushd "$exec_dir/scratch" >/dev/null
  if [ "$(is_array_based ../job.sh)" = true ]; then
    sbatch_output=$(sbatch --wait --array=0-0 ../job.sh 2>&1)
  else
    sbatch_output=$(sbatch --wait ../job.sh 2>&1)
  fi
  sbatch_status=$?
  popd >/dev/null

  test_failed=false
  if [ $sbatch_status -ne 0 ]; then
    test_failed=true
    msgbox "Test job submission failed:\n$sbatch_output\n\nPlease double-check your partition, account, and module settings."
  else
    test_job_id=$(echo "$sbatch_output" | grep -oE '[0-9]+' | tail -1)
    test_result=$(cat "$STATUS_DIR/jobs/${test_job_id}_0" 2>/dev/null)
    if [ "$test_result" = "0" ]; then
      msgbox "Test job (ID $test_job_id) completed successfully. Your configuration appears to be working."
    else
      test_failed=true
      msgbox "Test job (ID $test_job_id) did not finish successfully (exit status: ${test_result:-unknown}).\nCheck $STATUS_DIR/out and $STATUS_DIR/err for details."
    fi
  fi

  rm -rf "$STATUS_DIR" "exec/${test_benchmark}.${system_name}.${test_res_cfg}"
  rmdir exec 2>/dev/null

  if $test_failed; then
    exit 1
  fi
fi

if $local_execution; then
  cores_this_node=$(getconf _NPROCESSORS_ONLN)
  if ! text_input "Please enter the number of threads to use per rank. By default up to 8 ranks are started, given the $cores_this_node cores of this node, we recommend to use at most $((cores_this_node / 8)) threads per node." $((cores_this_node / 8)); then
    exit 1
  fi
  threads_per_process=$REPLY
  cat >"$config_dir/experiments.cfg" <<EOL
# benchmark param_set sys_template nodes processes_per_node threads_per_process

minife weak_x_scaled ${system_name} 1 1 ${threads_per_process}
minife weak_x_scaled ${system_name} 1 2 ${threads_per_process}
minife weak_x_scaled ${system_name} 1 4 ${threads_per_process}
minife weak_x_scaled ${system_name} 1 8 ${threads_per_process}

lammps weak_x_scaled ${system_name} 1 1 ${threads_per_process}
lammps weak_x_scaled ${system_name} 1 2 ${threads_per_process}
lammps weak_x_scaled ${system_name} 1 4 ${threads_per_process}
lammps weak_x_scaled ${system_name} 1 8 ${threads_per_process}

lulesh s_scaled ${system_name} 1 1 ${threads_per_process}
lulesh s_scaled ${system_name} 1 8 ${threads_per_process}
EOL
else
  cores_this_node=$(getconf _NPROCESSORS_ONLN)
  if ! text_input "Please enter the number of threads to use per rank. By default up to 8 ranks are started, given the $cores_this_node cores of this node, we recommend to use at most $((cores_this_node / 2)) threads per node." $((cores_this_node / 8)); then
    exit 1
  fi
  threads_per_process=$REPLY
  cat >"$config_dir/experiments.cfg" <<EOL
# benchmark param_set sys_template nodes processes_per_node threads_per_process

minife weak_x_scaled ${system_name} 1 1 ${threads_per_process}
minife weak_x_scaled ${system_name} 2 1 ${threads_per_process}
minife weak_x_scaled ${system_name} 4 1 ${threads_per_process}
minife weak_x_scaled ${system_name} 8 1 ${threads_per_process}

lammps weak_x_scaled ${system_name} 1 1 ${threads_per_process}
lammps weak_x_scaled ${system_name} 2 1 ${threads_per_process}
lammps weak_x_scaled ${system_name} 4 1 ${threads_per_process}
lammps weak_x_scaled ${system_name} 8 1 ${threads_per_process}

lulesh s_scaled ${system_name} 1 1 ${threads_per_process}
lulesh s_scaled ${system_name} 8 1 ${threads_per_process}
lulesh s_scaled ${system_name} 27 1 ${threads_per_process}
EOL
fi
editor=${FCEDIT:-${VISUAL:-${EDITOR}}}
if ! $editor --version >/dev/null 2>&1; then
  if nano --version >/dev/null 2>&1; then
    editor="nano"
  elif vim --version >/dev/null 2>&1; then
    editor="vim"
  elif vi --version >/dev/null 2>&1; then
    editor="vi"
  else
    editor="ed"
  fi
fi
if yes_no "We prepared a default experiment configuration. Do you want to edit it now?"; then
  $editor "$config_dir/experiments.cfg"
fi
