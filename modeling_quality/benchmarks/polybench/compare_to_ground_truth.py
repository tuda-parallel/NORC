"""Model results_extrap.json with Extra-P and compare the fitted leading
exponent of every metric against GROUND_TRUTH.txt's known complexity.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy
import numpy as np
from extrap.fileio.file_reader.json_file_reader import JsonFileReader
from extrap.modelers.model_generator import ModelGenerator
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster
from scipy.spatial.distance import pdist
from sklearn.preprocessing import StandardScaler

try:
    from norc.core.redundancy import find_redundant_pairs, is_cache_counter
    from norc.core.score import find_cutoff
except ImportError:
    find_redundant_pairs = None
    is_cache_counter = None
    find_cutoff = None

HERE = Path(__file__).parent


def leading_exponent_of_expr(expr):
    exponents = [1.0 for _ in re.findall(r"n(?!\^)", expr)]  # bare n -> exponent 1
    for match in re.findall(r"n\^\(?(\d+(?:/\d+)?)\)?", expr):
        exponents.append(eval(match) if "/" in match else float(match))
    return max(exponents)


def load_ground_truth(path):
    truth = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        kernel, expr = line.split(maxsplit=1)
        truth[kernel] = leading_exponent_of_expr(expr)
    return truth


def leading_exponent(function):
    best = 0.0
    for term in function.compound_terms:
        for simple in term.simple_terms:
            if simple.term_type == "polynomial":
                best = max(best, float(simple.exponent))
    return best


def find_redundant_metrics(rows, ranking, threshold=0.90):
    """Detect redundant metrics using correlation of leading exponents across kernels.

    rows: dict {(kernel, metric_name): (expected, predicted, deviation)}
    ranking: list of (metric_name, mean_abs_dev, n_kernels) tuples

    Returns pairs of (metric_a, metric_b, correlation, n_samples) and selected subset.
    """
    if find_redundant_pairs is None:
        return [], [m for m, _, _ in ranking]

    # Build samples in format {kernel: {metric: predicted_exponent}}
    samples = defaultdict(dict)
    for (kernel, metric_name), (_, predicted_exp, _) in rows.items():
        if metric_name == "time":
            continue
        samples[kernel][metric_name] = predicted_exp

    all_pairs = find_redundant_pairs(samples, threshold=0.0)

    # Build ranked list (best first by mean abs deviation)
    ranked_metrics = [m for m, _, _ in ranking]

    # Greedily select metrics, dropping redundant lower-ranked ones
    redundant_with = {}
    for a, b, r, _n in all_pairs:
        if abs(r) >= threshold:
            redundant_with.setdefault(a, set()).add(b)
            redundant_with.setdefault(b, set()).add(a)

    selected = []
    for metric in ranked_metrics:
        if metric == "time":
            continue
        if not any(other in redundant_with.get(metric, ()) for other in selected):
            selected.append(metric)

    return all_pairs, selected


def print_redundant_metrics(pairs, threshold):
    if not pairs:
        print(f"No metric pairs with |correlation| >= {threshold} found.")
        return

    print(f"\nMetric pairs with |correlation| >= {threshold}:")
    for a, b, r, n in pairs:
        print(f"  {a} ~ {b}\tr={r:.4f}\t(n={n})")


def plot_by_metric(deviations_by_metric, out_path, plot_style="violin"):
    order = sorted(
        deviations_by_metric,
        key=lambda m: -numpy.mean([abs(d) for d in deviations_by_metric[m]]),
    )
    data = [numpy.abs(deviations_by_metric[m]) for m in order]

    # Find knee in the deviation ranking
    # Negate means so they're in descending order (best-to-worst) for find_cutoff
    means = [-numpy.mean(d) for d in data]
    cutoff_idx = None
    if find_cutoff and len(means) >= 3:
        cutoff_idx = find_cutoff(means)

    fig, ax = plt.subplots(figsize=(8, 0.28 * len(order) + 1))
    ax.axvline(0, color="#888888", linewidth=1, zorder=0)
    if plot_style == "violin":
        parts = ax.violinplot(data, vert=False, showmeans=True, showextrema=True)
        for body in parts["bodies"]:
            body.set_facecolor("#2b6cb0")
            body.set_edgecolor("#2b6cb0")
            body.set_alpha(0.6)
        for key in ("cmeans", "cmins", "cmaxes", "cbars"):
            parts[key].set_color("#c05621" if key == "cmeans" else "#2b6cb0")

        # Add median lines
        for i, d in enumerate(data, 1):
            median_val = numpy.median(d)
            ax.plot([median_val, median_val], [i - 0.4, i + 0.4], color="#2b6cb0", linewidth=2, linestyle="--",
                    zorder=1)

        ax.set_yticks(range(1, len(order) + 1), labels=order)
    else:
        ax.boxplot(
            data,
            orientation="horizontal",
            tick_labels=order,
            showfliers=True,
            boxprops=dict(color="#2b6cb0"),
            medianprops=dict(color="#c05621"),
            whiskerprops=dict(color="#2b6cb0"),
            capprops=dict(color="#2b6cb0"),
            flierprops=dict(markeredgecolor="#2b6cb0", markersize=3),
        )

        # Add mean markers
        for i, d in enumerate(data, 1):
            mean_val = numpy.mean(d)
            ax.plot(mean_val, i, marker="D", color="#c05621", markersize=5, zorder=2)

    # Add cutoff line if detected
    if cutoff_idx is not None:
        ax.axhline(cutoff_idx + 0.5, color="red", linestyle="--", linewidth=1.5, zorder=3,
                   label=f"cutoff (idx {cutoff_idx})")
        ax.legend(loc="lower right", fontsize=8)

    ax.set_xlabel("leading-exponent deviation (modeled - expected)")
    ax.set_title("Extra-P leading-exponent deviation by metric, across kernels")
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def plot_heatmap(deviations, kernels, metrics, out_path, deviations_by_metric, clamp=3.0):
    grid = [
        [numpy.clip(deviations.get((kernel, metric), float("nan")), -clamp, clamp) for kernel in kernels]
        for metric in metrics
    ]
    # , (ax3, ax4)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(8.8578, 0.28 * len(metrics) + 3, 'cm'),
                                  gridspec_kw={'width_ratios': (0.75, 0.25), 'wspace': 0},
                                  layout='constrained', sharey=True)
    bound = max(abs(v) for row in grid for v in row if v == v)  # skip NaN
    im = ax.imshow(grid, cmap="RdBu_r", vmin=-bound, vmax=bound, aspect="auto")
    ax.set_xticks(range(len(kernels)), labels=kernels, rotation=90, fontsize=6)
    ax.set_yticks(range(len(metrics)), labels=[m.replace('PAPI_', '') for m in metrics], fontsize=6,
                  fontfamily="monospace")
    cbar = fig.colorbar(
        im, ax=ax, label="lead-exponent deviation (modeled - expected)",
        orientation='horizontal', pad=0.01
    )
    cbar.set_label("Lead-exponent deviation (modeled - expected)", fontsize=7)
    cbar.ax.tick_params(labelsize=6)

    order = sorted(
        deviations_by_metric,
        key=lambda m: numpy.mean([abs(d) for d in deviations_by_metric[m]]),
    )
    data = [numpy.abs(deviations_by_metric[m]) for m in order]

    ax2.violinplot(data, positions=np.arange(0, len(data)), orientation='horizontal', showmeans=True, showextrema=True,
                   widths=0.8)
    # ax2.margins(y=0.002, x=0)
    ax2.tick_params(labelsize=6)
    ax2.yaxis.set_visible(False)
    # ax2.boxplot(
    #     data,
    #     orientation="horizontal",
    #     showmeans=True,
    #     tick_labels=None,
    #     showfliers=True,
    #     boxprops=dict(color="#2b6cb0"),
    #     medianprops=dict(color="#c05621"),
    #     whiskerprops=dict(color="#2b6cb0"),
    #     capprops=dict(color="#2b6cb0"),
    #     flierprops=dict(markeredgecolor="#2b6cb0", markersize=3),
    # )
    # ax2.set_yticks([])
    ax2.set_xlabel("Absolute\nlead-exponent\ndeviation", fontsize=7)


    fig.get_layout_engine().set(w_pad=0, wspace=0)

    # Find cutoff at 0.5 MAD threshold
    cutoff_idx = next((i for i, d in enumerate(data) if np.mean(np.abs(d)) > 0.5), None)

    # Add cutoff line if detected
    if cutoff_idx is not None:
        ax2.axhline(cutoff_idx - 0.5, color="red", linestyle=":", linewidth=1, zorder=3,
                    label=f"0.5 cutoff")
        ax.axhline(cutoff_idx - 0.5, color="red", linestyle=":", linewidth=1, zorder=3)
        ax2.axvline(0.5, color="red", linestyle=":", linewidth=1, zorder=3)
        fig.legend(loc="lower right", fontsize=6, bbox_to_anchor=(1.0, 0.055))

    # ax.set_title("Extra-P leading-exponent deviation by kernel x metric")
    fig.savefig(out_path, bbox_inches='tight', pad_inches=0.01)
    print(f"wrote {out_path}")


def plot_redundancy_heatmap(all_pairs, metrics, out_path):
    """Plot metric correlations from redundancy detection as a heatmap."""
    if not all_pairs or not metrics:
        return

    n = len(metrics)
    matrix = numpy.zeros((n, n))
    metric_to_idx = {m: i for i, m in enumerate(metrics)}

    for a, b, r, _n in all_pairs:
        if a in metric_to_idx and b in metric_to_idx:
            i, j = metric_to_idx[a], metric_to_idx[b]
            matrix[i, j] = r
            matrix[j, i] = r
    numpy.fill_diagonal(matrix, 1.0)

    fig, ax = plt.subplots(figsize=(max(8, n * 0.5), max(8, n * 0.5)))
    im = ax.imshow(matrix, cmap="RdBu_r", aspect="auto", vmin=-1, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(metrics, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(metrics, fontsize=8)
    ax.set_title(f"Metric Correlation Heatmap (redundancy, {n} metrics)", fontsize=12)
    fig.colorbar(im, ax=ax, label="Pearson Correlation")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"wrote {out_path}")


EFFORT_COUNTER_CATEGORIES = {
    "Total instructions": ("PAPI_TOT_INS", []),
    "Branch instructions": ("PAPI_BR_INS", ["PAPI_BR_TKN", "PAPI_BR_NTK", "PAPI_BR_CN", "PAPI_BR_UCN"]),
    "Floating-point operations": (
        "PAPI_FP_OPS",
        ["PAPI_FP_INS", "PAPI_DP_OPS", "PAPI_SP_OPS", "PAPI_VEC_DP", "PAPI_VEC_SP"],
    ),
    "Integer operations": ("PAPI_INT_INS", []),
    "Load instructions": (
        "PAPI_LD_INS",
        ["PAPI_L1_DCR", "PAPI_L2_DCR", "PAPI_L3_DCR", "PAPI_L1_TCR", "PAPI_L2_TCR", "PAPI_L3_TCR",
         "PAPI_LST_INS", "PAPI_L1_DCA", "PAPI_L2_DCA", "PAPI_L3_DCA", "PAPI_L1_TCA", "PAPI_L2_TCA", "PAPI_L3_TCA"],
    ),
    "Store instructions": (
        "PAPI_SR_INS",
        ["PAPI_L1_DCW", "PAPI_L2_DCW", "PAPI_L3_DCW", "PAPI_L1_TCW", "PAPI_L2_TCW", "PAPI_L3_TCW",
         "PAPI_LST_INS", "PAPI_L1_DCA", "PAPI_L2_DCA", "PAPI_L3_DCA", "PAPI_L1_TCA", "PAPI_L2_TCA", "PAPI_L3_TCA"],
    ),
}


def select_rule_based(metric_to_mad, max_mad=0.5):
    """Pick one counter per effort category (recommended, else lowest-MAD
    available alternative) among counters with mean-abs-deviation <= max_mad.

    Returns {category: (counter, mad)} for categories with an eligible counter.
    """
    selected = {}
    for category, (recommended, alternatives) in EFFORT_COUNTER_CATEGORIES.items():
        candidates = [recommended] + alternatives
        eligible = [(c, metric_to_mad[c]) for c in candidates if c in metric_to_mad and metric_to_mad[c] <= max_mad]
        if eligible:
            selected[category] = min(eligible, key=lambda cm: cm[1])
    return selected


def print_rule_based_selection(selected):
    print("\nRule-based selection (recommended counter per category, else best alternative):")
    for category, (counter, mad) in sorted(selected.items(), key=lambda kv: kv[1][1]):
        print(f"  {category:<28}{counter:<16}MAD={mad:.3f}")


ACCURACY_CRITERIA = [
    ("exact match", lambda d: d == 0),
    ("|deviation| <= 0.25", lambda d: abs(d) <= 0.25),
    ("|deviation| <= 0.34", lambda d: abs(d) <= 0.34),
    ("|deviation| <= 0.5", lambda d: abs(d) <= 0.5),
]
ACCURACY_COLORS = [
    "#000000",
    "#08306b",
    "#4292c6",
    "#9ecae1",
]  # dark -> light, strictest -> loosest criterion


def plot_accuracy(deviations_by_metric, out_path):
    pct = {
        m: [
            100 * sum(within(d) for d in ds) / len(ds)
            for _, within in ACCURACY_CRITERIA
        ]
        for m, ds in deviations_by_metric.items()
    }
    order = sorted(
        pct, key=lambda m: -pct[m][0]
    )  # sort by strictest criterion, descending

    y = numpy.arange(len(order))
    bar_height = 0.8 / len(ACCURACY_CRITERIA)

    fig, ax = plt.subplots(figsize=(8, 0.28 * len(order) + 1))
    for i, (label, _) in enumerate(ACCURACY_CRITERIA):
        offset = (i - (len(ACCURACY_CRITERIA) - 1) / 2) * bar_height
        ax.barh(
            y + offset,
            [pct[m][i] for m in order],
            height=bar_height,
            color=ACCURACY_COLORS[i],
            label=label,
        )
    ax.set_yticks(y, labels=order)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("kernels meeting criterion (%)")
    ax.set_title("Extra-P leading-exponent accuracy by metric")
    ax.tick_params(axis="y", labelsize=7)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def write_csv(rows, out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "kernel", "expected", "modeled", "deviation"])
        for (kernel, metric), (expected, predicted, deviation) in sorted(rows.items()):
            writer.writerow([metric, kernel, expected, predicted, deviation])
    print(f"wrote {out_path}")


def cluster_metrics_by_deviation(deviations_by_metric, kernels, out_path, n_clusters=None):
    """Cluster metrics based on similarity of their deviation patterns across kernels.

    Builds a matrix where each row is a metric and each column is a kernel.
    Metrics are clustered by Euclidean distance in deviation space.
    """
    # Sort metrics by mean absolute deviation (lowest first)
    metrics = sorted(
        deviations_by_metric.keys(),
        key=lambda m: numpy.mean(numpy.abs(deviations_by_metric[m]))
    )

    # Build matrix: rows = metrics, cols = kernels
    matrix = []
    for metric in metrics:
        row = [deviations_by_metric[metric][kernels.index(k)] if k in kernels else numpy.nan
               for k in kernels]
        matrix.append(row)
    matrix = numpy.array(matrix)

    # Normalize each metric's deviation vector
    scaler = StandardScaler()
    matrix_norm = scaler.fit_transform(matrix)

    # Hierarchical clustering
    distances = pdist(matrix_norm, metric="euclidean")
    Z = linkage(distances, method="ward")

    # Cluster assignment
    if n_clusters is not None:
        # Pick the distance threshold that cuts the tree into exactly n_clusters
        # groups, so scipy's dendrogram coloring (which also cuts by distance)
        # matches these clusters one-for-one.
        heights = numpy.sort(Z[:, 2])
        n_merges = len(heights)
        k = min(max(n_clusters, 1), n_merges + 1)
        if k >= n_merges + 1:
            color_threshold = 0.0
        elif k <= 1:
            color_threshold = heights[-1] * 1.01
        else:
            color_threshold = (heights[n_merges - k] + heights[n_merges - k + 1]) / 2
        clusters = fcluster(Z, t=color_threshold, criterion="distance")
    else:
        # Auto-detect using distance threshold
        clusters = fcluster(Z, t=max(Z[:, 2]) * 0.5, criterion="distance")
        color_threshold = max(Z[:, 2]) * 0.5
    metric_to_mad = {m: numpy.mean(numpy.abs(deviations_by_metric[m])) for m in metrics}

    # Find best (lowest MAD) metric in each cluster
    cluster_reps = {}
    for cluster_id in numpy.unique(clusters):
        cluster_metrics = [metrics[i] for i, c in enumerate(clusters) if c == cluster_id]
        best = min(cluster_metrics, key=lambda m: metric_to_mad[m])
        cluster_reps[cluster_id] = best

    # Plot dendrogram with heatmap of clustered data
    fig, (ax) = plt.subplots(1, 1, figsize=(8.8578, 6, 'cm'),
                             # gridspec_kw={'height_ratios': (1, 1), 'hspace': 0},
                             layout='constrained')
    dendro_kwargs = {"Z": Z, "labels": [m.replace('PAPI_', '') for m in metrics], "ax": ax, "leaf_font_size": 6,
                     "leaf_rotation": 90}
    if color_threshold is not None:
        dendro_kwargs["color_threshold"] = color_threshold
    dendro = dendrogram(**dendro_kwargs)
    for label in ax.get_yticklabels():
        label.set_fontfamily('monospace')

    # Build rotated heatmap in dendrogram's leaf order (rows=kernels, cols=metrics)
    reordered_metrics = [m for m in metrics if m.replace('PAPI_', '') in dendro["ivl"]]
    reordered_metrics.sort(key=lambda m: list(dendro["ivl"]).index(m.replace('PAPI_', '')))
    heat_grid = numpy.array([[deviations_by_metric[m][kernels.index(k)] if k in kernels else numpy.nan
                              for m in reordered_metrics] for k in kernels])
    bound = numpy.nanmax(numpy.abs(heat_grid))
    # im = ax_heat.imshow(heat_grid, cmap="RdBu_r", vmin=-bound, vmax=bound, aspect="auto")
    # ax_heat.set_xticks(range(len(reordered_metrics)), labels=[m.replace('PAPI_', '') for m in reordered_metrics],
    #                    rotation=90, fontsize=5, fontfamily="monospace")
    # ax_heat.set_yticks(range(len(kernels)), labels=kernels, fontsize=5)
    # ax_heat.set_ylabel("Kernel", fontsize=7)
    # fig.colorbar(im, ax=ax_heat, label="Deviation", orientation='horizontal', pad=0.1, aspect=30)

    # Build parent map: each leaf and internal node points to its parent merge
    parent = {}
    for row in range(len(Z)):
        a, b = int(Z[row, 0]), int(Z[row, 1])
        parent[a] = len(metrics) + row
        parent[b] = len(metrics) + row

    # Annotate every junction with lowest-MAD metric in subtree, using headroom to decide placement
    display_index = {label: i for i, label in enumerate(dendro["ivl"])}

    fontsize = 6
    # Calculate character width in x-axis data units from font metrics
    fig_dpi = fig.dpi
    x_range = ax.get_xlim()[1] - ax.get_xlim()[0]
    points_to_x_data = (fontsize / 72) * fig_dpi / ax.get_window_extent(fig.canvas.get_renderer()).width * x_range
    char_width_x = points_to_x_data

    # Collect merge x-positions (dendrogram internal lines, not leaves)
    merge_positions = []
    temp_cluster_x = {i: 5 + 10 * display_index[metrics[i].replace('PAPI_', '')] for i in range(len(metrics))}
    for row_idx, (a, b, dist, _count) in enumerate(Z):
        a, b = int(a), int(b)
        merged_id = len(metrics) + row_idx
        x = (temp_cluster_x[a] + temp_cluster_x[b]) / 2
        temp_cluster_x[merged_id] = x
        merge_positions.append(x)

    # Reset for actual annotation pass
    cluster_x = {i: 5 + 10 * display_index[metrics[i].replace('PAPI_', '')] for i in range(len(metrics))}
    cluster_leaves = {i: {i} for i in range(len(metrics))}

    for row_idx, (a, b, dist, _count) in enumerate(Z):
        a, b = int(a), int(b)
        merged_id = len(metrics) + row_idx
        x = merge_positions[row_idx]
        leaves = cluster_leaves[a] | cluster_leaves[b]
        cluster_x[merged_id] = x
        cluster_leaves[merged_id] = leaves

        rep = min((metrics[i] for i in leaves), key=lambda m: metric_to_mad[m]).replace('PAPI_', '')

        # Calculate vertical headroom: distance to parent merge (infinite if at root)
        if merged_id in parent:
            parent_idx = parent[merged_id] - len(metrics)
            headroom = Z[parent_idx, 2] - dist
        else:
            headroom = float('inf')

        # Calculate cluster width from leaf positions
        leaf_positions = [5 + 10 * display_index[metrics[i].replace('PAPI_', '')] for i in leaves]
        cluster_left = min(leaf_positions)
        cluster_right = max(leaf_positions)
        cluster_width = cluster_right - cluster_left if len(leaf_positions) > 1 else 10

        label_width = len(rep) * char_width_x
        label_too_wide = label_width > cluster_width / 2

        # Root node (outermost cluster) is always centered, never rotated
        if headroom == float('inf'):
            ax.text(x, dist + 0.05, rep, ha="center", va="bottom", fontsize=fontsize,
                    color="black", fontfamily="monospace", weight="bold")
        # Rotate if label is wider than half the cluster, or if there's sufficient headroom
        elif label_too_wide:
            # Rotate 90° to save horizontal space
            ax.text(x + 1.5, dist + 0.1, rep, ha="left", rotation=90, va="bottom", fontsize=fontsize,
                    color="black", fontfamily="monospace", weight="bold")
        else:
            # All other horizontal labels: left-aligned
            ax.text(x + 1, dist + 0.05, rep, ha="left", va="bottom", fontsize=fontsize,
                    color="black", fontfamily="monospace", weight="bold")
    # ax.set_xlabel("Metric")
    ax.set_ylabel("Distance", fontsize=8)
    # ax.set_ylim(0,11.4)
    # ax.set_yticks(range(0, 12))
    # ax.set_yticklabels([str(i) if i % 2 == 0 else '' for i in range(0, 12)],fontsize=7)
    ax.grid(True, 'major', axis="y", color='lightgrey', linestyle='-', linewidth=0.5)
    # ax.set_title(
    #     "Metric Clustering by Deviation Pattern Across Kernels\n"
    #     "(annotated by counter with lowest mean absolute deviation per cluster)"
    # )
    # fig.tight_layout()
    fig.show()
    fig.savefig(out_path, bbox_inches="tight")
    print(f"wrote {out_path}")

    # Print cluster summary
    print("\nCluster representatives (lowest MAD per cluster):")
    for cluster_id in sorted(numpy.unique(clusters), key=lambda c: metric_to_mad[cluster_reps[c]]):
        rep = cluster_reps[cluster_id]
        print(f"  Cluster {cluster_id}: {rep} (MAD={metric_to_mad[rep]:.3f})")

    return {int(cluster_id): (rep, float(metric_to_mad[rep])) for cluster_id, rep in cluster_reps.items()}


def cluster_metrics_by_deviation2(deviations_by_metric, kernels, out_path, n_clusters=None):
    """Cluster metrics based on similarity of their deviation patterns across kernels.

    Builds a matrix where each row is a metric and each column is a kernel.
    Metrics are clustered by Euclidean distance in deviation space.
    """
    # Sort metrics by mean absolute deviation (lowest first)
    metrics = sorted(
        deviations_by_metric.keys(),
        key=lambda m: numpy.mean(numpy.abs(deviations_by_metric[m]))
    )

    # Build matrix: rows = metrics, cols = kernels
    matrix = []
    for metric in metrics:
        row = [deviations_by_metric[metric][kernels.index(k)] if k in kernels else numpy.nan
               for k in kernels]
        matrix.append(row)
    matrix = numpy.array(matrix)

    # Normalize each metric's deviation vector
    scaler = StandardScaler()
    matrix_norm = scaler.fit_transform(matrix)

    # Hierarchical clustering
    distances = pdist(matrix_norm, metric="euclidean")
    Z = linkage(distances, method="weighted")

    # Cluster assignment
    if n_clusters is not None:
        # Pick the distance threshold that cuts the tree into exactly n_clusters
        # groups, so scipy's dendrogram coloring (which also cuts by distance)
        # matches these clusters one-for-one.
        heights = numpy.sort(Z[:, 2])
        n_merges = len(heights)
        k = min(max(n_clusters, 1), n_merges + 1)
        if k >= n_merges + 1:
            color_threshold = 0.0
        elif k <= 1:
            color_threshold = heights[-1] * 1.01
        else:
            color_threshold = (heights[n_merges - k] + heights[n_merges - k + 1]) / 2
        clusters = fcluster(Z, t=color_threshold, criterion="distance")
    else:
        # Auto-detect using distance threshold
        clusters = fcluster(Z, t=max(Z[:, 2]) * 0.5, criterion="distance")
        color_threshold = max(Z[:, 2]) * 0.5
    metric_to_mad = {m: numpy.mean(numpy.abs(deviations_by_metric[m])) for m in metrics}

    # Find best (lowest MAD) metric in each cluster
    cluster_reps = {}
    for cluster_id in numpy.unique(clusters):
        cluster_metrics = [metrics[i] for i, c in enumerate(clusters) if c == cluster_id]
        best = min(cluster_metrics, key=lambda m: metric_to_mad[m])
        cluster_reps[cluster_id] = best

    # Plot dendrogram with heatmap of clustered data
    fig, (ax, ax_heat) = plt.subplots(2, 1, figsize=(18.1374, 10, 'cm'),
                                      gridspec_kw={'height_ratios': (1, 0.6), 'hspace': 0.15},
                                      layout='constrained')
    dendro_kwargs = {"Z": Z, "labels": [m.replace('PAPI_', '') for m in metrics], "ax": ax, "leaf_font_size": 7,
                     "leaf_rotation": 90}
    if color_threshold is not None:
        dendro_kwargs["color_threshold"] = color_threshold
    dendro = dendrogram(**dendro_kwargs)
    for label in ax.get_yticklabels():
        label.set_fontfamily('monospace')

    # Build rotated heatmap in dendrogram's leaf order (rows=kernels, cols=metrics)
    reordered_metrics = [m for m in metrics if m.replace('PAPI_', '') in dendro["ivl"]]
    reordered_metrics.sort(key=lambda m: list(dendro["ivl"]).index(m.replace('PAPI_', '')))
    heat_grid = numpy.array([[deviations_by_metric[m][kernels.index(k)] if k in kernels else numpy.nan
                              for m in reordered_metrics] for k in kernels])
    bound = numpy.nanmax(numpy.abs(heat_grid))
    im = ax_heat.imshow(heat_grid, cmap="RdBu_r", vmin=-bound, vmax=bound, aspect="auto")
    ax_heat.set_xticks(range(len(reordered_metrics)), labels=[m.replace('PAPI_', '') for m in reordered_metrics],
                       rotation=90, fontsize=6, fontfamily="monospace")
    ax_heat.set_yticks(range(len(kernels)), labels=kernels, fontsize=6)
    ax_heat.set_ylabel("Kernel", fontsize=8)
    fig.colorbar(im, ax=ax_heat, label="Deviation", orientation='horizontal', pad=0.1, aspect=30)

    # Annotate every junction (each row of Z is one merge) with the lowest-MAD
    # metric among the leaves it joins. Leaf x-positions follow scipy's own
    # convention (5 + 10*display_index); a merge's x is the mean of its two
    # children's x, its y is just the linkage distance.
    display_index = {label: i for i, label in enumerate(dendro["ivl"])}
    cluster_x = {i: 5 + 10 * display_index[metrics[i].replace('PAPI_', '')] for i in range(len(metrics))}
    cluster_leaves = {i: {i} for i in range(len(metrics))}

    for row_idx, (a, b, dist, _count) in enumerate(Z):
        a, b = int(a), int(b)
        merged_id = len(metrics) + row_idx
        x = (cluster_x[a] + cluster_x[b]) / 2
        leaves = cluster_leaves[a] | cluster_leaves[b]
        cluster_x[merged_id] = x
        cluster_leaves[merged_id] = leaves

        rep = min((metrics[i] for i in leaves), key=lambda m: metric_to_mad[m]).replace('PAPI_', '')
        if dist < 5.5:
            ax.text(x + 1, dist + 0.1, rep, ha="left", rotation=90, va="bottom", fontsize=7, color="black",
                    fontfamily="monospace", weight="bold")
        elif dist > 10:
            ax.text(x, dist + 0.05, rep, ha="center", va="bottom", fontsize=7, color="black",
                    fontfamily="monospace", weight="bold")
        else:
            ax.text(x + 0.7, dist + 0.05, rep, ha="left", va="bottom", fontsize=7, color="black",
                    fontfamily="monospace", weight="bold")
    # ax.set_xlabel("Metric")
    ax.set_ylabel("Distance", fontsize=8)
    ax.set_ylim(0, 11.4)
    ax.set_yticks(range(0, 12))
    ax.set_yticklabels([str(i) if i % 2 == 0 else '' for i in range(0, 12)], fontsize=7)
    ax.grid(True, 'major', axis="y", color='lightgrey', linestyle='-', linewidth=0.5)
    # ax.set_title(
    #     "Metric Clustering by Deviation Pattern Across Kernels\n"
    #     "(annotated by counter with lowest mean absolute deviation per cluster)"
    # )
    # fig.tight_layout()
    fig.show()
    fig.savefig(out_path, bbox_inches="tight")
    print(f"wrote {out_path}")

    # Print cluster summary
    print("\nCluster representatives (lowest MAD per cluster):")
    for cluster_id in sorted(numpy.unique(clusters), key=lambda c: metric_to_mad[cluster_reps[c]]):
        rep = cluster_reps[cluster_id]
        print(f"  Cluster {cluster_id}: {rep} (MAD={metric_to_mad[rep]:.3f})")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=HERE,
        help="Directory containing results_extrap.json to read, and to write "
             "deviations.csv/deviation_by_metric.png/exponent_accuracy.png/"
             "deviation_heatmap.png into (default: this script's own directory)",
    )
    parser.add_argument(
        "--metrics",
        nargs="+",
        metavar="METRIC",
        help="restrict to these metric names (default: all found in results_extrap.json)",
    )
    parser.add_argument(
        "--no-heatmap",
        action="store_false",
        dest="heatmap",
        help="disable export of kernel x metric heatmap (deviation_heatmap.png)",
    )
    parser.add_argument(
        "--plot-style",
        choices=["violin", "box"],
        default="box",
        help="deviation-by-metric plot style (default: box)",
    )
    parser.add_argument(
        "--cluster-count",
        type=int,
        default=None,
        help="number of clusters for dendrogram (default: auto-detect from distance threshold)",
    )
    parser.add_argument(
        "--exclude-hit-miss",
        action="store_true",
        help="exclude hit/miss counters",
    )
    parser.add_argument(
        "--exclude-counters",
        nargs="+",
        metavar="COUNTER",
        help="exclude these counter names from analysis",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    results_dir = args.results_dir
    truth = load_ground_truth(HERE / "GROUND_TRUTH.txt")

    experiment = JsonFileReader().read_experiment(str(results_dir / "results_extrap.json"))
    mg = ModelGenerator(experiment)
    mg.modeler.negative_coefficients = False
    # Extra-P's default polynomial exponents only go up to n^3; doitgen etc. need n^4.
    mg.modeler.poly_exponents = "13/4,10/3,7/2,11/3,15/4,4"
    mg.modeler.retain_default_exponents = True
    mg.model_all()
    models = experiment.modelers[0].models

    rows = {}
    for (callpath, metric), model in models.items():
        kernel = callpath.name
        if kernel not in truth:
            continue
        if args.metrics and metric.name not in args.metrics:
            continue
        if metric.name.startswith("wall_clock_seconds"):
            continue
        # Filter out cache hit/miss metrics
        if args.exclude_hit_miss and is_cache_counter and is_cache_counter(metric.name):
            continue
        # Filter out explicitly excluded counters
        if args.exclude_counters and (
                metric.name in args.exclude_counters or metric.name.replace('PAPI_', '') in args.exclude_counters):
            continue
        predicted = leading_exponent(model.hypothesis.function)
        expected = truth[kernel]
        rows[(kernel, metric.name)] = (expected, predicted, predicted - expected)

    if not rows:
        raise SystemExit(f"no models matched --metrics {args.metrics}")

    deviations = {key: deviation for key, (_, _, deviation) in rows.items()}

    deviations_by_metric = defaultdict(list)
    for (kernel, metric_name), deviation in deviations.items():
        deviations_by_metric[metric_name].append(deviation)

    summary = sorted(
        (
            (m, sum(abs(d) for d in ds) / len(ds), len(ds))
            for m, ds in deviations_by_metric.items()
        ),
        key=lambda r: r[1],
    )

    # Apply 0.5 MAD cutoff to summary output
    summary_cutoff_idx = next((i - 1 for i, (_, mean_abs_dev, _) in enumerate(summary) if mean_abs_dev > 0.5), len(summary) - 1)

    print(f"{'metric':<28}{'mean |deviation|':>18}{'n kernels':>12}")
    for i, (metric, mean_abs_dev, n) in enumerate(summary):
        if i > summary_cutoff_idx:
            break
        print(f"{metric:<28}{mean_abs_dev:>18.3f}{n:>12}")

    # Metrics at or above the cutoff for output
    summary_for_output = summary[:summary_cutoff_idx + 1]

    # Save ranking by mean absolute deviation for use by redundancy elimination
    ranking_data = [
        {"metric": metric, "mean_abs_deviation": float(mean_abs_dev), "n_kernels": n}
        for metric, mean_abs_dev, n in summary_for_output
    ]
    ranking_file = results_dir / "metric_ranking_by_deviation.json"
    with open(ranking_file, "w") as f:
        json.dump(ranking_data, f, indent=2)
    print(f"wrote {ranking_file}")

    metric_to_mad = {metric: mean_abs_dev for metric, mean_abs_dev, _ in summary}
    rule_based_selection = select_rule_based(metric_to_mad)
    print_rule_based_selection(rule_based_selection)

    # corr_threshold = 0.7
    # # Detect redundancy across all metrics (full correlation analysis with threshold=0.0)
    # redundant_pairs_all, selected_metrics = find_redundant_metrics(rows, summary_for_output, threshold=corr_threshold)
    # # Filter pairs and selection to cutoff metrics
    # cutoff_metric_set = {m for m, _, _ in summary_for_output}
    # redundant_pairs = [p for p in redundant_pairs_all if
    #                    abs(p[2]) >= corr_threshold and p[0] in cutoff_metric_set and p[1] in cutoff_metric_set]
    #
    # print_redundant_metrics(redundant_pairs, corr_threshold)
    # if selected_metrics:
    #     print(f"\nSelected metrics ({len(selected_metrics)} of {len(summary_for_output)}): {selected_metrics}")
    #     selected_file = results_dir / "selected_metrics.json"
    #     with open(selected_file, "w") as f:
    #         json.dump(selected_metrics, f, indent=2)
    #     print(f"wrote {selected_file}")
    #     plot_redundancy_heatmap(redundant_pairs_all, [m for m, _, _ in summary], results_dir / "redundancy_heatmap.png")

    plot_by_metric(
        deviations_by_metric, results_dir / "deviation_by_metric.png", args.plot_style
    )
    plot_accuracy(deviations_by_metric, results_dir / "exponent_accuracy.png")
    write_csv(rows, results_dir / "deviations.csv")

    kernels = sorted({k for k, _ in deviations})

    if args.heatmap:
        metrics = sorted(
            deviations_by_metric,
            key=lambda m: numpy.mean(numpy.abs(deviations_by_metric[m])),
        )
        plot_heatmap(deviations, kernels, metrics, results_dir / "deviation_heatmap.pdf", deviations_by_metric)

    # Clustering produces the clustered counter set independently of the
    # heatmap plot, so --no-heatmap doesn't also drop it.
    cutoff_metrics = {m for m, _, _ in summary_for_output if m != 'time'}
    deviations_by_metric_cutoff = {m: v for m, v in deviations_by_metric.items() if m in cutoff_metrics}
    cluster_reps = cluster_metrics_by_deviation(deviations_by_metric_cutoff, kernels, results_dir / "metric_clustering.pdf",
                                                n_clusters=args.cluster_count)

    selected_file = results_dir / "selected_counters.json"
    with open(selected_file, "w") as f:
        json.dump(
            {
                "rule_based": {category: {"counter": counter, "mean_abs_deviation": mad}
                                for category, (counter, mad) in rule_based_selection.items()},
                "clustered": {str(cluster_id): {"counter": counter, "mean_abs_deviation": mad}
                               for cluster_id, (counter, mad) in cluster_reps.items()},
            },
            f, indent=2,
        )
    print(f"wrote {selected_file}")


if __name__ == "__main__":
    main()
