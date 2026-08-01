#SBATCH --job-name=hwc-noise-test(§benchmark)
#SBATCH --output=§status_out/%A.out
#SBATCH --error=§status_err/%A.err
#SBATCH --nodes §nodes
#SBATCH --ntasks-per-node §total_tasks
#SBATCH --exclusive
#SBATCH --time=§time
trap "killall -u $(whoami) -v -w NOIGENA 2> /dev/null" EXIT

current_noise_pattern="NO_NOISE"

generate_rankfile() {
# generate_rankfile <stride> <n_ranks> <cores_per_rank> <offset> [outfile]
# Example: generate_rankfile 2 4 1 1 rankfile.txt
#   -> every 2nd core, starting at offset 1 -> cores 1,3,5,7
#
# Example: generate_rankfile 1 2 12 24 rankfile.txt
#   -> contiguous, 12 per rank, starting at core 24 -> ranks get 24-35, 36-47
#      (e.g. to pin onto the 2nd socket instead of the 1st)

    local stride="$1"
    local n_ranks="$2"
    local cores_per_rank="$3"
    local offset="${4:-0}"
    local outfile="${5:-rankfile.txt}"

    # trim whitespace from each line with awk/xargs to avoid padding artifacts
    mapfile -t all_cores < <(lscpu -e=CPU --online | tail -n +2 | tr -d ' ' | sort -n)

    if [[ ${#all_cores[@]} -eq 0 ]]; then
        echo "Error: could not determine core list from lscpu" >&2
        return 1
    fi

    if (( offset >= ${#all_cores[@]} )); then
        echo "Error: offset=$offset is beyond available cores (0..$((${#all_cores[@]}-1)))" >&2
        return 1
    fi

    # Apply offset first, then stride, over the remaining cores
    local pool=()
    for ((i=offset; i<${#all_cores[@]}; i+=stride)); do
        pool+=("${all_cores[$i]}")
    done

    local needed=$(( n_ranks * cores_per_rank ))
    if (( needed > ${#pool[@]} )); then
        echo "Error: need $needed cores (n_ranks=$n_ranks * cores_per_rank=$cores_per_rank)," \
             "but only ${#pool[@]} available after offset=$offset, stride=$stride" >&2
        return 1
    fi

    : > "$outfile"
    local idx=0
    for ((r=0; r<n_ranks; r++)); do
        local slots=()
        for ((c=0; c<cores_per_rank; c++)); do
            slots+=("${pool[$idx]}")
            ((idx++))
        done
        local slot_str
        slot_str=$(IFS=,; echo "${slots[*]}")
        echo "rank $r=localhost slot=${slot_str}" >> "$outfile"
    done

    #echo "Wrote $outfile:"
    #cat "$outfile"
}

set_noise_pattern(){
  # Only restart NOIGENA if the pattern has changed
  if [ ! "$1" = "$current_noise_pattern" ]; then
    current_noise_pattern=$1
    echo "Starting noise pattern $current_noise_pattern"
    killall -u $(whoami) -v -w NOIGENA 2> /dev/null
    if [ ! "$current_noise_pattern" = "NO_NOISE" ]; then
      # NOIGENA doesn't currently support threading so processes are used instead.
      generate_rankfile 2 §noise_procs 1 1 rankfile_noigena.txt
      mpirun --map-by rankfile:file=rankfile_noigena.txt -n §noise_procs NOIGENA PATTERN_$current_noise_pattern >> ~/noigena.log &

      # Add a random delay so that repeated runs are less likely to hit the exact same noise spot as previous ones.
      local delay=$(awk -v seed=$RANDOM 'BEGIN {srand(seed); printf("%.3f\n", rand() * 10)}')s
      echo "Delaying execution for $delay."
      sleep $delay
    fi
  fi
}


generate_rankfile 2 §noise_procs 1 1 rankfile_noigena.txt
echo "NOISE CPU ASSIGNMENT"
mpirun --map-by rankfile:file=rankfile_noigena.txt -n §noise_procs bash -c 'echo "Host: $(hostname), Task: $OMPI_COMM_WORLD_RANK, Cpus_allowed_list: $(grep Cpus_allowed_list /proc/self/status)"'


generate_rankfile 2 §procs §threads 0 rankfile_benchmark.txt
echo "BENCHMARK CPU ASSIGNMENT"
mpirun --map-by rankfile:file=rankfile_benchmark.txt -n §procs bash -c 'echo "Host: $(hostname), Task: $OMPI_COMM_WORLD_RANK, Cpus_allowed_list: $(grep Cpus_allowed_list /proc/self/status)"'

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
  generate_rankfile 2 §procs §threads 0 rankfile_benchmark.txt
  OMP_NUM_THREADS=§threads mpirun --map-by rankfile:file=rankfile_benchmark.txt -n §procs  "§benchmark" $BENCHMARK_PARAMS
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