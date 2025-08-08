# Ranking Tool

`analysis/rank` creates a resilience-based metric ranking from an experiment. The root directory of and experiment is passed as a positional argument and the following options are available:

| Short | Long            | Accepted Values  | Description                        |
|-------|-----------------|------------------|------------------------------------|
|-c     | --contribution  | float            | Minimum contribution per call path |
|-v     | --visits        | int              | Minimum visits per call path       |
|-d     | --deviation     | float            | Deviation threshold for rating [%] |
|-s     | --susceptibility| float            | Susceptibility threshold for rating|

The thresholds denote the tipping point between what is considered a good or bad metric.

All dimensions are grouped for the ranking so that only the metric dimension remains.

Before this tool can be used `analysis/analyze` has to be called on the experiment root directory once.