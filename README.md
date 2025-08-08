# Hardware Counter Noise Inquisitor (HCNI)
The Hardware Counter Noise Inquisitor automates the analysis of hardware counters' noise resilience as well as the performance measurements needed.

The analysis tools can be found in the `analysis` directory and include:
 - `analyze`: Calculates relative deviations from performance measurements
 - `plot`: Creates plots from relative deviation data
 - `rank`: Ranks metrics by their noise resilience
 - `analysis_ui`: GUI application for detailed analysis

The performance measurement tool can be found in `acquisition` and need to be configured and copied to the target system before taking measurements.

## Taking Performance Measurements

Before any performance measurements can be taken the tool must be configured for the target system:
  1. Configure how to install dependencies (see [Build Settings](doc/build_settings.md))
  2. Add a system configuration for the target system (see [Adding Systems](doc/adding_systems.md))
  3. Configure the experiment (see [Creating Experiments](doc/creating_experiments.md))

Now copy the `acquisition` folder to the target system, navigate to it, start an interactive Slurm session, and run `install`.

If everything is configured correctly this will install Score-P, PAPI, all benchmarks, and NOIGENA.Because this can take a long time it is advisable to choose a generous time limit for the interactive session. The `install` script will also create an empty experiment in the `build` folder. Subsequent calls to `install` will only create an empty experiment and not build anything else unless necessary.

Once the installation has succeeded run `run -i <N>`. This will run all measurements in the experiment `N` times and open the job tracker. The `run` command can be terminated at this point as the job tracking is not essential to the measurements.

Once all measurements have succeeded, go to `acquisition/build`, compress the `experiment` directory, and copy it back to the local machine for analysis.

## Analyzing Results

There are two types of analysis tools provided: Three CLI tools (`analyze`, `plot`, and `rank`) and one GUI tool (`analysis_ui`), all located in the `analysis` directory.

`analyze`, `plot` [[doc]](doc/plot.md), and `rank` [[doc]](doc/rank.md) accept an experiment directory as a parameter.
`plot` and `rank` require `analyze` to be run on the same experiment first.

`analysis_ui` is run without parameters and experiments can be loaded via the status bar by selecting the root directory of an experiment in the resulting dialog. The experiment will be automatically analyzed if it hasn't been yet.


