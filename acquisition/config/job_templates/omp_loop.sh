# Batch prefixes from system and benchmark go here.
#SBATCH --partition=§partition
#SBATCH --account=§budget
#SBATCH --job-name=HCNI(§partition)
#SBATCH --output=§status_out/%j.out
#SBATCH --error=§status_err/%j.err
#SBATCH --nodes §nodes
#SBATCH --ntasks-per-node §total_tasks
#SBATCH --exclusive
#SBATCH --time §time
#SBATCH --mem 0  # We have exclusive access so use all memory available

next_job_step=0
noigena_job_step=""

kill_noigena(){
  # If there is a job step associated to NOIGENA cancel it.
  if [ -n $noigena_job_step ]; then
    scancel "${SLURM_JOB_ID}.$noigena_job_step"
    noigena_job_step=""
    # Wait for any possible cancellation delays to pass.
    sleep 5s
  fi
}

trap "killall -s 9 -u $(whoami) -v -w NOIGENA 2> /dev/null" EXIT

current_noise_pattern=""
set_noise_pattern(){
  # Only restart NOIGENA if the pattern has changed.
  if [ ! "$1" = "$current_noise_pattern" ]; then
    current_noise_pattern=$1
    kill_noigena
    echo "Starting noise pattern $current_noise_pattern"
    if [ ! "$current_noise_pattern" = "NO_NOISE" ]; then
      # Run NOIGENA on odd cores
      OMP_NUM_THREADS=1 srun -n $((§noise_procs * §nodes)) --ntasks-per-node=§noise_procs --overlap --cpu-bind=verbose,map_cpu:§odd_cpus NOIGENA PATTERN_$current_noise_pattern &
      # Advance current job step and save NOIGENA's step for reference.
      noigena_job_step=$next_job_step
      next_job_step=$((next_job_step + 1))

      # Add a random delay so that repeated runs are less likely to hit the exact same noise spot as previous ones.
      local delay=$(awk -v seed=$RANDOM 'BEGIN {srand(seed); printf("%.3f\n", rand() * 10)}')s
      echo "Delaying execution for $delay."
      sleep $delay
    fi
  fi
}

# Iterate through all measurements for this job.
for array_id in $(ls -v $ARRAY_DIR); do
  t_start=$(date +%s)

  # Load measurement configuration and mark measurement as in-progress.
  source "$ARRAY_DIR/$array_id"
  STATUS_FILE=$STATUS_DIR/jobs/${SLURM_JOB_ID}_$array_id
  touch $STATUS_FILE
 
  if [ -f ./prologue.sh ]; then
    ./prologue.sh
  fi

  # Write results to a temporary directory first in case the measurement fails.
  export SCOREP_EXPERIMENT_DIRECTORY=$EXPERIMENT_DIRECTORY.tmp
  export OMP_PLACES="cores(§cpus)"
  export OMP_DISPLAY_AFFINITY=TRUE
  main_exit_code=1

  # Ensure noise pattern, run the benchmark on even cores, and update job step.
  set_noise_pattern $NOISE_PATTERN
  OMP_NUM_THREADS=§threads srun -n $((§procs * §nodes)) --ntasks-per-node=§procs --overlap --cpu-bind=verbose,mask_cpu:0x555555555555 "§benchmark" $BENCHMARK_PARAMS ;
  next_job_step=$((next_job_step + 1))
  export main_exit_code=$?

  if [ -f ./epilogue.sh ]; then
    ./epilogue.sh
  fi
  
  # Log final status.
  echo $main_exit_code > $STATUS_FILE

  if [ $main_exit_code = 0 ]; then
    # Retire the temporary experiment directory to the intended location.
    mv $SCOREP_EXPERIMENT_DIRECTORY $EXPERIMENT_DIRECTORY
    # Log the elapsed time.
    t_end=$(date +%s)
    echo $((t_end - t_start)) >> "../timings/${SLURM_JOB_ID}"
  fi
done

kill_noigena
exit 0