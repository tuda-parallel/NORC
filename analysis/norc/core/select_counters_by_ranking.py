#!/usr/bin/env python3
# This file is part of the NORC software
#
# Copyright (c) 2024-2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

"""Select hardware counters based on measured redundancy and ranking from
compare_to_ground_truth.py (mean absolute lead-exponent deviation).

Uses the metric ranking from a JSON file produced by compare_to_ground_truth.py
to prioritize counters: those with lower mean absolute deviation are preferred
when selecting which redundant counters to keep.
"""

import argparse
import json
import os
import sys

from norc.core.redundancy import (
    find_all_pairs_cached,
    select_counters,
    print_redundant_pairs,
    find_correlation_knee,
    plot_correlation_knee,
    filter_out_cache_counters,
    is_cache_counter,
    filter_pairs_by_counters,
)
from norc.core.score import find_cutoff
from norc.helpers.util import open_experiment_source, iterate_measurements


def load_ranking(ranking_file):
    """Load metric ranking from JSON file produced by compare_to_ground_truth.py.
    Returns a list of (metric, mean_abs_deviation) tuples sorted from best to worst.
    """
    with open(ranking_file) as f:
        ranking_data = json.load(f)
    return [(entry["metric"], entry["mean_abs_deviation"]) for entry in ranking_data]


def find_deviation_knee(ranked_with_deviations):
    """Detect the knee in deviation scores using the max-distance-to-chord method.

    Args:
        ranked_with_deviations: list of (metric, mean_abs_deviation) tuples

    Returns:
        (knee_index, knee_metric, knee_deviation) tuple
    """
    if not ranked_with_deviations:
        return None, None, None

    deviations = [d for _, d in ranked_with_deviations]
    if len(deviations) < 3:
        return len(deviations) - 1, ranked_with_deviations[-1][0], deviations[-1]

    knee_idx = find_cutoff(deviations)
    knee_metric, knee_deviation = ranked_with_deviations[knee_idx]
    return knee_idx, knee_metric, knee_deviation


def main():
    parser = argparse.ArgumentParser(
        description="Select hardware counters based on redundancy and quality ranking from "
        "compare_to_ground_truth.py (mean absolute lead-exponent deviation)."
    )
    parser.add_argument("experiment_root", help="Root of the NORC experiment")
    parser.add_argument(
        "-r",
        "--ranking-file",
        required=True,
        help="Path to metric_ranking_by_deviation.json from compare_to_ground_truth.py",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=None,
        help="Minimum |Pearson correlation| to flag a counter pair as redundant (default: auto-detect knee)",
    )
    parser.add_argument(
        "--no-auto-threshold",
        action="store_true",
        help="Disable auto-threshold detection and use a fixed threshold instead (requires -t/--threshold)",
    )
    parser.add_argument(
        "-c",
        "--contribution",
        type=float,
        default=1,
        help="Contribution threshold used when collecting correlations (default: 1)",
    )
    parser.add_argument(
        "-v",
        "--visits",
        type=int,
        default=100,
        help="Visit threshold used when collecting correlations (default: 100)",
    )
    parser.add_argument(
        "-m",
        "--min-resilience",
        type=float,
        default=None,
        help="Also include counters with rel_resilience >= this value (default: none)",
    )
    parser.add_argument(
        "--all-counters",
        action="store_true",
        help="Consider all measured counters instead of those above the resilience cutoff",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't read/write cached correlations; always reparse",
    )
    parser.add_argument(
        "--plot-knee",
        action="store_true",
        help="Generate a debug plot of correlations and knee detection",
    )
    parser.add_argument(
        "--exclude-cache",
        action="store_true",
        help="Exclude cache hit/miss counters from redundancy analysis",
    )
    args = parser.parse_args()

    # Load the ranking by deviation quality
    if not os.path.exists(args.ranking_file):
        print(f"Error: ranking file not found: {args.ranking_file}", file=sys.stderr)
        return 1

    ranked_with_dev = load_ranking(args.ranking_file)
    ranked = [m for m, _ in ranked_with_dev]
    print(f"Loaded ranking of {len(ranked)} metrics from {args.ranking_file}")
    print(f"Metrics ranked best to worst: {ranked[:5]}" + ("..." if len(ranked) > 5 else ""))

    # Find knee in deviation ranking
    knee_idx, knee_metric, knee_dev = find_deviation_knee(ranked_with_dev)
    if knee_idx is not None:
        print(f"\nDeviation ranking cutoff (knee):")
        print(f"  Index: {knee_idx} (of {len(ranked)})")
        print(f"  Metric: {knee_metric}")
        print(f"  Mean absolute deviation: {knee_dev:.4f}")

    # Compute redundancy pairs for all measured counters
    with open_experiment_source(args.experiment_root, read_only=args.no_cache) as tree:
        result_dir = os.path.join(tree.root, "result")
        all_pairs = find_all_pairs_cached(
            tree,
            result_dir,
            counters_filter=None,
            contrib_threshold=args.contribution,
            visit_threshold=args.visits,
            all_counters=args.all_counters,
            min_resilience=args.min_resilience,
        )

    # Determine threshold
    min_threshold = 0.8
    if args.no_auto_threshold:
        if args.threshold is None:
            print("Error: --no-auto-threshold requires -t/--threshold to be specified", file=sys.stderr)
            return 1
        threshold = args.threshold
    elif args.threshold is not None:
        threshold = args.threshold
    else:
        threshold = find_correlation_knee(all_pairs)
        print(f"Auto-detected knee threshold: {threshold:.4f}")
        threshold = max(threshold, min_threshold)
        if threshold > find_correlation_knee(all_pairs):
            print(f"Enforced minimum threshold: {threshold:.4f}")

    if args.plot_knee:
        plot_correlation_knee(all_pairs)

    # Filter cache counters if requested
    pairs_to_filter = all_pairs
    if args.exclude_cache:
        cache_counters = {c for row in all_pairs for c in [row[0], row[1]]}
        cache_counters = [c for c in cache_counters if is_cache_counter(c)]
        pairs_to_filter = filter_pairs_by_counters(all_pairs, cache_counters)
        print(f"Excluded {len(all_pairs) - len(pairs_to_filter)} pairs with cache counters")

    # Filter to threshold
    pairs = [p for p in pairs_to_filter if abs(p[2]) >= threshold]
    print(f"\nFound {len(pairs)} redundant pairs at threshold >= {threshold:.4f}:")
    print_redundant_pairs(pairs, threshold)

    # Select counters using the deviation ranking
    # normalized counter names (without PAPI_ prefix) in the ranking
    if args.exclude_cache:
        ranked = [c for c in ranked if not is_cache_counter(c)]
    final = select_counters(ranked, pairs_to_filter, threshold)
    print(f"\nCounters to measure ({len(final)} of {len(ranked)}): {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())