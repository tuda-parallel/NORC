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
            rows[key] = (float(row['expected']), float(row['modeled']))
    return rows


def compute_mad_for_combination(counters, exponents, kernels, technique='mean'):
    """Compute mean absolute deviation for a combination of counters.

    For each kernel, combines the predicted exponents from all counters using
    the specified technique, computes deviation from ground truth, then computes
    MAD across kernels.

    technique: 'mean', 'median', 'min', or 'max'
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
            if technique == 'mean':
                combined_pred = np.mean(predictions)
            elif technique == 'median':
                combined_pred = np.median(predictions)
            elif technique == 'min':
                combined_pred = np.min(predictions)
            elif technique == 'max':
                combined_pred = np.max(predictions)
            else:
                raise ValueError(f"Unknown technique: {technique}")

            deviation = combined_pred - expected
            deviations.append(abs(deviation))

    return np.mean(deviations) if deviations else float('inf')


def compute_individual_mad(counter, exponents, kernels):
    """Compute MAD for a single counter across all kernels."""
    deviations = []
    for kernel in kernels:
        if (kernel, counter) in exponents:
            exp, pred = exponents[(kernel, counter)]
            deviation = abs(pred - exp)
            deviations.append(deviation)
    return np.mean(deviations) if deviations else float('inf')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'deviations_csv',
        type=Path,
        help='Path to deviations.csv from compare_to_ground_truth.py'
    )
    parser.add_argument(
        '-k', '--max-size',
        type=int,
        default=5,
        help='Maximum combination size to search (default: 5)'
    )
    parser.add_argument(
        '--mad-threshold',
        type=float,
        default=0.5,
        help='Only consider counters with individual MAD <= this threshold (default: 0.5)'
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
    print(f"All counters: {len(all_counters)}")

    # Filter counters by MAD threshold
    print(f"\nFiltering counters with MAD <= {args.mad_threshold}...")
    counter_mads = {}
    for counter in all_counters:
        mad = compute_individual_mad(counter, exponents, kernels)
        counter_mads[counter] = mad

    filtered_counters = [c for c in all_counters if counter_mads[c] <= args.mad_threshold]
    filtered_counters.sort(key=lambda c: counter_mads[c])

    print(f"Counters passing filter: {len(filtered_counters)} of {len(all_counters)}")
    for counter in filtered_counters:
        print(f"  {counter}: MAD={counter_mads[counter]:.4f}")
    print()

    techniques = ['mean', 'median', 'min', 'max']
    results = []

    for size in range(1, min(args.max_size + 1, len(filtered_counters) + 1)):
        print(f"Searching combinations of size {size}...")
        size_results = {'size': size, 'techniques': {}}

        for technique in techniques:
            print(f"  Technique: {technique}")
            best_mad = float('inf')
            best_combo = None
            all_results_for_technique = []

            for combo in combinations(filtered_counters, size):
                mad = compute_mad_for_combination(combo, exponents, kernels, technique)
                all_results_for_technique.append((combo, mad))
                if mad < best_mad:
                    best_mad = mad
                    best_combo = combo

            # Sort and report top 5 for this technique
            all_results_for_technique.sort(key=lambda x: x[1])
            print(f"    Best MAD: {best_mad:.4f}")
            print(f"    Counters: {best_combo}")
            for i, (combo, mad) in enumerate(all_results_for_technique[:5]):
                marker = " ← best" if i == 0 else ""
                print(f"      {i+1}. {mad:.4f}  {combo}{marker}")

            size_results['techniques'][technique] = {
                'best_mad': float(best_mad),
                'best_combination': list(best_combo),
                'top_5': [
                    {'mad': float(mad), 'counters': list(combo)}
                    for combo, mad in all_results_for_technique[:5]
                ]
            }

        # Find the best technique for this size
        best_technique = min(size_results['techniques'].items(),
                            key=lambda x: x[1]['best_mad'])
        print(f"  → Best technique for size {size}: {best_technique[0]} (MAD: {best_technique[1]['best_mad']:.4f})")
        print()

        results.append(size_results)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Wrote results to {args.output}")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
