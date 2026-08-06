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

try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    from scipy.cluster.hierarchy import dendrogram, linkage, fcluster
    from scipy.spatial.distance import squareform

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from norc.helpers.util import (
    warn,
    iterate_measurements,
    open_experiment_source,
    ExperimentTree,
    load_measurement,
    write_measurement,
)
from norc.core.score import CACHEABLE_SELECTIONS, counters_above_cutoff, ranked_counters_above_cutoff, find_cutoff

flt_isdir = lambda e: e[2] and not e[0].startswith(".")


def is_cache_counter(counter_name):
    """Check if a counter is a cache hit/miss event."""
    normalized = counter_name.replace("PAPI_", "").upper()
    cache_suffixes = ("_DCH", "_ICH", "_DCM", "_ICM", "_TCH", "_TCM", "_LDM", "_STM", "BR_PRC", "BR_MSP", "CA_",
                      "STL", "STAL", "_IDL", "_TLB_")
    return any(suffix in normalized for suffix in cache_suffixes)


def filter_out_cache_counters(counters):
    """Remove cache hit/miss counters from the list."""
    return [c for c in counters if not is_cache_counter(c)]


def filter_pairs_by_counters(pairs, excluded_counters):
    """Remove pairs where either counter is in the excluded set."""
    excluded = set(c.replace("PAPI_", "") for c in excluded_counters)
    return [p for p in pairs if p[0].replace("PAPI_", "") not in excluded and p[1].replace("PAPI_", "") not in excluded]


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
        if not any(strip(other) in redundant_with.get(strip(counter), ()) for other in kept):
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


def find_correlation_knee(all_pairs):
    """Detect the knee in correlation strengths using the max-distance-to-chord method.

    Returns the correlation threshold at the knee point, or 0.0 if too few pairs.
    """
    if not all_pairs:
        return 0.0

    correlations = sorted([abs(p[2]) for p in all_pairs], reverse=True)
    if len(correlations) < 3:
        return correlations[0] if correlations else 0.0

    knee_idx = find_cutoff(correlations)
    return correlations[knee_idx]


def plot_correlation_knee(all_pairs, output_file="correlation_knee_debug.png"):
    """Plot correlations and the detected knee point for debug purposes.

    X-axis is unlabeled (just rank index).
    """
    if not HAS_MATPLOTLIB:
        warn("matplotlib not available; skipping plot")
        return

    if not all_pairs:
        warn("No pairs to plot")
        return

    correlations = sorted([abs(p[2]) for p in all_pairs], reverse=True)
    if len(correlations) < 3:
        warn(f"Too few correlations ({len(correlations)}) to plot")
        return

    knee_idx = find_cutoff(correlations)
    knee_value = correlations[knee_idx]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(range(len(correlations)), correlations, marker="o", markersize=3, label="Correlations")
    ax.axhline(knee_value, color="red", linestyle="--", linewidth=1, label=f"Knee: {knee_value:.4f}")
    ax.plot(knee_idx, knee_value, "ro", markersize=8)
    ax.plot([0, len(correlations) - 1], [max(correlations), min(correlations)], color="grey", linestyle="dotted",
            label="Reference")

    ax.set_ylabel("Absolute Correlation", fontsize=11)
    ax.set_title("Correlation Knee Detection", fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_file, dpi=100)
    print(f"Saved debug plot to {output_file}")
    plt.close(fig)


def build_correlation_matrix_from_pairs(all_pairs):
    """Build correlation matrix from pre-computed pairs (counter_a, counter_b, correlation, n_samples).

    Returns sorted counter list and NxN correlation matrix with 1.0 on diagonal.
    """
    counters = sorted({c for pair in all_pairs for c in [pair[0], pair[1]]})
    if not counters:
        return [], np.zeros((0, 0))

    n = len(counters)
    matrix = np.zeros((n, n))
    counter_to_idx = {c: i for i, c in enumerate(counters)}

    for a, b, r, _n in all_pairs:
        i, j = counter_to_idx[a], counter_to_idx[b]
        matrix[i, j] = r
        matrix[j, i] = r

    np.fill_diagonal(matrix, 1.0)
    return counters, matrix


def plot_correlation_heatmap(all_pairs, output_file="correlation_heatmap.png"):
    """Plot a heatmap of pairwise correlations between all counters for debugging."""
    if not HAS_MATPLOTLIB:
        warn("matplotlib not available; skipping plot")
        return

    counters, matrix = build_correlation_matrix_from_pairs(all_pairs)
    if len(counters) < 2:
        warn(f"Need at least 2 counters, got {len(counters)}")
        return

    fig, ax = plt.subplots(figsize=(max(8, len(counters) * 0.5), max(8, len(counters) * 0.5)))
    im = ax.imshow(matrix, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)

    ax.set_xticks(range(len(counters)))
    ax.set_yticks(range(len(counters)))
    ax.set_xticklabels(counters, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(counters, fontsize=8)

    ax.set_title(f"Counter Correlation Heatmap ({len(counters)} counters)", fontsize=12)
    cbar = fig.colorbar(im, ax=ax, label="Pearson Correlation")

    fig.tight_layout()
    fig.savefig(output_file, dpi=100, bbox_inches="tight")
    print(f"Saved correlation heatmap to {output_file}")
    plt.close(fig)


def cluster_counters_by_correlation(all_pairs, output_file="counter_clustering.png", n_clusters=None):
    """Hierarchically cluster counters by how similarly they behave, using
    1 - |correlation| as the distance (perfectly (anti-)correlated counters
    have distance 0). Plots a dendrogram in the same style as
    compare_to_ground_truth.py's cluster_metrics_by_deviation: each junction
    is annotated with the medoid (lowest average distance to the other
    counters in its merged group) counter.
    """
    if not HAS_MATPLOTLIB or not HAS_SCIPY:
        warn("matplotlib/scipy not available; skipping cluster plot")
        return

    counters, corr_matrix = build_correlation_matrix_from_pairs(all_pairs)
    if len(counters) < 2:
        warn(f"Need at least 2 counters, got {len(counters)}")
        return

    dist_matrix = 1 - np.abs(corr_matrix)
    np.fill_diagonal(dist_matrix, 0.0)
    Z = linkage(squareform(dist_matrix, checks=False), method="average")

    if n_clusters is not None:
        heights = np.sort(Z[:, 2])
        n_merges = len(heights)
        k = min(max(n_clusters, 1), n_merges + 1)
        if k >= n_merges + 1:
            color_threshold = 0.0
        elif k <= 1:
            color_threshold = heights[-1] * 1.01
        else:
            color_threshold = (heights[n_merges - k] + heights[n_merges - k + 1]) / 2
    else:
        color_threshold = max(Z[:, 2]) * 0.5 if len(Z) else 0.0

    fig, ax = plt.subplots(figsize=(max(10, len(counters) * 0.3), 8))
    dendro = dendrogram(Z, labels=counters, ax=ax, leaf_font_size=8, leaf_rotation=90,
                        color_threshold=color_threshold)

    # Annotate every junction with the medoid (lowest mean distance to the
    # other counters already in its group) among the leaves it joins.
    display_index = {label: i for i, label in enumerate(dendro["ivl"])}
    cluster_x = {i: 5 + 10 * display_index[counters[i]] for i in range(len(counters))}
    cluster_leaves = {i: {i} for i in range(len(counters))}

    for row_idx, (a, b, dist, _count) in enumerate(Z):
        a, b = int(a), int(b)
        merged_id = len(counters) + row_idx
        x = (cluster_x[a] + cluster_x[b]) / 2
        leaves = cluster_leaves[a] | cluster_leaves[b]
        cluster_x[merged_id] = x
        cluster_leaves[merged_id] = leaves

        medoid = min(leaves,
                     key=lambda i: np.mean([dist_matrix[i, j] for j in leaves if j != i]) if len(leaves) > 1 else 0.0)
        ax.text(x, dist, counters[medoid], ha="center", va="bottom", fontsize=9, color="red", weight="bold")

    ax.set_xlabel("Counter")
    ax.set_ylabel("Distance (1 - |correlation|)")
    ax.set_title(
        f"Counter Clustering by Correlation ({len(counters)} counters)\n"
        "(annotated by medoid counter per cluster)"
    )
    fig.tight_layout()
    fig.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"Saved counter clustering to {output_file}")
    plt.close(fig)

    clusters = fcluster(Z, t=color_threshold, criterion="distance") if len(Z) else np.array([1] * len(counters))
    print("\nCluster medoids:")
    for cluster_id in sorted(np.unique(clusters)):
        members = [i for i, c in enumerate(clusters) if c == cluster_id]
        medoid = min(members,
                     key=lambda i: np.mean([dist_matrix[i, j] for j in members if j != i]) if len(members) > 1 else 0.0)
        print(f"  Cluster {cluster_id}: {counters[medoid]} ({[counters[i] for i in members]})")


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


def _test_cluster_counters_by_correlation():
    if not HAS_SCIPY:
        return
    # A/B near-perfectly correlated, C uncorrelated with either -> A/B should
    # merge at a much smaller distance than C joins them.
    all_pairs = [("A", "B", 0.99, 100), ("A", "C", 0.01, 100), ("B", "C", 0.02, 100)]
    counters, matrix = build_correlation_matrix_from_pairs(all_pairs)
    dist_matrix = 1 - np.abs(matrix)
    Z = linkage(squareform(dist_matrix, checks=False), method="average")
    first_merge_members = {counters[int(Z[0, 0])], counters[int(Z[0, 1])]}
    assert first_merge_members == {"A", "B"}


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
        default=None,
        help="Minimum |Pearson correlation| to flag a counter pair as redundant (default: auto-detect knee, or 0.8 if no --auto-threshold)",
    )
    parser.add_argument(
        "--auto-threshold",
        action="store_true",
        help="Automatically detect the correlation threshold at the knee point instead of using a fixed value",
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
             "counters (|correlation| >= threshold) dropped in favor of the higher-ranked one.",
    )
    parser.add_argument(
        "--plot-knee",
        action="store_true",
        help="Generate a debug plot of correlations and knee detection",
    )
    parser.add_argument(
        "--plot-heatmap",
        action="store_true",
        help="Generate a heatmap of pairwise correlations between all counters",
    )
    parser.add_argument(
        "--plot-cluster",
        action="store_true",
        help="Generate a dendrogram hierarchically clustering counters by correlation "
             "(1 - |correlation| distance), similar to --plot-heatmap",
    )
    parser.add_argument(
        "--cluster-count",
        type=int,
        default=None,
        help="Cut the cluster dendrogram into exactly this many clusters (default: "
             "auto-detect via a distance threshold)",
    )
    parser.add_argument(
        "--exclude-cache",
        action="store_true",
        help="Exclude cache hit/miss counters from redundancy analysis",
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

        # Filter cache counters if requested, before anything (plots included) sees all_pairs.
        if args.exclude_cache:
            cache_counters = {c for row in all_pairs for c in [row[0], row[1]]}
            cache_counters = [c for c in cache_counters if is_cache_counter(c)]
            filtered = filter_pairs_by_counters(all_pairs, cache_counters)
            print(f"Excluded {len(all_pairs) - len(filtered)} pairs with hit/miss counters")
            all_pairs = filtered

        if args.plot_heatmap:
            plot_correlation_heatmap(all_pairs)

        if args.plot_cluster:
            cluster_counters_by_correlation(all_pairs, n_clusters=args.cluster_count)

    # Determine threshold
    min_threshold = 0.8
    if args.auto_threshold:
        threshold = find_correlation_knee(all_pairs)
        print(f"Auto-detected knee threshold: {threshold:.4f}")
        threshold = max(threshold, min_threshold)
        if threshold > find_correlation_knee(all_pairs):
            print(f"Enforced minimum threshold: {threshold:.4f}")
    elif args.threshold is not None:
        threshold = args.threshold
    else:
        threshold = min_threshold
        print(f"Using default threshold: {threshold}")

    if args.plot_knee:
        plot_correlation_knee(all_pairs)

    pairs = [p for p in all_pairs if abs(p[2]) >= threshold]

    print_redundant_pairs(pairs, threshold)

    if args.select:
        ranked = (
            sorted(counters)
            if args.all_counters
            else ranked_counters_above_cutoff(args.experiment_root, args.contribution, args.visits, args.min_resilience)
        )
        if args.exclude_cache:
            ranked = [c for c in ranked if not is_cache_counter(c)]
        final = select_counters(ranked, pairs, threshold)
        print(f"Counters to measure ({len(final)} of {len(ranked)}): {final}")


if __name__ == "__main__":
    main()
