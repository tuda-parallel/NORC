#!/bin/bash
#set -x
app_name="HWCNI"

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
    result=$(whiptail --title "$app_name configuration assistant" --checklist "$1" $((size[0] + $# / 2)) $((size[1] + 10)) $(($# / 2)) "${@:2}" 3>&1 1>&2 2>&3)
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

# configuring metrics to measure
if [ "$1" == "metrics" ]; then
  available_metrics=()
  avail_output=$(papi_avail --check)
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
    find_non_overlapping_sets "${selected_counters[@]}"
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

cat >"$config_dir/build_settings.sh" <<EOL
#!/bin/bash
# Generated with configuration assistant

#########################BUILD OPTIONS######################
export BUILD_JOBS=${num_build_jobs}
export USE_SPACK=${use_spack}
export SPACK_VERSION_SUFFIX=${spack_version_suffix}

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

      if ! text_input "You can optionally specify additonal sbatch prefixes (e.g., #SBATCH --hint=multithread)."; then
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

if $local_execution; then
  cores_this_node=$(getconf _NPROCESSORS_ONLN)
  if ! text_input "Please enter the number of threads to use per rank. By default up to 8 ranks are started, given the $cores_this_node cores of this node, we recommend to use at most $((cores_this_node / 8)) threads per node." $((cores_this_node / 8)); then
    exit 1
  fi
  threads_per_process=$REPLY
  cat >"$config_dir/experiments.cfg" <<EOL
# benchmark param_set sys_template nodes processes_per_node threads_per_process

minife x20y20z20  ${system_name} 1 1 ${threads_per_process}
minife x40y20z20  ${system_name} 1 2 ${threads_per_process}
minife x80y20z20  ${system_name} 1 4 ${threads_per_process}
minife x160y20z20 ${system_name} 1 8 ${threads_per_process}

lammps x20y20z20  ${system_name} 1 1 ${threads_per_process}
lammps x40y20z20  ${system_name} 1 2 ${threads_per_process}
lammps x80y20z20  ${system_name} 1 4 ${threads_per_process}
lammps x160y20z20 ${system_name} 1 8 ${threads_per_process}

lulesh s10r1  ${system_name} 1 1 ${threads_per_process}
lulesh s10r8  ${system_name} 1 8 ${threads_per_process}
EOL
else
  cores_this_node=$(getconf _NPROCESSORS_ONLN)
  if ! text_input "Please enter the number of threads to use per rank. By default up to 8 ranks are started, given the $cores_this_node cores of this node, we recommend to use at most $((cores_this_node / 2)) threads per node." $((cores_this_node / 8)); then
    exit 1
  fi
  threads_per_process=$REPLY
  cat >"$config_dir/experiments.cfg" <<EOL
# benchmark param_set sys_template nodes processes_per_node threads_per_process

minife x20y20z20  ${system_name} 1 1 ${threads_per_process}
minife x40y20z20  ${system_name} 2 1 ${threads_per_process}
minife x80y20z20  ${system_name} 4 1 ${threads_per_process}
minife x160y20z20 ${system_name} 8 1 ${threads_per_process}

lammps x20y20z20  ${system_name} 1 1 ${threads_per_process}
lammps x40y20z20  ${system_name} 2 1 ${threads_per_process}
lammps x80y20z20  ${system_name} 4 1 ${threads_per_process}
lammps x160y20z20 ${system_name} 8 1 ${threads_per_process}

lulesh s10r1  ${system_name} 1 1 ${threads_per_process}
lulesh s10r8  ${system_name} 8 1 ${threads_per_process}
lulesh s10r27 ${system_name} 27 1 ${threads_per_process}
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
