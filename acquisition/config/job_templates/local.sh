#SBATCH --job-name=hwc-noise-test(§benchmark)
#SBATCH --output=§status_out/%A.out
#SBATCH --error=§status_err/%A.err
#SBATCH --nodes §nodes
#SBATCH --ntasks-per-node §total_tasks
#SBATCH --exclusive
#SBATCH --time=§time
trap "killall -u $(whoami) -v -w NOIGENA 2> /dev/null" EXIT

current_noise_pattern="NO_NOISE"
set_noise_pattern(){
  # Only restart NOIGENA if the pattern has changed
  if [ ! "$1" = "$current_noise_pattern" ]; then
    current_noise_pattern=$1
    echo "Starting noise pattern $current_noise_pattern"
    killall -u $(whoami) -v -w NOIGENA 2> /dev/null
    if [ ! "$current_noise_pattern" = "NO_NOISE" ]; then
      # NOIGENA doesn't currently support threading so processes are used instead.
      OMP_NUM_THREADS=1 taskset -c §odd_cpus mpirun --bind-to core -n §noise_procs --oversubscribe NOIGENA PATTERN_$current_noise_pattern >> ~/noigena.log &

      # Add a random delay so that repeated runs are less likely to hit the exact same noise spot as previous ones.
      local delay=$(awk -v seed=$RANDOM 'BEGIN {srand(seed); printf("%.3f\n", rand() * 10)}')s
      echo "Delaying execution for $delay."
      sleep $delay
    fi
  fi
}

echo "NOISE CPU ASSIGNMENT"
taskset -c §odd_cpus mpirun --bind-to core -n §noise_procs --oversubscribe bash -c 'echo "Host: $(hostname), Task: $OMPI_COMM_WORLD_RANK, Cpus_allowed_list: $(grep Cpus_allowed_list /proc/self/status)"'

echo "BENCHMARK CPU ASSIGNMENT"
taskset -c §even_cpus mpirun --bind-to core -n §procs --oversubscribe bash -c 'echo "Host: $(hostname), Task: $OMPI_COMM_WORLD_RANK, Cpus_allowed_list: $(grep Cpus_allowed_list /proc/self/status)"'

for array_id in $(ls $ARRAY_DIR); do
  t_start=$(date +%s)

  source "$ARRAY_DIR/$array_id"
  STATUS_FILE=$STATUS_DIR/jobs/${SLURM_JOB_ID}_$array_id
  touch "$STATUS_FILE"

  echo "=== Start $EXPERIMENT_DIRECTORY ==="
  echo "=== Start $EXPERIMENT_DIRECTORY ===" >&2

  echo "§benchmark($PARAMSET_NAME) % $NOISE_PATTERN"
  echo "$SCOREP_METRIC_PAPI"

  if [ -f ./prologue.sh ]; then
    ./prologue.sh
  fi

  export SCOREP_EXPERIMENT_DIRECTORY=$EXPERIMENT_DIRECTORY.tmp
  export OMP_PLACES="cores(§cpus)"
  export OMP_DISPLAY_AFFINITY=TRUE
  main_exit_code=1

  set_noise_pattern $NOISE_PATTERN
  OMP_NUM_THREADS=§threads taskset -c §even_cpus mpirun --bind-to core -n §procs --oversubscribe "§benchmark" $BENCHMARK_PARAMS
  main_exit_code=$?
  export main_exit_code
  echo "exit code: $main_exit_code"
  echo "exit code: $main_exit_code" >&2

  if [ -f ./epilogue.sh ]; then
    ./epilogue.sh
  fi

  if [ "$main_exit_code" = "0" ]; then
    mv "$SCOREP_EXPERIMENT_DIRECTORY" "$EXPERIMENT_DIRECTORY"
  fi
  echo $main_exit_code > "$STATUS_FILE"

  t_end=$(date +%s)
  # Log the elapsed time. Since this is running sequentially there is no need for extra files for conflict avoidance.
  echo $((t_end - t_start)) >> "../timings/${SLURM_JOB_ID}"

done
exit 0