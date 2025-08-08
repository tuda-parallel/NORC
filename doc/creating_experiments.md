# Creating Experiments

An experiment is defined by a list of measurements, metrics, and noise patterns.

`acquisition/config/experiments.cfg` contains the list of measurements the runner will run.
Each line of the form `<benchmark> <param_set> <system> <nodes> <processes> <threads>` describes an experiment.
Empty lines and lines starting with `#` are ignored.

`<benchmark>` and `<param_set>` are explained [here](adding_benchmarks.md).
`<system>` is explained [here](adding_systems.md).

`<nodes>, <processes>, <threads>` describe the number of nodes, processes, and threads used respectively.
`<processes>` is the number of processes per node and `<threads>` is the number of threads per process.

Keep in mind that half of the cores will be used by NOIGENA, thus decreasing the sensible limit of process and thread count to half of what would normally be available. Node count is unaffected by this.

## Noise Patterns
Every measurement is run with a list of noise patterns configured in `acquisition/config/noise.cfg`.
Each line in this file has the form `<pattern> [n]`, where `[n]` is the number of measurements to be done with this noise pattern. Lines starting with `#` are ignored.

Before patterns can be used here, they must be configured in `acquisition/config/noigena_cfg.yaml` (for details see NOIGENA's documentation at `acquisition/noigena/USER_GUIDE`).
Next, NOIGENA must be rebuilt. This should happen automatically during installation if any relavant changes have occurred.

The noise pattern names in the configuration file should be the same as configured in `noigena_cfg.yaml` but without the "PATTERN_" prefix.
`NO_NOISE` is a special noise pattern that does not run NOIGENA and is required for comparisons between measurements with and without induced noise. It is recommended to perform several measurements with the `NO_NOISE` pattern, up to the total number of runs with other noise patterns.

See NOIGENA's user guide for information on noise pattern creation and configuration.

## Hardware Counter Sets
Every measurement is run for each set of hardware counters configured in `acquisition/config/metrics.cfg`.
Each non-empty line not starting with "#" is interpreted as a comma separated (no spaces!) list of hardware counter names, as used in SCOREP_METRICS_PAPI.