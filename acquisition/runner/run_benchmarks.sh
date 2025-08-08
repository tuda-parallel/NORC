#!/bin/bash

# This file is copied to the build directory and runs all measurements.

source ./init.sh
source ./macros.sh
source experiment/config/modules.sh
source ./benchmark_util.sh

SCRIPT_NAME="$0"

print_usage() {
  echo "Usage: $SCRIPT_NAME [OPTION]..."
  echo "OPTIONS:"

  echo "\t-h, --help"
  echo "\t\tPrints this help message"

  echo "\t-i N, --iterations N"
  echo "\t\tNumber of iterations for each benchmark"

  echo "\t-l, --local:"
  echo "\t\tExecute benchmarks locally with mpirun rather than Slurm"
  echo "\t\tDO NOT USE ON LOGIN NODES!"

  echo "\t-r N, --retry N:"
  echo "\t\t Maximum number of retries for failed jobs"

  echo "\t-t, --reset-time:"
  echo "\t\t Remove previous time measurements and use the initial estimate for each benchmark"
}

run_arrays() {
  print_info "Running jobs"

  export SCOREP_OVERWRITE_EXPERIMENT_DIRECTORY=true
  rm -f "$JOB_MAP_FILE"
  mkdir -p "$STATUS_DIR/jobs"

  local prg_total=$(ls exec/ | wc -w)
  local prg_current=1
  source ../progress.sh

  for job_dir in $(ls exec/); do
    progress $((prg_current * 100 / prg_total))
    prg_current=$((prg_current + 1))

    local job=$(echo $job_dir | tr "." " ")
    local benchmark=$(get_positional 1 $job)
    local system=$(get_positional 2 $job)
    local res_cfg=$(get_positional 3 $job)

    local exec_dir="exec/$job_dir"
    export ARRAY_DIR="$exec_dir/array"
    mkdir -p $ARRAY_DIR
    globalize ARRAY_DIR

    # Jobs put their measured timings here.
    mkdir -p "$exec_dir/timings"

    local use_arrays=$(is_array_based "$exec_dir/job.sh")

    if [[ $RESET_TIME = true ]]; then
      rm -r "$exec_dir/timings"
    fi

    if [[ $(ls "$exec_dir/timings" | wc -w) > 0 ]]; then
      if [[ $use_arrays = true ]]; then
        # Since array tasks only do one measurement there is no possibility of performing a job partially.
        # Estimating the time limit too tightly would therefore cause slower jobs to fail without logging their higher time requirements,
        # increasing the likelyhood of failure on subsequent runs and creating a bias towards faster runs in the measurement results
        # by discarding slower ones during execution. This is probably not what someone analysing the distribution of performance metrics
        # would want.
        # The time limit is therefore estimated a bit more generously at a minute above the highest measured time.
        # Since these timings don't add up this should not inconvenience the scheduler too much either.
        time_estimate=$(($(estimate_time $exec_dir/timings 1.0) + 60))
      else
        # Iterative time is cumulative with faster job steps providing some buffer.
        # Since the worst case scenario here is that part of the steps have to be re-run,
        # time per run is estimated right between the average and maximum measured time.
        # This should still give the runner quite some slack.
        time_estimate=$(estimate_time $exec_dir/timings 0.5)
      fi
    else
      # Use user-provided initial estimate from config
      time_estimate=$(
        source "config/benchmarks/$benchmark/settings.sh"
        echo $TIME_ESTIMATE
      )
      # Convert Slurm time to seconds for calculations
      time_estimate=$(unslurmify_time $time_estimate)
    fi

    # Local runs print their output to the console in addition to the variable it's kept in for further processing.
    output_stream=/dev/null
    if [ $LOCAL_RUN = true ]; then
      output_stream=$(tty)
    fi

    # This makes the below pipes report the exit code of sbatch rather than tee.
    set -o pipefail
    task_count=$(ls $ARRAY_DIR | wc -l)
    # Skip taskless assignments
    if [[ $task_count = 0 ]]; then
      continue
    fi

    pushd "$exec_dir/scratch"
    if [[ $use_arrays = true ]]; then
      # Write the time estimate directly to the file because sbatch doesn't seem to support the parameter version
      local slurmtime=$(slurmify_time $time_estimate)
      sed -i "s/§time/$slurmtime/g" ../job.sh
      # The job file has indicated that it wants to use arrays so sbatch is invoked with a job array.
      batch_output=$(sbatch --dependency=singleton --array=0-$((task_count - 1)) ../job.sh | tee $output_stream)
    else
      # Write the time estimate directly to the file because sbatch doesn't seem to support the parameter version
      local slurmtime=$(slurmify_time $((time_estimate * task_count)))
      sed -i "s/§time/$slurmtime/g" ../job.sh

      # No job array was requested. The tasks will be executed as job steps.
      batch_output=$(sbatch --dependency=singleton ../job.sh | tee $output_stream)
    fi
    # Check if the job was successfully submitted
    if [ $? -ne 0 ]; then
      exit_failure "Job creation failed for $job_dir: $batch_output"
    fi
    set +o pipefail
    popd
    job_id=$(get_positional 4 $batch_output)
    # The next job has to wait for this one to finish in order to prevent cross-contamination of noise patterns.

    for task_id in $(ls "$ARRAY_DIR"); do
      # Get all necessary information from the job step config
      source "$ARRAY_DIR/$task_id"
      # Associate all parameters with a unique ID for tracking
      echo "$benchmark.$system.$res_cfg.$SCOREP_METRIC_PAPI.$noise_pattern.$PARAMSET_NAME ${job_id}_${task_id}" >>"$JOB_MAP_FILE"
    done
  done
  progress_clear
}

build_arrays() {
  print_info "Preparing jobs"

  source ../progress.sh
  progress 0

  # Remove residual files and directories from previous runs
  if [ -d exec ]; then
    for dir in $(ls exec); do
      rm -r exec/$dir/array
      rm exec/$dir/job.sh
    done
  fi

  local prg_total=$(cat "config/noise.cfg" | wc -l)
  local prg_current=0

  # Noise patterns form the outer hierarchy level so that a pattern can be run in parallel to several subsequent benchmark runs
  # and once those are done a new one can be started without having to restart NOIGENA all the time.
  # This causes benchmark runs to see different parts of the noise pattern, maximizing the measured noise, which is exactly what we want.
  while IFS= read -r noise_line; do
    progress $((prg_current * 100 / prg_total))
    prg_current=$((prg_current + 1))

    # Remove lines starting with '#'
    noise_line=${noise_line%%#*}
    if [ $(echo $noise_line | wc -w) = 0 ]; then
      continue
    fi

    noise_pattern=$(get_positional 1 $noise_line)
    # Number of iterations for this particular noise pattern
    noise_iterations=$(get_positional 2 $noise_line 1) # If there is only the noise pattern that trailing 1 will automatically become the iteration count.

    while IFS= read -r experiment; do
      # Remove lines starting with '#'
      experiment=${experiment%%#*}

      # Skip lines that are too short
      if [ $(echo $experiment | wc -w) -lt 6 ]; then
        if [ $(echo $experiment | wc -w) -ne 0 ]; then
          print_warning "Experiment is missing parameters: $experiment"
        fi
        continue
      fi

      # Extract the individual parameters from the experiment description
      local benchmark=$(get_positional 1 $experiment)
      local param_set=$(get_positional 2 $experiment)
      local system=$(get_positional 3 $experiment)
      local nodes=$(get_positional 4 $experiment)
      local processes=$(get_positional 5 $experiment)
      local threads=$(get_positional 6 $experiment)

      local res_cfg="n${nodes}p${processes}t${threads}"
      local result_dir="$(pwd)/result/$benchmark/$system/$res_cfg"

      local exec_dir=$(execution_directory $system $benchmark $res_cfg)
      local ARRAY_DIR="$exec_dir/array"

      # Create the job script and required directories if this is the first element of this array
      if [ ! -d $ARRAY_DIR ]; then
        mkdir -p "$ARRAY_DIR"
        job_from_template $system $benchmark $nodes $processes $threads
        mkdir -p $STATUS_DIR/out/$benchmark/${system}n${nodes}p${processes}t${threads}
        mkdir -p $STATUS_DIR/err/$benchmark/${system}n${nodes}p${processes}t${threads}
      fi

      for it in $(seq 1 $((N_ITERATIONS * noise_iterations))); do
        while IFS= read -r counters; do
          # Remove lines starting with '#'
          counters=${counters%%#*}
          if [ $(echo $counters | wc -w) = 0 ]; then
            continue
          fi

          experiment_parent="$result_dir/$counters/$noise_pattern.$param_set"
          mkdir -p "$experiment_parent"
          EXPERIMENT_DIRECTORY="$experiment_parent/measurement.r$it"

          # Seek the first missing result
          if [ -d "$EXPERIMENT_DIRECTORY" ]; then continue; fi

          local job_idx=$(ls $ARRAY_DIR | wc -l)

          local jobfile=$ARRAY_DIR/$job_idx

          local benchmark_params=$(awk "/^$param_set/ {print \$0}" config/benchmarks/$benchmark/params | cut -f 2- -d ' ')

          echo "#!/bin/bash" >"$jobfile"
          echo "export EXPERIMENT_DIRECTORY=\"$EXPERIMENT_DIRECTORY\"" >>"$jobfile"
          echo "export NOISE_PATTERN=$noise_pattern" >>"$jobfile"
          echo "export PARAMSET_NAME=$param_set" >>"$jobfile"
          echo "export BENCHMARK_PARAMS=\"$benchmark_params\"" >>"$jobfile"
          echo "export SCOREP_METRIC_PAPI=$counters" >>"$jobfile"

        done <"config/metrics.cfg"
      done
    done <"config/experiments.cfg"
  done <"config/noise.cfg"
  progress_clear
}

############################################### Argument Parsing ###############################################

# Default values for command-line arguments
N_ITERATIONS=1
# If this is enabled job scripts will not be executed in parallel.
LOCAL_RUN=false
# Maximum number of retries on job failure
export RETRY_LIMIT=0
# Whether to continue a previous run or start a new one
CONTINUE_PREV=false
# This flag causes the runner to remove previous time measurements and use the initial estimate
RESET_TIME=false

ARG_LIST=$(getopt -o hi:lsr:ct --long help,iterations:,local,serial,retry:,continue,reset-time -- $@)

if [ $? -ne 0 ]; then
  print_usage
  exit 1
fi

eval set -- "$ARG_LIST"
while [ : ]; do
  case "$1" in
  -h | --help)
    print_usage
    shift
    ;;
  -i | --iterations)
    N_ITERATIONS=$2
    shift 2
    ;;
  -l | --local)
    LOCAL_RUN=true
    shift
    ;;
  -r | --retry)
    export RETRY_LIMIT=$2
    shift 2
    ;;
  -c | --continue)
    export CONTINUE_PREV=true
    shift
    ;;
  -t | --reset-time)
    export RESET_TIME=true
    ;;
  --)
    break
    ;;
  esac
done

if [ -f experiment/config/force_local_run ]; then
  LOCAL_RUN=true
fi

if $LOCAL_RUN; then
  # Make sure the fake slurm commands are found first
  export PATH="$(pwd)/fake_slurm:$PATH"
fi
######################################### Check hardware counters accessible #########################################
if /usr/sbin/sysctl --version >/dev/null; then
  perf_paranoid_level=$(/usr/sbin/sysctl kernel.perf_event_paranoid --values)
  if [[ $perf_paranoid_level -gt 0 ]]; then
    print_warning "perf_event_paranoid=$perf_paranoid_level is too high for accessing hardware counters without root privileges. Please set it to 0."
  fi
fi
papi_avail -c | grep "PAPI_"
check_failure "Cannot access any hardware counters."

############################################### Experiment Preparation ###############################################

pushd experiment

mkdir -p status
export STATUS_DIR="$(pwd)/status"
mkdir -p "$STATUS_DIR"
JOB_MAP_FILE="$STATUS_DIR/job_map"

if [ $CONTINUE_PREV = false ]; then
  rm -rf "$STATUS_DIR/jobs"
  mkdir -p "$STATUS_DIR/jobs"
fi

############################################### Experiment Execution ###############################################

current_try=0
while [ $current_try -le $RETRY_LIMIT ]; do
  # When continuing a previous run, jump right to status tracking.
  if [ $CONTINUE_PREV = true ]; then
    CONTINUE_PREV=false
  else
    build_arrays
    run_arrays
  fi

  echo -e "Attempt $current_try\n"
  python ../job_status.py $(pwd)/status

  if [ $? = 0 ]; then
    print_success "All jobs have finished successfully."
    exit 0
  fi

  current_try=$(($current_try + 1))
done

print_error "All jobs have terminated but there are failed jobs."

popd
