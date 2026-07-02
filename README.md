<!-- # NORC -->
[![GitHub Release](https://img.shields.io/github/v/release/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC/releases)
[![GitHub Release Date](https://img.shields.io/github/release-date/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC/releases)
[![Last Commit](https://img.shields.io/github/last-commit/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC/commits/main)
[![Contributors](https://img.shields.io/github/contributors/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC/graphs/contributors)
[![Issues](https://img.shields.io/github/issues/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC/issues)
[![Code Size](https://img.shields.io/github/languages/code-size/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC)
[![Top Language](https://img.shields.io/github/languages/top/tuda-parallel/NORC)](https://github.com/tuda-parallel/NORC)
[![License][license.badge]](./LICENSE)
[![CI](https://github.com/tuda-parallel/NORC/actions/workflows/CI.yml/badge.svg?branch=development)](https://github.com/tuda-parallel/NORC/actions/workflows/CI.yml)

<br />
<div align="center">
  <h1 align="center">NORC</h1>
  <h3 align="center"> Noise Resilient Hardware Counters in HPC</h3>
  <p align="center">
    <a href="doc/approach.md"><strong>Explore the approach »</strong></a>
    <br />
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

Before any performance measurements can be taken the tool must be configured for the target system, this can be done interactively during installation or beforehand by adjusting the configuration files in the config folder.
To perform the interactive installation, navigate to `acquisition` and run the installation script [`install.sh`](acquisition/install):

```bash
cd acquisition
./install.sh
```

The installation script will ask questions to create a meaningful configuration for your system, if you want to adjust the configuration in detail perform the following steps:

1. Configure how to install dependencies (see [Build Settings](doc/build_settings.md))
2. Add a system configuration for the target system (see [Adding Systems](doc/adding_systems.md))
3. Configure the experiment (see [Creating Experiments](doc/creating_experiments.md))

To run the installation non interactively use `./install.sh -q`, if everything is configured correctly this will install Score-P, PAPI, all benchmarks, and NOIGENA. As this can take a long time, we advise to choose a generous time limit for interactive session if required by the system. The `install` script will also create an empty experiment in the `build` folder. Subsequent calls to `install` will only create an empty experiment and not build anything else unless necessary.

Once the installation has succeeded execute the [run script](acquisition/run.sh):

```bash
cd acquisition
./run.sh -i <N>
```

This will run all measurements in the experiment `N` times and open the job tracker. The `run` command can be terminated at this point as the job tracking is not essential to the measurements. Once all measurements have succeeded, go to `acquisition/build`, compress the `experiment` directory, and copy it back to the local machine for analysis.

### Setup for analyzing the results

For analyzing the results, we provide a Python package which can be simply installed using pip:

```bash
cd analysis
pip install .
```

### tldr;
```bash
git clone https://github.com/tuda-parallel/NORC.git
cd NORC
cd acquisition
./install.sh

# Once the interactive setup completes 
# install the analysis components
cd ../analysis
pip install .

# Run some experiments and examine them
cd ../acquisition
./run.sh -i <N>

# Finally launch the GUI and examine the results

```

## Analyzing the Results

Instructions for analyzing the results are provided [here](analysis/README.md).

## Contributing

We welcome contributions from everyone! Please see our general [CONTRIBUTING.md](CONTRIBUTING.md) for instructions on how to get started.

If you are a **student** (e.g., working on a thesis), please refer to our specialized [Student Contribution Guide](doc/students_contribute.md).

**Important:** All development should target the **`development`** branch.

## Contact

[![][parallel.badge_tarraf]][parallel_website_tarraf] [![][parallel.badge_geiss]][parallel_website_geiss]

- [Ahmad Tarraf][parallel_website_tarraf]
- [Alexander Geiß][parallel_website_geiss]
- [Lukas Fuchs](https://github.com/Lukas-Fuchs)

## License

![license][license.badge]

Distributed under the BSD 3-Clause License. See [LICENCE](./LICENSE) for more information.


## Citation

```
@inproceedings{10.1145/3731599.3767517,
  author = {Tarraf, Ahmad and Gei\ss{}, Alexander and Fuchs, Lukas and Wolf, Felix},
  title = {Fantastic Hardware Counters and How to Find Them: Automating the Detection of Noise-Resilient Performance Counters in HPC},
  year = {2025},
  isbn = {9798400718717},
  publisher = {Association for Computing Machinery},
  address = {New York, NY, USA},
  url = {https://doi.org/10.1145/3731599.3767517},
  doi = {10.1145/3731599.3767517},
  booktitle = {Proceedings of the SC '25 Workshops of the International Conference for High Performance Computing, Networking, Storage and Analysis},
  pages = {1587–1600},
  numpages = {14},
  keywords = {Hardware Counters, Noise, Performance Analysis, High-performance Computing, Parallel Programming},
  location = {{St}. {Louis}, {MO}, {USA}},
  series = {SC Workshops '25}
}

@inproceedings{10027495,
  author={Ritter, Marcus and Tarraf, Ahmad and Geiß, Alexander and Daoud, Nour and Mohr, Bernd and Wolf, Felix},
  booktitle={2022 IEEE/ACM Workshop on Programming and Performance Visualization Tools (ProTools)}, 
  title={Conquering Noise With Hardware Counters on HPC Systems}, 
  year={2022},
  pages={1-10},
  keywords={Visualization;Runtime;System performance;Systems architecture;Hardware;Behavioral sciences;Reliability;Hardware counters;performance analysis;noise;high-performance computing;parallel programming},
  location = {{Dallas}, {TX}, {USA}}
  doi={10.1109/ProTools56701.2022.00007}},
```

## Publications

1. Ahmad Tarraf, Alexander Geiß, Lukas C. Fuchs, Felix Wolf: Fantastic Hardware Counters and How to Find Them: Automating the Detection of Noise-Resilient Performance Counters in HPC. In Proc. of the Workshop on Programming and Performance Visualization Tools (ProTools), held in conjunction with the International Conference for High Performance Computing, Networking, Storage, and Analysis (SC25), St. Louis, MO, USA, pages 1587–1600, ACM, November 2025.
 
2. Marcus Ritter, Ahmad Tarraf, Alexander Geiß, Nour Daoud, Bernd Mohr, Felix Wolf: Conquering Noise With Hardware Counters on HPC Systems. In Proc. of the Workshop on Programming and Performance Visualization Tools (ProTools), held in conjunction with the International Conference for High Performance Computing, Networking, Storage, and Analysis (SC22), Dallas, TX, USA, pages 1–10, IEEE, 2022.



[license.badge]: https://img.shields.io/badge/License-BSD_3--Clause-blue.svg

[parallel_website_tarraf]: https://www.parallel.informatik.tu-darmstadt.de/laboratory/team/tarraf/tarraf.html

[parallel.badge_tarraf]: https://img.shields.io/badge/Parallel_Programming:-Ahmad_Tarraf-blue

[parallel_website_geiss]: https://www.parallel.informatik.tu-darmstadt.de/laboratory/team/geiss/geiss.html

[parallel.badge_geiss]: https://img.shields.io/badge/Parallel_Programming:-Alexander_Geiß-blue
