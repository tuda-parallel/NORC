# Artifacts Reproducibility

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.16786108.svg)]()


Below, we describe how to reproduce the results from the Paper entitled:
"Fantastic Hardware Counters and How to Find Them: Automating the Detection of Noise-Resilient Performance Counters in HPC"

Before you start, first set up [NORC](https://github.com/tuda-parallel/NORC?tab=readme-ov-file#installation). The experiments are divided into two parts:
- Experiments on the CM cluster
- Experiments on the Grace Hopper system


## Prerequisites 
Before you start, there are two prerequisites:
1. Install [NORC](https://github.com/tuda-parallel/NORC?tab=readme-ov-file#installation)
2. Depending on what you want to test, you need to [download and extract](#extracting-the-data-set) the data set from [Zenodo](https://doi.org/10.5281/zenodo.16786108).



### Extracting the Data Set:
download the zip file from [here](https://doi.org/10.5281/zenodo.16786108) or using wget in a bash terminal:
```sh
wget https://zenodo.org/api/records/16786109/files-archive
```
Next, unzip the file
```sh
unzip data.zip
```
This extracts the needed traces and experiments:

```sh
data
├── NORC_experiment_cm.zip
└── NORC_experiment_gracehopper.zip
```



## Artifact A1 – Noise-Resilient Hardware Counter Data (DEEP-EST CM)

This artifact contains **hardware counter data** collected on the **Cluster Module (CM)** of the DEEP-EST system during demonstration *C₃*, using configurations *C₁* (acquisition) and *C₂* (analysis) with [NORC](https://github.com/tuda-parallel/NORC).  
It demonstrates how NORC can identify **noise-resilient hardware counters**, providing:
- The **raw counter measurements**  
- The **ranking of counters by noise resilience**  
- Plots and tables generated from the analysis

### System & Dependencies
- **Hardware:** DEEP-EST CM, 50 nodes × 2× Intel Xeon Skylake Gold 6146 (12 cores, 24 threads), 192 GB DDR4, InfiniBand EDR
- **Software:** Score-P (≥8.0, PAPI support), PAPI, SIONlib, PyYAML, NumPy, NOIGENA, LAMMPS, LULESH, miniFE  
  (see NORC docs for exact versions & module setup)
- **Extra tools:** GCC 12.3, CMake 3.30, make, MPI (ParaStationMPI 5.9.2-1), Python 3.11, SLURM  
- **Analysis deps (Python):** numpy, matplotlib, pyside6, termcolor, pycubexr, tqdm

### Input Configurations
The acquisition requires:
1. **System configuration** – job submission settings
2. **Experiment configuration** – benchmark runs & parameters
3. **Noise patterns** – types and repetitions
4. **Hardware counter list** – selected counters only:  
   `STL_ICY`, `TOT_INS`, `DP_OPS`, `SR_INS`, `LD_INS`, `BR_INS`, `REF_CYC`

### Reproduction Steps
1. **Install & configure NORC** (acquisition + analysis components)  
   Use the interactive installer to select the CM environment and required counters.
2. **Run experiments** (`norc run`) on the CM to collect raw data (**~230 min** runtime).
3. **Copy results** to an analysis machine.
4. **Analyze data**  
   - **GUI:** open experiment folder in NORC analysis GUI → start pre-processing  
   - **CLI:** run `norc_analyze`
5. **Export results**  
   - Rankings: `norc_rank`  
   - Deviation plots: `norc_plot`

### Expected Outputs
- GUI view of results (Fig. 5 in the paper)  
- Counter ranking table (Table 4)  
- Ranked deviation plots (Fig. 6)


## Artifact A2 – Noise-Resilient Hardware Counter Data (Grace Hopper Node)

This artifact is similar to **Artifact A1**, but the data was collected on a **Grace Hopper–based node**.  
It demonstrates how NORC can identify **noise-resilient hardware counters**, providing:
- The **raw counter measurements**  
- The **ranking of counters by noise resilience**  
- Plots and tables generated from the analysis

### System & Dependencies
- **Hardware:** NVIDIA Grace Hopper Superchip  
  - 72× Neoverse V2 Armv9 cores  
  - 480 GB LPDDR5X RAM  
  - NVIDIA GH200 GPU (96 GB HBM3)
- **Software:** Same as in A1 — Score-P (≥8.0, PAPI support), PAPI, SIONlib, PyYAML, NumPy, NOIGENA, LAMMPS, LULESH, miniFE  
  (on this system, dependencies installed automatically via **Spack**)
- **Extra tools:** GCC 11.4.0, make, Python 3.11, SLURM (optional)  
- **Analysis deps (Python):** same as in A1 — numpy, matplotlib, pyside6, termcolor, pycubexr, tqdm

### Input Configurations
Same as in A1, except:
- Different **noise patterns**
- **All hardware counters** are selected

### Reproduction Steps
1. **Install & configure NORC** (acquisition + analysis components)  
   Use the interactive installer, selecting Grace Hopper environment settings.
2. **Installer settings:**  
   - Enable **Spack** usage  
   - Set Spack suffix: `%gcc@11.4.0`  
   - Parallel build jobs: `72`  
   - No SLURM detected → confirm  
   - System config: `local`  
   - Threads per rank: `9`  
   - Edit `experiments.cfg` to match resources  
   - Select **all hardware counters**
3. **Run experiments** (`norc run`) on the GH node to collect raw data (**~2200 min** runtime).
4. **Copy results** to an analysis machine.
5. **Analyze data**  
   - **GUI:** open experiment folder in NORC analysis GUI → start pre-processing  
   - **CLI:** run `norc_analyze`
6. **Export results**  
   - Rankings: `norc_rank` (Table 5 in paper)  
   - Deviation plots: `norc_plot` (Fig. 7 in paper)

### Expected Outputs
- Counter ranking table (Table 5)  
- Ranked deviation plots (Fig. 7)
