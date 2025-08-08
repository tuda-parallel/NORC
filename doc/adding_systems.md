# Adding Systems

System configurations are directories in `acquisition/config/systems` containing a configuration file (`system.sh`) and a batch prefix (`batch_prefix`).

The configuration file is a Bash file which exports the following fields:
  - `PARTITION`: Name of the target partition as used by Slurm
  - `BUDGET`: Name of the budget to run jobs under
  - `CORES_PER_NODE`: Number of cores available on the target nodes
  - `JOB_TEMPLATE`: What [job template](job_templates.md) to execute jobs with (when in doubt use `omp_loop`)

The batch prefix file (`batch_prefix`) contains `#SBATCH` directives that are prepended to the job files before they are submitted to Slurm. This file must only contain `#SBATCH` directives. Adding commands would cause Slurm to ignore the rest of the allocation options.