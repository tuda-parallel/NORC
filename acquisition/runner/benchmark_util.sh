source ./macros.sh

even(){
  local cores="0"
  for n in $(seq 2 $(($1-1))); do
    if [ $((n % 2)) = 0 ]; then
      cores="$cores,$n"
    fi
  done
  echo $cores
}

odd(){
  local cores="1"
  for n in $(seq 3 $(($1-1))); do
    if [ $((n % 2)) = 1 ]; then
      cores="$cores,$n"
    fi
  done
  echo $cores
}

execution_directory() {
  local system="$1"
  local benchmark="$2"
  local res_cfg="$3"

  echo "exec/$benchmark.$system.$res_cfg"
}


job_from_template() {
  local system="$1"
  local benchmark="$2"
  local n_nodes="$3"
  local n_procs_benchmark="$4"
  local n_threads="$5"

  # Load system-related info
  source "config/systems/$system/system.sh"

  local exec_dir=$(execution_directory $system $benchmark n${n_nodes}p${n_procs_benchmark}t${n_threads})
  
  mkdir -p "$exec_dir/scratch"
  
  jobscript="$exec_dir/job.sh"
  
  echo "#!/bin/bash" > "$jobscript"
  echo "" >> "$jobscript"

  # Prepend system batch prefix
  local system_batch_prefix="config/systems/$system/batch_prefix"
  if [ -f "$system_batch_prefix" ]; then
    cat "$system_batch_prefix" >> "$jobscript"
    echo "" >> "$jobscript"
  fi

  # Prepend benchmark batch prefix
  local benchmark_batch_prefix="config/benchmarks/$benchmark/batch_prefix"
  if [ -f "$benchmark_batch_prefix" ]; then
    cat "$benchmark_batch_prefix" >> "$jobscript"
    echo "" >> "$jobscript"
  fi

  if [ -d config/benchmarks/$benchmark/resources ]; then
    cp -rf config/benchmarks/$benchmark/resources/* "$exec_dir/scratch/"
    check_warn "WARNING: Benchmark $benchmark has an empty resource folder. Consider deleting it or adding resources."
  fi

  # NOIGENA always runs on half the available cores so that the noise level will always be roughly the same.
  local n_procs_noigena=$(( CORES_PER_NODE / 2 ))
  local n_procs_total=$(( n_procs_benchmark + n_procs_noigena ))

  # Add the job script's main part (still a template)
  cat config/job_templates/$JOB_TEMPLATE.sh >> "$jobscript"

  # Fill in the job template's parameters to create a working script for sbatch.
  sed -i "s|§benchmark|$benchmark|g;
          s|§status_out|$(pwd)/status/out/$benchmark/${system}n${n_nodes}p${n_procs_benchmark}t${n_threads}|g;
          s|§status_err|$(pwd)/status/err/$benchmark/${system}n${n_nodes}p${n_procs_benchmark}t${n_threads}|g;
          s|§nodes|$n_nodes|g;
          s|§procs|$n_procs_benchmark|g;
          s|§noise_procs|$n_procs_noigena|g;
          s|§threads|$n_threads|g;
          s|§total_tasks|$n_procs_total|g;
          s|§cpus|$CORES_PER_NODE|g;
          s|§odd_cpus|$(odd $CORES_PER_NODE)|g;
          s|§even_cpus|$(even $CORES_PER_NODE)|g;
          s|§partition|$PARTITION|g;
          s|§budget|$BUDGET|g;" "$jobscript"

  chmod +x "$jobscript"

}

# calculates a time estimate per run for a series of time measurements
# $1: a directory containing time measurements
# $2: estimation tightness (0 is average, 1 is maximum, values in between interpolate linearly)
estimate_time() {
  local sum=0
  local max=0
  local count=0

  # Flatten the content of all files to a list of numbers and iterate it
  for t in $(cat $1/*); do
    sum=$((sum + t))
    if [[ $t > $max ]]; then
      max=$t
    fi
    count=$((count + 1))
  done

  local avg=$(echo "scale=6; $sum/$count" | bc)
  # Linear interpolation between average and maximum (ceiled)
  echo "$avg $max $2" | awk '{print int(($1 * (1-$3) ) + ($2 * $3) + 0.5)}'
}

# converts seconds into a time value accepted by Slurm
slurmify_time() {
  seconds=$1
  minutes=$((seconds / 60))
  hours=$((minutes / 60))
  days=$((hours / 24))
  printf "%d-%02d:%02d:%02d" $days $((hours % 24)) $((minutes % 60)) $((seconds % 60))
}

# converts a Slurm-formatted time into seconds
unslurmify_time() {
  slurmtime="$1"
  days=0
  hours=0
  minutes=0
  seconds=0

  dt_split=$(echo $slurmtime | sed "s/-/ /g")
  # dd-hh*
  if [ $(echo "$dt_split" | wc -w) = 2 ]; then
    days=$(get_positional 1 $dt_split)
    
    slurmtime=$(get_positional 2 $dt_split)
    hms_split=$(echo $slurmtime | sed "s/:/ /g")
    hms_len=$(echo "$hms_split" | wc -w)
    
    hours=$(get_positional 1 $hms_split)
    # dd-hh:mm*
    if [ $hms_len -gt 1 ]; then minutes=$(get_positional 2 $hms_split); fi
    # dd-hh:mm:ss
    if [ $hms_len -gt 2 ]; then seconds=$(get_positional 3 $hms_split); fi
    
  else
    hms_split=$(echo $slurmtime | sed "s/:/ /g")
    hms_len=$(echo $hms_split | wc -w)
    
    if   [ $hms_len = 1 ]; then
      # mm
      minutes=$(get_positional 1 $hms_split)
    elif [ $hms_len = 2 ]; then
      # mm:ss
      minutes=$(get_positional 1 $hms_split)
      seconds=$(get_positional 2 $hms_split)
    elif [ $hms_len = 3 ]; then
      # hh:mm:ss
      hours=$(get_positional 1 $hms_split)
      minutes=$(get_positional 2 $hms_split)
      seconds=$(get_positional 3 $hms_split)
    fi
  fi
  
  result=$days
  result=$(((result * 24) + hours))
  result=$(((result * 60) + minutes))
  result=$(((result * 60) + seconds))

  echo $result
}


is_array_based() {
  if [[ $(cat $1 | grep "#RUNNER ARRAY" | wc -w) > 0 ]]; then
      echo true
  else
      echo false
  fi
}

is_system_array_based() {
  # Load system-related info
  source "config/systems/$1/system.sh"
  is_array_based config/job_templates/$JOB_TEMPLATE.sh
}