# This file is part of the NORC software
#
# Copyright (c) 2024-2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
import sys
import argparse
import itertools
import numpy as np

from pycubexr import CubexParser
from tqdm import tqdm

from norc.helpers.util import (
    warn,
    iterate_measurements,
    open_experiment_source,
    ExperimentTree,
    data_selection,
    measurement_info,
    load_measurement,
    write_measurement,
)
from norc.core.score import compute_scores, find_cutoff, CACHEABLE_SELECTIONS

flt_isdir = lambda e: e[2] and not e[0].startswith(".")

# Raw HW counter values above this are treated as measurement artifacts (see analyze.py).
ARTIFACT_THRESHOLD = 1e13


def collect_counter_samples(tree: ExperimentTree, result_dir, counters_filter=None):
    """Collect raw per-(sweep point, callpath, thread) counter values from every
    NO_NOISE measurement.

    Noisy measurements are skipped: whether two counters track the same underlying
    hardware resource doesn't depend on injected noise, and skipping them roughly
    halves the number of cubex files that need parsing.

    Samples are keyed by (benchmark, params, system, res_cfg, region name, repetition,
    thread) rather than by raw array position, so that counters split across separate
    profile.cubex files (as happens whenever a run needs more simultaneous counters
    than PAPI can sample at once) can still be compared on the same underlying event,
    not just counters that happened to land in one file together.

    If `counters_filter` is given, only those counter names are read; a
    profile.cubex whose measured counters don't intersect it at all is skipped
    without even being opened.
    """
    samples = {}  # key -> {counter: value}

    for meas in tqdm(list(iterate_measurements(tree, result_dir))):
        if meas.noise_pattern != "NO_NOISE":
            continue
        counters = meas.counters.strip(",").split(",")
        if counters_filter is not None:
            # counters_filter holds names as produced by score.py, which strips
            # the "PAPI_" prefix (see measurement_info.from_key); meas.counters
            # keeps the raw, prefixed names used to address the cubex metrics.
            counters = [c for c in counters if c.replace("PAPI_", "") in counters_filter]
            if not counters:
                continue

        # Each `meas.dirs` entry is the NO_NOISE.<params> folder, which holds one
        # subfolder per repetition (measurement.r1, measurement.r2, ...) -- the
        # actual profile.cubex lives one level deeper, exactly as in analyze.py.
        rep_dirs = []
        for d in meas.dirs:
            rep_dirs += [path for _, path, _ in filter(flt_isdir, tree.scandir(d))]

        for rep_idx, exdir in enumerate(rep_dirs):
            cubex_path = os.path.join(exdir, "profile.cubex")
            if not tree.exists(cubex_path):
                continue

            try:
                with tree.cubex_source(cubex_path) as cubex_source, CubexParser(cubex_source) as experiment:
                    for counter in counters:
                        metric_values = experiment.get_metric_values(
                            experiment.get_metric_by_name(counter), allow_full_uint64_values=True
                        )

                        def iterate_cnodes(cnode):
                            for child in cnode.get_children():
                                iterate_cnodes(child)
                            if cnode.id not in metric_values.cnode_indices:
                                return
                            vals = np.abs(metric_values.cnode_values(cnode))
                            # ponytail: region name only (no full call path) can collide
                            # for recursive/duplicate-named regions at different depths;
                            # upgrade to a full path key (see analyze.py) if that shows up.
                            for thread_idx, v in enumerate(vals):
                                if v > ARTIFACT_THRESHOLD:
                                    continue
                                key = (
                                    meas.benchmark,
                                    meas.params,
                                    meas.system,
                                    meas.res_cfg,
                                    cnode.region.name,
                                    rep_idx,
                                    thread_idx,
                                )
                                samples.setdefault(key, {})[counter] = v

                        for cnode_ in experiment.get_root_cnodes():
                            iterate_cnodes(cnode_)
            except KeyboardInterrupt:
                print("Exiting on keyboard interrupt")
                exit(0)
            except Exception:
                warn(f"Skipping {exdir}")
                continue

    return samples


def _all_pairs_cache_path(tree, contrib_threshold, visit_threshold, all_counters):
    key = "all" if all_counters else f"c{contrib_threshold}_v{visit_threshold}"
    return os.path.join(tree.root, "result", ".redundancy", f"correlations_{key}.pickle")


def find_all_pairs_cached(
    tree: ExperimentTree,
    result_dir,
    counters_filter,
    contrib_threshold,
    visit_threshold,
    all_counters,
    min_resilience=None,
):
    """Correlate every co-occurring counter pair (no threshold cutoff) and cache
    the result in the experiment archive, so re-running with a different `-t`
    reuses it instead of reparsing every profile.cubex and recorrelating.

    Only cached for the thresholds in `CACHEABLE_SELECTIONS` (the same combos
    `norc_score` caches), and only when `min_resilience` is left at its default
    -- it can pull in extra counters beyond the cutoff, so a non-default
    value always recomputes rather than risk serving a cache that's missing
    counters it would have added.
    """
    cacheable = all_counters or (
        min_resilience is None and (contrib_threshold, visit_threshold) in CACHEABLE_SELECTIONS
    )
    cache_path = _all_pairs_cache_path(tree, contrib_threshold, visit_threshold, all_counters)

    if cacheable and tree.exists(cache_path):
        cached = load_measurement(tree, cache_path)
        if cached is not None:
            return cached

    samples = collect_counter_samples(tree, result_dir, counters_filter)
    all_pairs = find_redundant_pairs(samples, threshold=0.0)

    if cacheable:
        write_measurement(tree, cache_path, all_pairs)

    return all_pairs


def _ranked_items(experiment_root, contrib_threshold=0, visit_threshold=0):
    """Score every counter and return (sorted_items, cutoff_idx), shared by
    `counters_above_cutoff` and `ranked_counters_above_cutoff`."""
    selection = data_selection()
    selection.lump_benchmarks = True
    selection.lump_noise = True
    selection.lump_params = True
    selection.lump_resources = True
    selection.lump_systems = True
    selection.contrib_threshold = contrib_threshold
    selection.visit_threshold = visit_threshold

    sgp = compute_scores(experiment_root, selection)
    sorted_items = sorted(sgp.scores.items(), key=lambda it: it[1].rel_resilience, reverse=True)
    cutoff_idx = find_cutoff([sc.rel_resilience for _, sc in sorted_items])
    return sorted_items, cutoff_idx


def counters_above_cutoff(experiment_root, contrib_threshold=0, visit_threshold=0, min_resilience=None):
    """Return the set of counter names at or above the resilience cutoff,
    using the same scoring/cutoff logic as `norc_score`.

    If `min_resilience` is given, a counter is included when it clears
    *either* criterion: at/above the cutoff, or `rel_resilience >= min_resilience`
    (independent criteria, not both required)."""
    sorted_items, cutoff_idx = _ranked_items(experiment_root, contrib_threshold, visit_threshold)
    return {
        measurement_info.from_key(key).counter
        for i, (key, sc) in enumerate(sorted_items)
        if i <= cutoff_idx or (min_resilience is not None and sc.rel_resilience >= min_resilience)
    }


def ranked_counters_above_cutoff(experiment_root, contrib_threshold=0, visit_threshold=0, min_resilience=None):
    """Same selection as `counters_above_cutoff`, but as a list of counter names
    ordered best-to-worst by `rel_resilience` (ties broken by first occurrence),
    for use as the priority order in `select_counters`."""
    sorted_items, cutoff_idx = _ranked_items(experiment_root, contrib_threshold, visit_threshold)
    names = []
    seen = set()
    for i, (key, sc) in enumerate(sorted_items):
        if i <= cutoff_idx or (min_resilience is not None and sc.rel_resilience >= min_resilience):
            name = measurement_info.from_key(key).counter
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def select_counters(ranked, pairs, threshold=0.98):
    """Greedily reduce `ranked` (counter names, best-to-worst) to a set worth
    actually measuring: walk it in order and drop any counter that is
    redundant (|correlation| >= `threshold`, per `pairs`) with one already kept.

    `pairs` is the (counter_a, counter_b, correlation, n_samples) list from
    `find_redundant_pairs`/`find_all_pairs_cached`; its counter names are the
    raw, PAPI_-prefixed ones `collect_counter_samples` stores samples under,
    while `ranked` holds the stripped names `counters_above_cutoff`/`score.py`
    use -- both get normalized here so they compare equal.
    """
    strip = lambda c: c.replace("PAPI_", "")

    redundant_with = {}
    for a, b, r, _n in pairs:
        if abs(r) >= threshold:
            a, b = strip(a), strip(b)
            redundant_with.setdefault(a, set()).add(b)
            redundant_with.setdefault(b, set()).add(a)

    kept = []
    for counter in ranked:
        if not any(other in redundant_with.get(counter, ()) for other in kept):
            kept.append(counter)
    return kept


def filter_samples_to_counters(samples, counters):
    return {
        key: {c: v for c, v in row.items() if c in counters}
        for key, row in samples.items()
    }


def find_redundant_pairs(samples, threshold=0.98):
    """Pairwise-correlate every pair of counters that co-occur in `samples`
    (as produced by `collect_counter_samples`) and return the pairs whose
    |Pearson correlation| is at least `threshold`, sorted strongest first.

    A near-perfect linear relationship across many independent sweep points,
    callpaths and threads is architecture- and counter-name-agnostic evidence
    that two counters are aggregating (or derived from) the same underlying
    hardware resource, so only one of them needs to be kept.

    Returns a list of (counter_a, counter_b, correlation, n_samples) tuples.
    """
    counters = sorted({c for row in samples.values() for c in row})
    rows = list(samples.values())

    n_pairs = len(counters) * (len(counters) - 1) // 2
    pairs = []
    for a, b in tqdm(itertools.combinations(counters, 2), total=n_pairs):
        xa, xb = [], []
        for row in rows:
            if a in row and b in row:
                xa.append(row[a])
                xb.append(row[b])
        if len(xa) < 2 or np.std(xa) == 0 or np.std(xb) == 0:
            continue
        r = np.corrcoef(xa, xb)[0, 1]
        if np.isfinite(r) and abs(r) >= threshold:
            pairs.append((a, b, r, len(xa)))

    return sorted(pairs, key=lambda p: -abs(p[2]))


def print_redundant_pairs(pairs, threshold):
    if not pairs:
        print(f"No counter pairs with |correlation| >= {threshold} found.")
        return

    print(f"Counter pairs with |correlation| >= {threshold}:")
    for a, b, r, n in pairs:
        print(f"  {a} ~ {b}\tr={r:.4f}\t(n={n})")


def _test_filter_samples_to_counters():
    samples = {1: {"A": 1.0, "B": 2.0, "C": 3.0}, 2: {"A": 4.0, "C": 5.0}}
    filtered = filter_samples_to_counters(samples, {"A", "C"})
    assert filtered == {1: {"A": 1.0, "C": 3.0}, 2: {"A": 4.0, "C": 5.0}}


def _test_select_counters():
    # pairs use the raw PAPI_-prefixed names collect_counter_samples stores,
    # ranked uses the stripped names counters_above_cutoff returns.
    ranked = ["A", "B", "C", "D"]
    pairs = [("PAPI_A", "PAPI_B", 0.99, 100), ("PAPI_C", "PAPI_D", 0.5, 100)]
    assert select_counters(ranked, pairs, threshold=0.98) == ["A", "C", "D"]


def _test_find_redundant_pairs():
    rng = np.random.default_rng(0)
    n = 200
    base = rng.normal(size=n)

    samples = {}
    for i in range(n):
        samples[i] = {
            "A": base[i],
            "B": 2.0 * base[i] + 1.0,  # perfectly redundant with A
            "C": rng.normal(),  # independent
        }

    pairs = find_redundant_pairs(samples, threshold=0.98)
    assert len(pairs) == 1
    a, b, r, cnt = pairs[0]
    assert {a, b} == {"A", "B"}
    assert r > 0.98
    assert cnt == n


def main():
    parser = argparse.ArgumentParser(
        description="Detect PAPI counters that are redundant (near-perfectly "
        "correlated) across the measured parameter sweep."
    )
    parser.add_argument("experiment_root")
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=0.98,
        help="Minimum |Pearson correlation| to flag a counter pair as redundant (default: 0.98)",
    )
    parser.add_argument(
        "--all-counters",
        action="store_true",
        help="Consider all measured counters instead of restricting to those at or "
        "above the resilience cutoff (as determined by norc_score).",
    )
    parser.add_argument(
        "-c",
        "--contribution",
        type=float,
        default=0,
        help="Contribution threshold used when scoring for the cutoff (default: 0)",
    )
    parser.add_argument(
        "-v",
        "--visits",
        type=int,
        default=0,
        help="Visit threshold used when scoring for the cutoff (default: 0)",
    )
    parser.add_argument(
        "-r",
        "--min-resilience",
        type=float,
        default=None,
        help="Also include counters with rel_resilience >= this value, independently "
        "of the cutoff (default: none, cutoff alone decides).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't read/write the cached correlations in result/.redundancy/; "
        "always reparse every profile.cubex and recorrelate.",
    )
    parser.add_argument(
        "--select",
        action="store_true",
        help="Instead of listing redundant pairs, print the final set of counters worth "
        "measuring: the resilience ranking (same as norc_score) with redundant lower-ranked "
        "counters (|correlation| >= --threshold) dropped in favor of the higher-ranked one.",
    )
    args = parser.parse_args()

    counters = None
    if not args.all_counters:
        counters = counters_above_cutoff(args.experiment_root, args.contribution, args.visits, args.min_resilience)
        print(f"Restricting to {len(counters)} counter(s) above the cutoff: {sorted(counters)}")

    with open_experiment_source(args.experiment_root, read_only=args.no_cache) as tree:
        result_dir = os.path.join(tree.root, "result")
        if args.no_cache:
            samples = collect_counter_samples(tree, result_dir, counters)
            all_pairs = find_redundant_pairs(samples, threshold=0.0)
        else:
            all_pairs = find_all_pairs_cached(
                tree,
                result_dir,
                counters,
                args.contribution,
                args.visits,
                args.all_counters,
                args.min_resilience,
            )

    pairs = [p for p in all_pairs if abs(p[2]) >= args.threshold]

    print_redundant_pairs(pairs, args.threshold)

    if args.select:
        ranked = (
            sorted(counters)
            if args.all_counters
            else ranked_counters_above_cutoff(args.experiment_root, args.contribution, args.visits, args.min_resilience)
        )
        final = select_counters(ranked, all_pairs, args.threshold)
        print(f"Counters to measure ({len(final)} of {len(ranked)}): {final}")


if __name__ == "__main__":
    main()
