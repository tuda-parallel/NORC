# Job Templates

Job templates define how exactly jobs are to be executed.

Structurally, they are bash scripts with named placeholders that are filled in at runtime and turned into job scripts.

One job script can either execute a single measurement or all measurements that can be assumed to fit its job allocation, depending on the type of job template.

Templates are defined in `acquisition/config/job_templates`. To use a template, set it as the job template setting in the settings for some [system](adding_systems) (without the `.sh` suffix).

## Predefined Templates
Because job templates are quite complicated to write there are a few predefined ones that users are encouraged to try first:
 - `omp_loop`: Runs measurements [sequentially](#sequential-execution) using MPI via `srun` and OpenMP
 - `omp_array`: Runs measurements as a [job array](#sequential-execution) using MPI via `srun` and OpenMP
 - `mpi_omp_local`: Runs measurements using MPI via `mpirun` and OpenMP; Typically used for tests on a user's local machine

`omp_loop` is recommended for its smaller allocation footprint and better environment consistency between measurements.

If none of the predefined templates fit your needs, read on.


## Placeholders
Placeholders are parameters that are valid throughout the whole job and that are substituted for their values before the job is submitted.

Unlike variables, placeholders can be used in `#SBATCH` directives.

Placeholders are prefixed by `§`, analogous to shell variables. 

The following placeholders are currently available:
 - `§benchmark`: Name of the benchmark's executable
 - `§status_out`: Absolute path to the standard output status directory
 - `§status_err`: Absolute path to the error status directory
 - `§nodes`: The number of nodes
 - `§procs`: The number of benchmark processes per node
 - `§noise_procs`: The number of NOIGENA processes per node
 - `§total_tasks`: Sum of `§procs` and `§noise_procs`; Mostly used for #SBATCH directives where that math could not be performed.
 - `§threads`: The number of threads per process
 - `§cpus`: Available cores per node
 - `§odd_cpus`: Comma separated list of odd cores
 - `§even_cpus`: Comma separated list of even cores
 - `§partition`: Name of the target partition
 - `§budget`: Name of the budget used by the job
 - `§time`: The job allocation's time budget

## Runner hints
Runner hints tell the runner how to call the job script.
They consist of the prefix `#RUNNER` followed by the hint.

The following hints are currently available:
 - ARRAY: Set job execution to [array mode](#array-execution)
   - Otherwise the job is executed [sequentially](#sequential-execution)


## Execution Modes
There are currently two execution modes that define how each job is run and how much it does:

### Sequential Execution
This mode tells the runner to execute the job script as a regular Slurm job that is assumed to perform a provided list of measurements as separate job steps.

### Array Execution
This mode tells the runner to execute the job script as a Slurm job array, wherein each task performs a single measurement.

## Environment Variables
Various environment variables are provided for the job as a whole by the runner and for individual tasks by their respective definitions.

### Job Variables
 - `$ARRAY_DIR`: Directory containing all tasks to be performed by this job/array
 - `$STATUS_DIR`: Status directory, mainly for tracking the task's execution status and exit code

### Task Variables
 - `$EXPERIMENT_DIRECTORY`: Target Directory for performance measurements
 - `$NOISE_PATTERN`: Name of the noise pattern to be run by NOIGENA (without the "PATTERN_" prefix)
 - `$PARAMSET_NAME`: Name of the parameter set as defined in the benchmark's `params` file
 - `$BENCHMARK_PARAMS`: The benchmark's parameter list
 - `$SCOREP_METRIC_PAPI`: The hardware counters to be recorded by PAPI; Typically handled automatically by the instrumented application.