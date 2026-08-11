# NORC Experiment Folder Structure

This document describes the directory layout and file organization for NORC experiments.

## Overview

A NORC experiment directory contains measurement data from running benchmarks under various noise conditions and hardware counter configurations. The structure evolves through three stages:

1. **Raw measurements** – Score-P profiles from benchmark runs
2. **Analysis results** – Extracted deviations and scoring data
3. **Generated measurement scripts** – Custom orchestration scripts for arbitrary programs

---

## Input Experiment Structure

This is the structure created by the **acquisition pipeline** (`/acquisition` in the NORC repository).

```
experiment_root/
├── result/
│   ├── <benchmark>/
│   │   ├── <system>/
│   │   │   ├── <res_cfg>/
│   │   │   │   ├── <counter_group>/
│   │   │   │   │   ├── <noise_pattern>.<param_set>/
│   │   │   │   │   │   ├── measurement.r1/
│   │   │   │   │   │   │   ├── profile.cubex
│   │   │   │   │   │   │   ├── metadata.json
│   │   │   │   │   │   │   └── ...
│   │   │   │   │   │   ├── measurement.r2/
│   │   │   │   │   │   └── ...
│   │   │   │   │   └── ...
│   │   │   │   └── ...
│   │   │   └── ...
│   │   └── ...
│   └── ...
│
├── config/
│   ├── experiments.cfg
│   ├── noise.cfg
│   ├── metrics.cfg
│   ├── noigena_cfg.yaml
│   ├── job_templates/
│   │   ├── omp_array.sh
│   │   └── omp_loop.sh
│   ├── systems/
│   │   ├── <system_name>/
│   │   │   ├── system.sh
│   │   │   └── batch_prefix
│   │   └── ...
│   └── benchmarks/
│       ├── <benchmark_name>/
│       │   ├── params
│       │   ├── batch_prefix
│       │   └── settings.sh
│       └── ...
│
└── status/
    ├── job_map
    └── jobs/
        ├── <job_id>_<task_id>
        └── ...
```

### Key Components

#### `result/` – Raw Measurement Data

Hierarchical organization by:
- **benchmark**: Name of the benchmark (e.g., `minife`, `lammps`, `lulesh`)
- **system**: System/cluster identifier (e.g., `dp-cn`, `dp-esb`)
- **res_cfg**: Resource configuration (e.g., `omp` for OpenMP, `mpi` for MPI)
- **counter_group**: PAPI counter set (e.g., `PAPI_TOT_INS,PAPI_BR_INS`)
- **noise_pattern**: Noise applied (e.g., `NO_NOISE`, `M2S2`, `N2S2`, `M2N2S2`)
- **param_set**: Parameter set name (e.g., `x20y20z20`, `s10r1`)
- **measurement.rN**: Individual repetition directory
  - `profile.cubex`: Score-P profile (binary format)
  - Metadata and timing files

**Naming convention:**
```
<noise_pattern>.<param_set>/measurement.r<repetition>/
```

#### `config/` – Experiment Configuration

- **experiments.cfg**: List of benchmarks and their parameter sets
  ```
  benchmark param_set system nodes procs threads
  minife    x20y20z20  dp-cn 1     1     2
  ```

- **noise.cfg**: Noise patterns to apply during measurement
  ```
  M2S2
  N2S2
  M2N2S2
  NO_NOISE 2
  ```

- **metrics.cfg**: PAPI counter groups (one group per line, comma-separated)
  ```
  PAPI_DP_OPS
  PAPI_BR_INS,PAPI_LD_INS,PAPI_SR_INS
  ```

- **systems/, benchmarks/**: System and benchmark-specific configuration

#### `status/` – Job Tracking

- **job_map**: Maps task descriptions to Slurm job IDs
- **jobs/**: Individual task status files (created/updated by job scripts)

---

## Modeling-Quality (MQM) Results Structure

`modeling_quality/submit_calibration_job.sh` (a.k.a. `run_mq_analysis`) stores
its PolyBench calibration runs under the experiment by default:

```
experiment_root/
├── result/, config/, status/    # (as above)
│
└── modeling_quality/
    └── polybench.<system>.<timestamp>/
        ├── job.sh
        ├── papi_counters.list
        ├── build/
        └── results/
            ├── results.jsonl, results.json, results_extrap.json
            ├── metric_ranking_by_deviation.json
            ├── selected_counters.json          # {"rule_based": {...}, "clustered": {...}}
            └── deviations.csv, deviation_heatmap.pdf, metric_clustering.pdf, ...
```

Pass `--local` to store this under `modeling_quality/exec/` (next to the
scripts) instead of inside the experiment.

## Analysis Results Structure

After running `norc_analyze`, the experiment gains a `.deviations/` subdirectory:

```
experiment_root/
├── result/
│   ├── <benchmark>/
│   │   └── ... (as above)
│   │
│   └── .deviations/
│       ├── <benchmark>.<params>.<noise_pattern>.<system>.<res_cfg>.<counter>.pickle
│       ├── <benchmark>.<params>.<noise_pattern>.<system>.<res_cfg>.<counter>.pickle
│       └── ...
│
└── ...
```

### Deviation Files

**Filename convention:**
```
{benchmark}.{params}.{noise_pattern}.{system}.{res_cfg}.{counter}.pickle
```

**Example:**
```
minife.x20y20z20.NO_NOISE.dp-cn.omp.PAPI_TOT_INS.pickle
minife.x20y20z20.M2S2.dp-cn.omp.PAPI_TOT_INS.pickle
```

**File format:** Python pickle containing a list of callpath data:
```python
[
  callpath_1: {
    name: str,
    visits: int,
    contribution: float,        # % of total execution time
    deviations: np.array        # relative deviation % per repetition
  },
  callpath_2: {...},
  ...
]
```

### Scoring Results

After `norc_rank` or opening the GUI, score data is cached (implementation-dependent, typically in-memory or temporary files).

---

## Generated Measurement Script Structure

When using `norc_generate`, the output script creates a measurement-specific directory layout:

```
<output_dir>/
├── measure.sh                 # Generated orchestration script
├── temp_templates/            # Temporary script copies
│   ├── template_1_iter1.sh
│   ├── template_1_iter2.sh
│   └── ...
│
├── logs/                       # Sbatch/mpirun output
│   ├── <job_id>.out
│   └── <job_id>.err
│
└── result/                     # Measurement results
    ├── <prefix>.<params>.r1/   # Extra-P naming convention
    │   ├── profile.cubex
    │   ├── metadata.json
    │   └── ...
    ├── <prefix>.<params>.r2/
    └── ...
```

### Result Directory Naming

**Extra-P Convention:**
```
NAME = [PREFIX "."] PARAMETER-VALUE-PAIRS [".r" REPETITION-NUMBER]
PARAMETER-VALUE-PAIRS = PARAM-NAME PARAM-VALUE *("." PARAM-NAME PARAM-VALUE)
```

**Examples** (with `--prefix myapp --var n=1,2 --var t=2,4 --iterations 2`):
```
result/
├── myapp.n=1.t=2.r1/    # Counter 1, iteration 1
├── myapp.n=1.t=2.r2/    # Counter 1, iteration 2
├── myapp.n=1.t=2.r3/    # Counter 2, iteration 1
├── myapp.n=1.t=2.r4/    # Counter 2, iteration 2
├── myapp.n=2.t=2.r1/    # Counter 1, iteration 1
└── ...
```

Each directory contains a Score-P `profile.cubex` file that can be analyzed with `norc_analyze`.

---

## File Format Details

### Profile Files (profile.cubex)

Binary format produced by Score-P. Contains:
- Call graph with timing information
- Hardware counter measurements (from PAPI)
- Per-thread statistics
- Metadata

Can be read with:
```python
import pycubexr
with pycubexr.CubexParser(cubex_path) as parser:
    # Access metrics, callpaths, regions
```

### Pickle Files (.pickle)

Python serialized objects containing measurement statistics. Structure:
```python
List[
  {
    'name': str,                  # Function/callpath name
    'visits': int,                # Call count
    'contribution': float,        # % of total time
    'deviations': np.ndarray      # Relative deviations [%]
  },
  ...
]
```

---

## Workflow Example

### Step 1: Acquisition (Creates raw measurements)
```bash
cd acquisition
./run.sh -i 3 --local  # 3 iterations, local execution
# Creates: experiment/result/<benchmark>/<system>/<res_cfg>/<counters>/<noise>.<params>/measurement.rN/
```

### Step 2: Analysis (Extracts deviations)
```bash
cd analysis
norc_analyze ../experiment
# Creates: experiment/result/.deviations/*.pickle
```

### Step 3: Scoring (Ranks counters)
```bash
norc_rank ../experiment --top 2
# Output: Top 2 counters by resilience
```

### Step 4: Analysis of Generated Results
```bash
# Copy generated results to a new experiment directory
cp -r measure_results/ ../experiment_custom/result/
# Optionally add .deviations/ structure for analysis

norc_analyze ../experiment_custom
norc_rank ../experiment_custom
```

### Step 5: HW-Counter-based Measurements as Basis for Performance Modeling (Using norc_generate)
```bash
norc_generate ../experiment my_template.sh \
  --var n=1,2,4 \
  --var threads=2,4 \
  --top 2 \
  --prefix myapp \
  -o measure.sh

bash measure.sh  # Or: sbatch measure.sh
# Creates: result/<prefix>.<params>.r<N>/profile.cubex for each counter+param+iteration
```

## See Also

- [Analysis Tools Documentation](./rank.md)
- [Plotting Documentation](./plot.md)