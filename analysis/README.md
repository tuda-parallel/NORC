# NORC Analysis Components

**NORC** is a Python toolkit for measuring and analyzing the **noise resilience** of hardware counters in High-Performance Computing (HPC) systems.  
It provides both command-line utilities and a GUI for automated performance measurements, statistical analysis, visualization, and ranking of metrics.

---

## Analyzing Results

NORC offers two types of analysis tools:
- **CLI Tools** – `norc_analyze`, [`norc_plot`](doc/plot.md), and [`norc_rank`](doc/rank.md)  
- **GUI Tool** – `norc_gui`

### NORC CLI
All CLI tools accept an **experiment directory** as input.  
`norc_plot` and `norc_rank` must be run **after** `norc_analyze` has processed the experiment.

Example workflow:
```bash
norc_analyze /path/to/experiment     # Perform analysis
norc_plot /path/to/experiment        # Generate plots
norc_rank /path/to/experiment        # Rank metrics
```
### NORC GUI
The GUI (`norc_gui`) requires no parameters.
After launch:
1. Use the status bar to select the root directory of an experiment.
2. If the experiment has not been analyzed, NORC will process it automatically.

## tdlr;
After installation, the following commands are available
```bash
pip install .
norhc_gui # Launches the GUI
norhc_analyze /path/to/experiment     # Analyze results
norhc_plot /path/to/experiment        # Generate plots (requires analyze)
norhc_rank /path/to/experiment        # Rank metrics (requires analyze)
```


