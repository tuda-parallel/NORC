# This file is part of the NORC software
#
# Copyright (c) 2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

"""Estimate the total execution time of an experiment (or a plain directory of
measurement output), to help plan how long a measurement campaign will take.

Two independent sources can be used:

- "timings": sums plain-text timing values (one float per line) found in any
  `timings/` directory below the given root. Fast, but only as accurate as
  whatever wrote those files.
- "cubex": sums the maximal inclusive "time" metric of every `.cubex` profile
  below the given root, via pycubexr. Slower, but reflects what was actually
  measured.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from pycubexr import CubexParser

from norc.helpers.util import DirTree, open_experiment_source


def walk_tree(tree, path):
    """Yields (dirpath, dirnames, filenames) for `path` and everything below it,
    same shape as os.walk, but through an ExperimentTree (so it works on zip
    archives too)."""
    entries = tree.scandir(path)
    dirnames = [name for name, _, is_dir in entries if is_dir]
    filenames = [name for name, _, is_dir in entries if not is_dir]
    yield path, dirnames, filenames
    for name, subpath, is_dir in entries:
        if is_dir:
            yield from walk_tree(tree, subpath)


def sum_timings(tree, root, timings_dirname="timings", outlier_threshold=300):
    """Sums timing values from text files in any `timings_dirname` directory
    below `root`. Values above `outlier_threshold` are reported separately and
    excluded from the sum.

    Returns (total_seconds, outliers).
    """
    total = 0.0
    outliers = []

    for dirpath, _, filenames in walk_tree(tree, root):
        if os.path.basename(dirpath) != timings_dirname:
            continue
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            try:
                with tree.open_binary(file_path) as f:
                    text = f.read().decode("utf-8", errors="replace")
            except (OSError, IOError) as e:
                print(f"Error when reading {file_path}: {e}", file=sys.stderr)
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    value = float(line)
                except ValueError:
                    continue
                if value > outlier_threshold:
                    outliers.append(value)
                    continue
                total += value

    return total, outliers


def find_cubex_files(tree, root):
    """Recursively finds all .cubex files below `root`."""
    return [
        os.path.join(dirpath, filename)
        for dirpath, _, filenames in walk_tree(tree, root)
        for filename in filenames
        if filename.lower().endswith(".cubex")
    ]


def get_max_inclusive_time(tree, cubex_path):
    """Extracts the maximal inclusive "time" metric from a .cubex file."""
    try:
        with tree.cubex_source(cubex_path) as source, CubexParser(source) as cube:
            metric = cube.get_metric_by_name("time")
            return float(cube.get_metric_values(metric).values.max())
    except Exception as e:
        print(f"Error processing {cubex_path}: {e}", file=sys.stderr)
        return 0.0


def sum_cubex_times(tree, root, jobs=None):
    """Sums the maximal inclusive time across every .cubex file below `root`.

    Files are parsed in parallel when `tree` is backed by a real directory
    (a DirTree pickles trivially); a zip-backed tree is read sequentially,
    since the underlying archive handle can't be shared across processes.

    Returns (total_seconds, n_files).
    """
    cubex_files = find_cubex_files(tree, root)
    n = len(cubex_files)
    if n == 0:
        return 0.0, 0

    total_time = 0.0

    if isinstance(tree, DirTree):
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            futures = {
                executor.submit(get_max_inclusive_time, tree, f): f for f in cubex_files
            }
            for i, future in enumerate(as_completed(futures), 1):
                total_time += future.result()
                if i % 100 == 0 or i == n:
                    print(f"{i}/{n}")
    else:
        for i, f in enumerate(cubex_files, 1):
            total_time += get_max_inclusive_time(tree, f)
            if i % 100 == 0 or i == n:
                print(f"{i}/{n}")

    return total_time, n


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Estimate total experiment execution time from timing logs or .cubex profiles"
    )
    parser.add_argument(
        "--overhead",
        type=float,
        default=0.10,
        help="Fractional overhead added on top of the summed time (default: 0.10)",
    )

    subparsers = parser.add_subparsers(dest="mode", required=True)

    timings_parser = subparsers.add_parser(
        "timings", help="Sum plain-text timing values under timings/ directories"
    )
    timings_parser.add_argument("root", help="Experiment directory or zip archive to scan")
    timings_parser.add_argument(
        "--timings-dirname",
        default="timings",
        help="Name of the directories holding timing files (default: timings)",
    )
    timings_parser.add_argument(
        "--outlier-threshold",
        type=float,
        default=300,
        help="Values above this (in seconds) are reported as outliers and excluded (default: 300)",
    )

    cubex_parser = subparsers.add_parser(
        "cubex", help="Sum maximal inclusive time across .cubex profiles"
    )
    cubex_parser.add_argument("root", help="Experiment directory or zip archive to scan")
    cubex_parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Number of worker processes (default: all available cores; ignored for zip archives)",
    )

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    try:
        tree = open_experiment_source(args.root)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    with tree:
        if args.mode == "timings":
            total, outliers = sum_timings(
                tree, tree.root, args.timings_dirname, args.outlier_threshold
            )
            for value in outliers:
                print(f"Outlier: {value}")
        else:
            total, n = sum_cubex_times(tree, tree.root, args.jobs)
            if n == 0:
                print("No .cubex files found.")
                sys.exit(1)

    print(f"Total in seconds: {total}")
    print(f"Total in seconds plus {args.overhead * 100:.0f}% overhead: {total * (1 + args.overhead)}")


if __name__ == "__main__":
    main()