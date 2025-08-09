
#SBATCH --partition=§partition
#SBATCH --account=§budget
#SBATCH --job-name=NORC(§partition)
#SBATCH --output=§status_out/%A_%a.out
#SBATCH --error=§status_err/%A_%a.err
#SBATCH --nodes §nodes
#SBATCH --ntasks-per-node §total_tasks
#SBATCH --exclusive
#SBATCH --time §time
#SBATCH --mem 0  # We have exclusive access so use all memory available

#This line tells the runner that this is to be executed as a job array.
#RUNNER ARRAY

trap "killall -s 9 -u $(whoami) -v -w NOIGENA" EXIT

t_start=$(date +%s)

source "$ARRAY_DIR/$SLURM_ARRAY_TASK_ID"
STATUS_FILE=$STATUS_DIR/jobs/${SLURM_ARRAY_JOB_ID}_$SLURM_ARRAY_TASK_ID
touch $STATUS_FILE

if [ -f ./prologue.sh ]; then
  ./prologue.sh
fi

export SCOREP_EXPERIMENT_DIRECTORY=$EXPERIMENT_DIRECTORY.tmp
export OMP_PLACES="cores(§cpus)"
export OMP_DISPLAY_AFFINITY=TRUE
main_exit_code=1
if [ ! $NOISE_PATTERN = NO_NOISE ]; then
	# NOIGENA doesn't currently support threading so processes are used instead.
  OMP_NUM_THREADS=1 srun -n $((§noise_procs * §nodes)) --ntasks-per-node=§noise_procs --overlap --cpu-bind=verbose,map_cpu:§odd_cpus NOIGENA PATTERN_$NOISE_PATTERN &
  # Random delay for randomizing the part of the noise pattern affecting the benchmark.
  delay=$(awk -v seed=$RANDOM 'BEGIN {srand(seed); printf("%.3f\n", rand() * 10)}')s
  echo "Delaying execution for $delay."
  sleep $delay
fi

OMP_NUM_THREADS=§threads srun -n $((§procs * §nodes)) --ntasks-per-node=§procs --overlap --cpu-bind=verbose,mask_cpu:0x555555555555 "§benchmark" $BENCHMARK_PARAMS
export main_exit_code=$?
killall -u $(whoami) -s 9 -v -w NOIGENA 2> /dev/null


if [ -f ./epilogue.sh ]; then
  ./epilogue.sh
fi

if [ $main_exit_code = 0 ]; then
  # Retire the temporary experiment directory to the intended location
  mv $SCOREP_EXPERIMENT_DIRECTORY $EXPERIMENT_DIRECTORY
  # Log the elapsed time.
  t_end=$(date +%s)
  echo $((t_end - t_start)) > "../timings/${SLURM_ARRAY_JOB_ID}_$SLURM_ARRAY_TASK_ID"
fi

echo $main_exit_code > $STATUS_FILE

killall -s 9 -u $(whoami) -v -w NOIGENA

sleep 5s
exit 0