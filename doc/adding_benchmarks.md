# Adding Benchmarks

Every directory in acquisition/benchmarks that does not start with a period will be built during installation.
The name of the directory will be the name of the benchmark everywhere else (here referred to as `<benchmark>`).

Each of these directories must contain:
 - build.sh
   - Builds the benchmark and places its binary in the installation's bin directory
 - params
   - Contains named parameter sets used for experiment definition
 - settings.sh
   - Settings used during runtime (such as an initial time estimate for the respective benchmark)
 
They may also contain:
 - resources
   - Directory containing any resources the benchmark will need at runtime
   - The runner will ensure that all resources will always be visible from the directory the benchmark is running in
   - prologue.sh / epilogue.sh
     - Scripts run before / after each benchmark execution
     - Located in the resources directory
 - batch_prefix
   - Prepended to Slurm job files for additional #SBATCH directives
   - Do not put any commands in here since that would break the job files

## Creating a Build Script
The build script must be located at `acquisition/benchmarks/<benchmark>/build.sh` and executable.

It is automatically executed by the top-level installation after the tooling has been set up.

The script must configure and build the benchmark using a Score-P wrapped compiler (scorep-mpicc, scorep-mpicxx,...).

For the configuration step it is usually advisable to turn off Score-P instrumentation. It has to be turned back on for the build step.
([source \[PDF\]](https://perftools.pages.jsc.fz-juelich.de/cicd/scorep/tags/latest/pdf/scorep.pdf))

**Example (CMake):**  
`SCOREP_WRAPPER=off cmake . \`  
`-DCMAKE_C_COMPILER=scorep-mpicc \`  
`-DCMAKE_CXX_COMPILER=scorep-mpicxx`  
`make`

**Example (CMake):**  
`SCOREP_WRAPPER=off ./configure \`  
`CC=scorep-mpicc \`  
`CXX=scorep-mpicxx`  
`make`  

The `SCOREP_WRAPPER` is automatically turned back on for the make step unless the variable was exported (don't do that).

After the build has succeeded the resulting executable must be placed in `$INSTALL_DIR/bin`, which is automatically added to the runtime `$PATH` variable.
The executable's name must be identical to the folder name (`<benchmark>`). 

## Creating a Parameter File
Benchmarks can automatically be run with different parameters.  
These parameter sets are configured in `acquisition/benchmarks/<benchmark>/params`.

Each line in this file represents a named set of parameters.
It starts with the set's name `<param_set>`, followed by the parameters for the benchmark like when executing it on the command line:  
`<param_set> <p1> <p2> <...>`.

Path parameters should be relative to `acquisition/benchmarks/<benchmark>/resources`.

## Benchmark Settings
`acquisition/benchmarks/<name>/settings.sh` is a Bash script exporting the following variables:
 - `TIME_ESTIMATE`: The initial time estimate per run for this benchmark. Time must be in a format recognizable by Slurm (see [here](https://slurm.schedmd.com/sbatch.html)).

## Adding Resources
Resources like config or input files can be placed in `acquisition/benchmarks/<name>/resources` and will automatically be copied to the benchmark's execution directory.

Please note that these resources will be used by all runs of the experiment and should therefore be treated as read-only.
Copies of resources can be created / deleted using prologue/epilogue.sh if mutable resources are needed.