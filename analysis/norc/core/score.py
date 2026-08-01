# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import numpy as np
import sys
import os
import argparse

from tqdm import tqdm

from norc.helpers.util import (
    data_selection,
    measurement_info,
    available_measurements,
    warn,
    load_measurement,
    write_measurement,
    open_experiment_source,
)

# The (contribution, visit) threshold combos that get re-requested often
# enough (including the CLI default and the GUI's usual "real data" setting) to be worth
# caching in the experiment archive instead of recomputing every time.
CACHEABLE_SELECTIONS = {(0, 0), (0.1, 0), (1, 0), (0, 100), (0.1, 100), (1, 100)}


# Summarized deviation and susceptibility scores
class score:
    def __init__(self, noisy_info, ref_info, selection, tree):
        noisy_data = get_filtered_data(noisy_info, selection, tree)
        ref_data = get_filtered_data(ref_info, selection, tree)
        # Deviation score for noisy measurement
        self.dev_noisy = deviation_score(noisy_info, selection, noisy_data)
        # Deviation score for reference measurement
        self.dev_ref = deviation_score(ref_info, selection, ref_data)
        # Noise susceptibility score
        self.susceptibility = sensitivity_score(noisy_info, ref_info, selection, noisy_data, ref_data)

        self.rel_resilience = -np.inf

    def deviation(self):
        return max(self.dev_noisy, self.dev_ref)


class score_group:
    def __init__(self, scores=None):
        if scores is None:
            scores = {}
        self.scores = scores
        self.update_resilience()

    def put(self, key, scr):
        self.scores[key] = scr
        self.update_resilience()

    def clear(self):
        self.scores = {}

    def update_resilience(self):
        if not self.scores:
            return
        min_deviation = np.inf
        min_susceptibility = np.inf
        max_deviation = 0
        max_susceptibility = 0
        for s in self.scores.values():
            d = s.deviation()
            if np.isinf(s.deviation()):
                continue
            min_deviation = min(min_deviation, d)
            max_deviation = max(max_deviation, d)
            max_susceptibility = max(max_susceptibility, s.susceptibility)
            min_susceptibility = min(min_susceptibility, s.susceptibility)

        if max_deviation == 0 or max_susceptibility == 0:
            return

        min_d_normed = min_deviation / max_deviation
        min_s_normed = min_susceptibility / max_susceptibility
        susc_weight = min(1.0, min_s_normed / min_d_normed) if min_d_normed != 0 else 1.0
        for k, s in self.scores.items():
            if np.isinf(s.deviation()) or np.isinf(s.susceptibility):
                # Infinity indicates missing data and doesn't need handling.
                continue
            d_normed = s.deviation() / max_deviation
            s_normed = s.susceptibility / max_susceptibility
            self.scores[k].rel_resilience = 1.0 / ((1.0 + d_normed) * (1.0 + s_normed * susc_weight))


def deviation_score_from_data(visits, contribution, deviation, selection: data_selection):
    score = 0.0
    # Total contribution of measurements used for the score.
    # Used for scaling to compensate for cutoff loss.
    total_contribution = 0.0
    for vis, contrib, devs in zip(visits, contribution, deviation):
        if vis >= selection.visit_threshold and contrib >= selection.contrib_threshold:
            score += contrib * np.sum(devs) / len(devs)
            total_contribution += contrib

    if total_contribution == 0:
        assert score == 0.0
        return 0.0

    return score / total_contribution


def get_filtered_data(info: measurement_info, selection: data_selection, tree):
    visits = []
    contributions = []
    deviations = []
    for path in info.file_paths:
        measurement = load_measurement(tree, path)
        for callpath in measurement:
            if not selection or (
                    callpath.visits >= selection.visit_threshold and callpath.contribution >= selection.contrib_threshold
            ):
                visits.append(callpath.visits)
                contributions.append(callpath.contribution)
                deviations.append(callpath.deviations)

    return visits, contributions, deviations


def deviation_score(info: measurement_info, selection: data_selection, filtered_data):
    visits, contributions, deviations = filtered_data
    if not deviations:
        warn(f"Missing data for measurement {info.key()}")
        return np.inf
    return deviation_score_from_data(visits, contributions, deviations, selection)


def sensitivity_score(
        noisy_info: measurement_info,
        ref_info: measurement_info,
        selection: data_selection,
        noisy_data,
        ref_data,
):
    noisy_vis, noisy_con, noisy_dev = noisy_data
    ref_vis, ref_con, ref_dev = ref_data

    if not noisy_dev:
        warn(f"Missing data for measurement {noisy_info.key()}")
        return np.inf

    if not ref_dev:
        warn(f"Missing data for measurement {ref_info.key()}")
        return np.inf

    def mu_sigma_sq(dev, con):
        sum = 0.0
        total_contrib = 0.0
        for d, c in zip(dev, con):
            sum += np.sum(d) / len(d) * c
            total_contrib += c
        if total_contrib == 0:
            return 0.0, 0.0
        mu = sum / total_contrib

        sum = 0.0
        for d, c in zip(dev, con):
            sum += np.sum([(x - mu) ** 2 for x in d]) / len(d) * c
        sigma_sq = sum / total_contrib
        return mu, sigma_sq

    mu_noisy, sigma_sq_noisy = mu_sigma_sq(noisy_dev, noisy_con)
    mu_ref, sigma_sq_ref = mu_sigma_sq(ref_dev, ref_con)

    denom = np.sqrt(sigma_sq_noisy + sigma_sq_ref)
    if denom == 0:
        return 0.0 if mu_noisy == mu_ref else np.inf

    return abs(mu_noisy - mu_ref) / denom


def _moving_average(ys, window):
    window = min(window, len(ys))
    if window < 3:
        return ys
    # Edge-padded so it doesn't shift the curve inward or flatten it towards
    # zero at the boundaries.
    pad = window // 2
    padded = np.pad(ys, (pad, pad), mode="edge")
    return np.convolve(padded, np.ones(window) / window, mode="valid")[: len(ys)]


def smooth_curve(values, window=1):
    """Moving-average smooth `values`, e.g. for plotting alongside `find_cutoff`.

    Non-finite entries (`np.inf`) are left untouched and excluded from the
    averaging of their neighbors, matching how `find_cutoff` treats them.
    """
    values = np.asarray(values, dtype=float)
    finite_idx = [i for i, v in enumerate(values) if np.isfinite(v)]
    result = values.copy()
    if len(finite_idx) >= 3:
        result[finite_idx] = _moving_average(values[finite_idx], window)
    return result


def find_cutoff(values, smoothing_window=1):
    """Find the index of the cutoff (knee/elbow) in a sequence of scores.

    Uses the maximum-distance-to-chord method: the cutoff is the point that
    sits furthest above the straight line connecting the first and last
    point, after both axes have been normalized to [0, 1]. This is a
    simple, dependency-free approximation of the Kneedle algorithm (Satopaa
    et al., 2011) that works well for the roughly convex/concave,
    monotonically decreasing resilience curves produced by
    `score_group.scores` once sorted by `rel_resilience`. Restricting to
    points above the chord (rather than the largest distance in either
    direction) also handles S-shaped curves, which bulge below the chord on
    a second, unrelated bend.

    Args:
        values: Sequence of floats, assumed sorted in descending order
            (e.g., `rel_resilience` scores ordered best-to-worst).
            Non-finite entries (`np.inf`, from missing data) are ignored
            when locating the cutoff, but do not shift the indices of the
            remaining values.
        smoothing_window: Size of the moving-average window applied to
            `values` before looking for bends. Keeps small local wiggles
            (noise) from shifting exactly which index gets picked. Set to
            1 to disable.

    Returns:
        Index (0-based, into the original `values`) of the cutoff point.
        Everything at or before this index is considered "before the
        cutoff"; this index itself should typically be included in a
        selection. Returns `len(values) - 1` if fewer than 3 finite values
        are available (nothing to bend), or if all finite values coincide.
    """
    n = len(values)
    finite_idx = [i for i, v in enumerate(values) if np.isfinite(v)]
    if len(finite_idx) < 3:
        return n - 1

    xs = np.array(finite_idx, dtype=float)
    ys = _moving_average(np.array([values[i] for i in finite_idx], dtype=float), smoothing_window)

    # Normalize both axes to [0, 1] so the result does not depend on the
    # absolute scale/units of `values` or on how many points there are.
    x_range = xs.max() - xs.min()
    x_norm = (xs - xs.min()) / x_range if x_range > 0 else np.zeros_like(xs)
    y_range = ys.max() - ys.min()
    y_norm = (ys - ys.min()) / y_range if y_range > 0 else np.zeros_like(ys)

    # Perpendicular distance of each normalized point from the chord
    # connecting the first and last normalized point.
    x0, y0 = x_norm[0], y_norm[0]
    x1, y1 = x_norm[-1], y_norm[-1]
    dx, dy = x1 - x0, y1 - y0
    chord_len = np.hypot(dx, dy)
    if chord_len == 0:
        return n - 1  # all (finite) points coincide

    # Signed distance to the chord: positive means the point sits above the
    # chord, which for a decreasing curve is the classic "elbow" bulge (lots
    # of good items, then a fast drop). S-shaped curves also bulge below the
    # chord on their second bend; that's a real inflection but not the cutoff
    # we want, so it's only used as a fallback for curves that never rise
    # above the chord at all (fully convex, no plateau to speak of).
    cross = (dx * (y_norm - y0) - dy * (x_norm - x0)) / chord_len
    if np.any(cross > 0):
        best = int(np.argmax(cross))
    else:
        best = int(np.argmax(np.abs(cross)))
    return finite_idx[best]


def _test_find_cutoff():
    # Plain concave elbow: the only bulge is above the chord.
    assert find_cutoff([1.0, 0.9, 0.6, 0.2, 0.1, 0.0]) == 1

    # S-curve: flat, steep drop, flat again, steep drop again. That second
    # drop bulges *below* the chord - a real inflection, but not the elbow
    # we want, since it's a plateau-to-plateau step, not "before this most
    # items are still fine". Restricting to the above-chord side picks the
    # first (and only) genuine cutoff instead.
    s_curve = [1.0, 0.98, 0.95, 0.6, 0.3, 0.28, 0.27, 0.1, 0.02, 0.0]
    assert find_cutoff(s_curve) == 1

    # Noisy decreasing curve with a tiny single-point downdraw early on and
    # the real cliff much further along. The downdraw bulges below the
    # chord, so it's excluded on its own merits; smoothing still nudges the
    # exact index picked on the (above-chord) plateau leading into the drop.
    noisy = [1.0, 0.99, 0.98, 0.99, 0.85, 0.99, 0.98, 0.97, 0.96, 0.5, 0.2, 0.0]
    assert find_cutoff(noisy, smoothing_window=1) == 8
    assert find_cutoff(noisy) == 7


def plot_resilience_curve(ax, sorted_counters):
    """Draw the resilience-ranking-with-cutoff plot onto `ax`.

    `sorted_counters` is a list of (key, score) pairs, best-to-worst by
    `rel_resilience` (as produced by `sorted(scores.items(), key=lambda it:
    it[1].rel_resilience, reverse=True)`). Shared by the Ranking tab in the
    GUI and `norc_score --plot` so both show the exact same thing.
    """
    counter_names = [measurement_info.from_key(key).counter for key, _ in sorted_counters]
    resiliences = np.array([sc.rel_resilience for _, sc in sorted_counters], dtype=float)
    ranks = np.arange(1, len(resiliences) + 1)
    finite = np.isfinite(resiliences)

    # Rank (as counter name) on the x axis, resilience on y.
    ax.plot(ranks[finite], resiliences[finite], marker="o", markersize=3)

    if finite.sum() >= 3:
        cutoff_idx = find_cutoff(list(resiliences))
        finite_ranks = ranks[finite]
        finite_resiliences = resiliences[finite]

        # Same smoothing find_cutoff applies before looking for bends - shown
        # so it's clear why the cutoff doesn't sit on a raw wiggle.
        # smoothed = smooth_curve(resiliences)
        # ax.plot(finite_ranks, smoothed[finite], linestyle="-", linewidth=1, label="smoothed")
        # Same chord find_cutoff measures distance-to-selection against: the
        # straight line from the first to the last finite point.
        # ax.plot(
        #     [finite_ranks[0], finite_ranks[-1]],
        #     [finite_resiliences[0], finite_resiliences[-1]],
        #     color="gray",
        #     linestyle=":",
        #     linewidth=1,
        #     label="selection reference line",
        # )
        if np.isfinite(resiliences[cutoff_idx]):
            ax.axvline(ranks[cutoff_idx], color="red", linestyle="--", linewidth=1)
            ax.axhline(resiliences[cutoff_idx], color="red", linestyle="--", linewidth=1)
            ax.annotate(
                f"{resiliences[cutoff_idx]:.2f}",
                (ranks[-1], resiliences[cutoff_idx]),
                textcoords="offset points",
                xytext=(4, 2),
                ha="left",
                fontsize="small",
                color="red",
            )
            ax.plot(ranks[cutoff_idx], resiliences[cutoff_idx], "ro")
            ax.annotate(
                "cutoff",
                (ranks[cutoff_idx], resiliences[cutoff_idx]),
                textcoords="offset points",
                xytext=(6, 6),
                color="red",
            )
        # ax.legend(loc="best", fontsize="small")

    ax.set_xticks(ranks)
    ax.set_xticklabels(counter_names, fontsize="small", rotation=90, family="monospace")
    ax.set_ylim(0, 1)
    ax.set_xlabel("Counter")
    ax.set_ylabel("Resilience score")
    ax.set_title("Counters ranked by resilience")


def print_cli_formatted(scores, selection):
    print(
        "================================================================================================================"
    )
    print(
        f"Ignoring callpaths with contribution < {selection.contrib_threshold}% and visits < {selection.visit_threshold}"
    )
    print(
        "----------------------------------------------------------------------------------------------------------------"
    )

    print("Top Counters for constraints:")

    sorted_items = sorted(scores.items(), key=lambda it: it[1].rel_resilience, reverse=True)
    cutoff_idx = find_cutoff([sc.rel_resilience for _, sc in sorted_items])

    place = 1
    for i, (key, sc) in enumerate(sorted_items):
        info = measurement_info.from_key(key)
        marker = "  <-- cutoff" if i == cutoff_idx else ""
        print(
            f"{place}.\t{info.counter}\tResilience: {sc.rel_resilience:.4f}\tDeviation: {sc.deviation():.4f}%\tSuscept.: {sc.susceptibility:.4f}{marker}"
        )
        place += 1
    print(
        "================================================================================================================"
    )


def print_tabular(scores, selection):
    print("\\begin{table}")
    print("  \\begin{tabular}{lllll}")
    print("    Rank & Counter & Relative Resilience & Deviation & Susceptibility\\\\\\hline")

    cellv = lambda x: "\\(" + ("-" if np.isinf(x) else f"{x:.4f}") + "\\)"

    place = 1
    for key, sc in sorted(scores.items(), key=lambda it: it[1].rel_resilience, reverse=True):
        info = measurement_info.from_key(key)
        counter = info.counter.replace("_", "\\_")
        print(
            f"    {place} & {counter} & {cellv(sc.rel_resilience)} & {cellv(sc.deviation())}\\% & {cellv(sc.susceptibility)} \\\\"
        )
        place += 1
    print("  \\hline\\end{tabular}")
    print(f"  \\caption{{min. contribution: {selection.contrib_threshold}%, min. visits: {selection.visit_threshold}}}")
    print("\\end{table}")


class ScoreComputationCancelled(Exception):
    """Raised from a `compute_scores` progress_callback to abort the computation."""


def _scores_cache_path(tree, selection):
    return os.path.join(
        tree.root, "result", ".scores", f"c{selection.contrib_threshold}_v{selection.visit_threshold}.pickle"
    )


def compute_scores(experiment_root, selection, progress_callback=None):
    """Compute resilience scores for `experiment_root`.

    `progress_callback`, when given, is called as `progress_callback(done, total)`
    before each measurement is scored. It may raise `ScoreComputationCancelled`
    to abort early (e.g. from a GUI cancel button).

    For the common threshold combos in `CACHEABLE_SELECTIONS`, the result is
    cached in the experiment archive (`result/.scores/`) so re-opening the
    same experiment doesn't redo the (expensive) scoring pass.
    """
    with open_experiment_source(experiment_root) as tree:
        cacheable = (selection.contrib_threshold, selection.visit_threshold) in CACHEABLE_SELECTIONS
        cache_path = _scores_cache_path(tree, selection)

        if cacheable and tree.exists(cache_path):
            cached = load_measurement(tree, cache_path)
            if cached is not None:
                return cached

        deviation_dir = os.path.join(tree.root, "result", ".deviations")

        noisy = {}
        ref = {}
        for info in available_measurements(tree, deviation_dir, selection).values():
            key = info.key()
            if info.noise_pattern == "NO_NOISE":
                ref[key] = info
            else:
                noisy[key] = info

        keys = list(noisy.keys())
        scores = {}
        for i, key in enumerate(tqdm(keys) if progress_callback is None else keys):
            if progress_callback is not None:
                progress_callback(i, len(keys))
            info_ref = measurement_info.from_key(key)
            scores[key] = score(noisy[key], ref[info_ref.noiseless_key()], selection, tree)

        sgp = score_group(scores)

        if cacheable:
            write_measurement(tree, cache_path, sgp)

        return sgp


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("experiment_root")
    parser.add_argument(
        "-c",
        "--contribution",
        action="store",
        type=float,
        default=0,
    )
    parser.add_argument(
        "-v",
        "--visits",
        action="store",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--tex",
        action="store_true",
    )
    parser.add_argument(
        "--plot",
        action="store",
        nargs="?",
        const="-",
        default=None,
        metavar="FILE",
        help="Show the resilience/cutoff plot (same as the GUI's Ranking tab). "
             "With a FILE argument, save it there instead of opening a window.",
    )

    args = parser.parse_args()

    selection = data_selection()
    selection.lump_benchmarks = True
    selection.lump_noise = True
    selection.lump_params = True
    selection.lump_resources = True
    selection.lump_systems = True
    selection.contrib_threshold = args.contribution
    selection.visit_threshold = args.visits

    sgp = compute_scores(args.experiment_root, selection)

    if args.tex:
        print_tabular(sgp.scores, selection)
    else:
        print_cli_formatted(sgp.scores, selection)

    if args.plot is not None:
        import matplotlib.pyplot as plt

        sorted_counters = sorted(sgp.scores.items(), key=lambda it: it[1].rel_resilience, reverse=True)
        fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
        plot_resilience_curve(ax, sorted_counters)

        if args.plot == "-":
            plt.show()
        else:
            fig.savefig(args.plot)


if __name__ == "__main__":
    main()
