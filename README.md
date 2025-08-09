<!-- # FTIO -->
![GitHub Release](https://img.shields.io/github/v/release/tuda-parallel/NORC)
![GitHub Release Date](https://img.shields.io/github/release-date/tuda-parallel/NORC)
![](https://img.shields.io/github/last-commit/tuda-parallel/NORC)
![contributors](https://img.shields.io/github/contributors/tuda-parallel/NORC)
![issues](https://img.shields.io/github/issues/tuda-parallel/NORC)
![](https://img.shields.io/github/languages/code-size/tuda-parallel/NORC)
![](https://img.shields.io/github/languages/top/tuda-parallel/NORC)
![license][license.bedge]
<!-- [![CI](https://github.com/tuda-parallel/NORC/actions/workflows/CI.yml/badge.svg)](https://github.com/tuda-parallel/NORC/actions/workflows/CI.yml) -->
<!-- [![CD](https://github.com/tuda-parallel/NORC/actions/workflows/python-publish.yml/badge.svg)](https://github.com/tuda-parallel/NORC/actions/workflows/python-publish.yml) -->
<!-- [![pypi](https://img.shields.io/pypi/status/ftio-hpc)](https://pypi.org/project/ftio-hpc/) -->

<br />
<div align="center">
  <h1 align="center">NORC</h1>
  <p align="center">
 <h3 align="center"> Noise Resilient Hardware Counters in HPC</h2>
    <!-- <br /> -->
    <a href="https://github.com/tuda-parallel/FTIO/tree/main/docs/approach.md"><strong>Explore the approach »</strong></a>
    <br />
    <!-- <br /> -->
    <!-- <a href="#testing">View Demo</a> -->
    <!-- · -->
    <a href="https://github.com/tuda-parallel/NORC/issues">Report Bug</a>
    ·
    <a href="https://github.com/tuda-parallel/NORC/issues">Request Feature</a>
  </p>
</div>

<!-- #  -->

NORC is a tool that automates the analysis of hardware counters' noise resilience and performance measurements. This repository provides two main components:

1. The **data acquisition** component measures performance. You'll find the tool in the [`acquisition`](acquisition) directory. Before taking measurements, you need to configure it to your target system.
2. The **analysis component** allows inspecting the results from the data acquisition. The tools are located in the `analysis` directory. You can find more details in the [analysis README](analysis/README.md).



## Installation
The installation process is divided into two parts:

1. [Setup for the measurements'](#setup-for-data-acquisition): This involves configuring the environment and tools for taking performance measurements.
2. [Setup for results evaluation](#setup-for-analyzing-the-results): This covers the necessary steps to prepare the system for evaluating the collected data.

### Setup for Data Acquisition  
Before any performance measurements can be taken the tool must be configured for the target system:
  1. Configure how to install dependencies (see [Build Settings](doc/build_settings.md))
  2. Add a system configuration for the target system (see [Adding Systems](doc/adding_systems.md))
  3. Configure the experiment (see [Creating Experiments](doc/creating_experiments.md))

Afterwards, navigate to `acquisition` and run the instal script [`install.sh`](acquisition/install):
```bash
cd acquisition
./install.sh
```
If everything is configured correctly this will install Score-P, PAPI, all benchmarks, and NOIGENA. As this can take a long time, we advise to choose a generous time limit for interactive session if required by the system. The `install` script will also create an empty experiment in the `build` folder. Subsequent calls to `install` will only create an empty experiment and not build anything else unless necessary.

Once the installation has succeeded execute the [run script](acquisition/run.sh):
```bash
cd acquisition
run -i <N>
```
This will run all measurements in the experiment `N` times and open the job tracker. The `run` command can be terminated at this point as the job tracking is not essential to the measurements. Once all measurements have succeeded, go to `acquisition/build`, compress the `experiment` directory, and copy it back to the local machine for analysis.

### Setup for analyzing the results
For analyzing the results, we provide a python package which can be simply installed using pip:
```bash
cd analysis
pip install .
```

### tdlr;
```bash
git clone https://github.com/tuda-parallel/NORHC.git
cd NORHC
cd acquisition
./install.sh

# Once the interactive setups completes 
# install the analysis components
cd ../analysis
pip install .

# Run some experiments and examine them
cd ../acquisition
run -i <N>

# Finally launch the GUI and examine the results

```

## Analyzing the Results
Instructions on how to analyze the results are provided [here](analysis/README.md).



## Contributing

Kindly see the instructions provided under [docs/contributing.md](/docs/contributing.md).


## Contact

[![][parallel.bedge_tarraf]][parallel_website_tarraf] [![][parallel.bedge_geiss]][parallel_website_geiss]

- [Ahmad Tarraf][parallel_website_tarraf]
- [Alexander Geiß][parallel_website_geiss]
- [Lukas Fuchs](https://github.com/Lukas-Fuchs)


## License

![license][license.bedge]

Distributed under the BSD 3-Clause License. See [LICENCE](./LICENSE) for more information.




[license.bedge]: https://img.shields.io/badge/License-BSD_3--Clause-blue.svg
[parallel_website_tarraf]: https://www.parallel.informatik.tu-darmstadt.de/laboratory/team/tarraf/tarraf.html
[parallel.bedge_tarraf]: https://img.shields.io/badge/Parallel_Programming:-Ahmad_Tarraf-blue
[parallel_website_geiss]: https://www.parallel.informatik.tu-darmstadt.de/laboratory/team/geiss/geiss.html
[parallel.bedge_geiss]: https://img.shields.io/badge/Parallel_Programming:-Alexander_Geiß-blue