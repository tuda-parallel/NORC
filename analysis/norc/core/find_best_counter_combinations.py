#!/usr/bin/env python3
"""Find the best combination of up to k counters by exhaustive search.

Reads deviations.csv (produced by compare_to_ground_truth.py) and searches all
subsets of counters up to size k. For each subset and each kernel, averages the
predicted exponents across counters, computes the deviation from ground truth,
then reports the mean absolute deviation across kernels.
"""

import argparse
import csv
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np


def load_exponents(csv_path):
    """Load exponent data from CSV. Returns {(kernel, metric): (expected, predicted)}."""
    rows = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row['kernel'], row['metric'])
            rows[key] = (float(row['expected']), float(row['predicted']))
    return rows


def compute_mad_for_combination(counters, exponents, kernels):
    """Compute mean absolute deviation for a combination of counters.

    For each kernel, averages the predicted exponents from all counters,
    computes deviation from ground truth, then computes MAD across kernels.
    """
    deviations = []
    for kernel in kernels:
        # Collect predicted exponents for this kernel from all counters
        predictions = []
        expected = None
        for counter in counters:
            if (kernel, counter) in exponents:
                exp, pred = exponents[(kernel, counter)]
                predictions.append(pred)
                if expected is None:
                    expected = exp  # Same for all counters of a kernel

        if predictions and expected is not None:
            avg_pred = np.mean(predictions)
            deviation = avg_pred - expected
            deviations.append(abs(deviation))

    return np.mean(deviations) if deviations else float('inf')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--deviations-csv',
        type=Path,
        required=True,
        help='Path to deviations.csv from compare_to_ground_truth.py'
    )
    parser.add_argument(
        '-k', '--max-size',
        type=int,
        default=5,
        help='Maximum combination size to search (default: 5)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=None,
        help='Write results to JSON (default: stdout only)'
    )
    parser.add_argument(
        '--exclude-time',
        action='store_true',
        help='Exclude "time" metric from combinations'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    exponents = load_exponents(args.deviations_csv)

    # Collect unique counters and kernels
    kernels = sorted(set(k for k, _ in exponents.keys()))
    all_counters = sorted(set(m for _, m in exponents.keys()))

    if args.exclude_time and 'time' in all_counters:
        all_counters.remove('time')

    print(f"Loaded {len(exponents)} (kernel, metric) pairs")
    print(f"Kernels: {len(kernels)}")
    print(f"Counters: {len(all_counters)}")
    print()

    results = []
    for size in range(1, min(args.max_size + 1, len(all_counters) + 1)):
        print(f"Searching combinations of size {size}...")
        best_mad = float('inf')
        best_combo = None
        all_results_for_size = []

        for combo in combinations(all_counters, size):
            mad = compute_mad_for_combination(combo, exponents, kernels)
            all_results_for_size.append((combo, mad))
            if mad < best_mad:
                best_mad = mad
                best_combo = combo

        # Sort and report top 5 for this size
        all_results_for_size.sort(key=lambda x: x[1])
        print(f"  Best MAD at size {size}: {best_mad:.4f}")
        print(f"    Counters: {best_combo}")
        for i, (combo, mad) in enumerate(all_results_for_size[:5]):
            marker = " ← best" if i == 0 else ""
            print(f"      {i+1}. {mad:.4f}  {combo}{marker}")
        print()

        results.append({
            'size': size,
            'best_mad': float(best_mad),
            'best_combination': list(best_combo),
            'top_5': [
                {'mad': float(mad), 'counters': list(combo)}
                for combo, mad in all_results_for_size[:5]
            ]
        })

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Wrote results to {args.output}")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
