# Artifacts Reproducibility

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.14965920.svg)]()


Below, we describe how to reproduce the results from the Paper entitled:
"Fantastic Hardware Counters and How to Find Them:  Automating the Detection of Noise-Resilient Performance Counters in HPC"

Before you start, first set up [NORC](https://github.com/tuda-parallel/NORC?tab=readme-ov-file#installation). The experiments are divided into two parts:
- Experiments on the CM cluster
- Experiments on the Grace Hopper system


## Prerequisites 
Before you start, there are two prerequisites:
1. Install  [NORC](https://github.com/tuda-parallel/NORC?tab=readme-ov-file#installation)
2. Depending on what you want to test, you need to [download and extract](#extracting-the-data-set) the data set from [Zenodo]().



### Extracting the Data Set:
download the zip file from [here]() or using wget in a bash terminal:
```sh
wget https://zenodo.org/records/14965920/files/data.zip?download=1
```
Next, unzip the file
```sh
unzip data.zip
```
This extracts the needed traces and experiments:

```sh
data
├── ...
└── ...
```
