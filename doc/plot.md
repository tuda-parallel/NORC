# Plotting Tool

`analysis/plot` creates plots for each metric, benchmark, system, noise pattern, parameter set, and system resource configuration. These are a lot of dimensions but they can be reduced by grouping them. The result is both exported into SVGs and shown in a Matplotlib window, which is often overcrowded on most consumer-grade monitors due to the potentially high number of plots needed.  The root directory of and experiment is passed as a positional argument and the following options are available:
  
| Short | Long                    | Accepted Values  | Description                                                       |
|-------|-------------------------|------------------|-------------------------------------------------------------------|
|-m     | --mode                  | {sum, max}       | Plotting mode                                                     |
|-c     | --contribution          | float            | Minimum contribution per call path                                |
|-v     | --visits                | int              | Minimum visits per call path                                      |
|-b     | --bands                 | int              | Number of color bands                                             |
|-g     | --groupings             | groupings        | List of dimension groupings                                       |
|N/A    | --benchmark             | names            | List of benchmarks to plot                                        |
|N/A    | --system                | names            | List of systems to plot                                           |
|N/A    | --noise                 | names            | List of noise patterns to plot                                    |
|N/A    | --counter               | names            | List of metrics to plot                                           |
|N/A    | --deviation_cutoff      | int              | Maximum deviation to display (Warning: May hide data.)            |
|N/A    | --height                | float            | Factor applied to the height of individual plots                  |
|N/A    | --fontsize              | int              | Font size for axis labels, etc.                                   |


## Filters and Groupings

Filters are comma-separated lists of items within their respective category. If specified, only the items in the list will be considered for plots. e.g., `--counter time,PAPI_TOT_INS` would only create plots for these two metrics.

Groupings are comma-separated lists of categories that are to be combined into their parent category. For example, measurements from several benchmarks can be combined into a single ALL_BENCHMARKS category. Valid categories are:

| Category | Parent Category |
|----------|-----------------|
|benchmark | ALL_BENCHMARKS  |
|system    | ALL_SYSTEMS     |
|noise     | ALL_NOISE       |
|parameters| benchmark       |
|resources | system          |

A special `all` grouping exists that groups everything.

The starting letters (b,s,n,p,r,a) are sufficient for grouping lists. Parameters andresources are grouped by default because this level of detail is rarely needed.

Before this tool can be used `analysis/analyze` has to be called on the experiment root directory once.