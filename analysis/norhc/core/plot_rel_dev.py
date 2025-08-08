# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import sys
import os
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import copy

import norhc.helpers.util as util
import norhc.core.score as scr

from matplotlib import pyplot as plt
from matplotlib import ticker
import numpy as np
import numpy.ma as ma
from tqdm import tqdm


class plot_settings:
    def __init__(self):
        self.extended_zero_area = 0.5
        self.plot_mode = "sum"
        self.bin_spread = 20
        self.n_bands = 1
        self.font_size = None
        self.plot_width = 10
        self.plot_height = 6
        self.deviation_cutoff = -1
        self.sorted = False
        self.split_after = 0

        self.selection = util.data_selection()


class cached_plot:
    def __init__(
        self,
        info: util.measurement_info,
        xs,
        ys,
        deviation_score,
        contributions,
        max_y,
        max_deviation,
        color,
    ):
        self.info = info
        self.xs = xs
        self.ys = ys
        self.contributions = contributions  # These contributions represent the reduced contribution bins for plotting
        self.max_contribution = np.max(contributions)
        self.max_y = max_y
        self.max_deviation = max_deviation
        self.color = color
        self.deviation_score = deviation_score


# returns the appropriate value accumulation function for a plotting mode
def get_accumulator(mode: str):
    return {"max": np.maximum, "sum": np.add}[mode]


# Sets up the general axis property for an individual plot.
# TODO: Some way of controlling which experiment dimension controls which plotting dimension would be nice.
def setup_chart(ax, settings: plot_settings, p: util.measurement_info, y_label, y_ticks):
    # Set the x-axis to its maximum length for now. It may be shortened later on.
    ax.set_xlim(-settings.extended_zero_area, 1000)

    # The x-scale starts being logarithmic at 100
    ax.set_xscale("symlog", linthresh=100, linscale=3)
    # An additional linear locator is employed explicitly before the logarithmic scale starts.
    # Not doing so would lead to an empty scale before 100.
    ax.xaxis.set_major_locator(
        util.SplitLocator(
            ticker.MultipleLocator(20),
            ticker.SymmetricalLogLocator(base=10, linthresh=100),
            100,
        )
    )

    # Don't use scientific notation for values below 100
    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())

    # Only show major ticks on the x-axis since the minor ones are undefined
    ax.xaxis.grid(True, which="major", alpha=0.5)
    ax.xaxis.grid(False, which="minor")
    ax.set_xlabel("Relative deviation [%]")

    # The "y-gridlines" act as the separators for noisy and noiseless measurements for each plot
    ax.yaxis.grid(True, which="major", alpha=1)
    ax.set_ylabel(y_label)

    # Right y-axis with system name
    ax2 = ax.twinx()
    ax2.set_ylabel(p.system)
    # No ticks on the right axis
    ax2.tick_params(axis="y", which="both", right=False, labelright=False)

    # Labels for ticks on the y-axis
    ax.set_yticks(np.arange(0, len(y_ticks), 1))
    ax.set_yticklabels(y_ticks)


def is_noiseless(noise_pattern: str):
    return noise_pattern == "NO_NOISE"


# Calculates all data required or plotting.
# This makes plotting the same data multiple times more efficient.
def prepare_plot(settings: plot_settings, p: util.measurement_info):
    # TODO: Show progress
    if settings.font_size:
        plt.rcParams.update({"font.size": settings.font_size})
    visits, contributions, deviations = scr.get_filtered_data(p, settings.selection)
    deviation_score = scr.deviation_score_from_data(visits, contributions, deviations, settings.selection)

    accumulate = get_accumulator(settings.plot_mode)
    # Same colors as in the paper
    colors = ["#1f78b4", "#e47025", "#33a02c"]
    # Noisy measurements point down, clean ones up.
    direction = -1
    color = colors[1]
    if is_noiseless(p.noise_pattern):
        direction = 1
        color = colors[0]

    xs = []
    max_contribution = 100  # np.max(plt_inf.contributions)
    max_deviation = 0

    # The bands are slightly bigger than they have to be so that the maximum contribution doesn't start its own band
    contrib_bin_size = max_contribution / settings.n_bands + 0.0000001
    band_contributions = [max_contribution]
    if settings.n_bands > 1:
        # contributions = np.zeros(color_bands)
        band_contributions = np.linspace(0.0, max_contribution, settings.n_bands)

    # Bin widths increase with higher deviations.
    bins = np.concatenate(
        [
            np.arange(0, 100, 0.25),
            np.arange(101, 300 + settings.bin_spread, 1),
            np.arange(300 + settings.bin_spread, 1000 + settings.bin_spread, 10),
        ]
    )

    hist_size = len(bins) - settings.bin_spread
    xs = bins[0:hist_size]

    ys = [np.zeros(0)] * settings.n_bands

    for vis, contribution, deviation in zip(visits, contributions, deviations):
        if vis < settings.selection.visit_threshold or contribution < settings.selection.contrib_threshold:
            continue

        if settings.deviation_cutoff > 0:
            deviation = list(filter(lambda d: d <= settings.deviation_cutoff, deviation))
        max_deviation = max(max_deviation, np.max(deviation))

        hst, _ = np.histogram(deviation, bins=bins)
        hst = np.convolve(
            hst,
            np.ones(settings.bin_spread) / settings.bin_spread,
            "valid",
        )

        band = int(contribution // contrib_bin_size)
        # contributions[band] += contribution
        if len(ys[band]) == 0:
            ys[band] = hst
        else:
            ys[band] = accumulate(ys[band], hst * contribution)

        deviation = []

    max_y = 0
    for i in range(len(ys)):
        if len(ys[i]) == 0:
            band_contributions[i] = 0
            continue

        max_y = max(max_y, np.max(ys[i]))

        ys[i] *= direction

    return cached_plot(p, xs, ys, deviation_score, band_contributions, max_y, max_deviation, color)


def plot(ax: plt.Axes, c1: cached_plot, c2: cached_plot, settings: plot_settings):
    if settings.font_size:
        plt.rcParams.update({"font.size": settings.font_size})
    max_y = max(c1.max_y, c2.max_y)
    for cache in [c1, c2]:
        for contribution, y in zip(cache.contributions, cache.ys):
            if len(y) == 0:
                continue

            counter_idx = cache.info.counter_index

            # max_contribution = 100
            max_contribution = cache.max_contribution
            alpha = np.interp(contribution, [0, max_contribution], [0.1, 0.8])
            # Y values are normed to 0.5 so that each graph is exactly 1 high
            ax.fill_between(
                cache.xs,
                counter_idx + y / (2 * max_y),
                counter_idx,
                color=cache.color,
                alpha=alpha,
                linewidth=0,
            )

            # Plot the first value again for the extended zero area
            ax.fill_between(
                [-settings.extended_zero_area, 0],
                counter_idx + [y[0], y[0]] / (2 * max_y),
                counter_idx,
                color=cache.color,
                alpha=alpha,
                linewidth=0,
            )

            direction = 1 if is_noiseless(cache.info.noise_pattern) else -1
            ax.vlines(
                cache.deviation_score,
                counter_idx,
                counter_idx + (0.5 * direction),
                colors="black",
            )


def plot_all(experiment_dir, settings: plot_settings):
    plt_infs = util.available_measurements(experiment_dir, settings.selection)

    unsorted_benchmarks = set()
    unsorted_systems = set()
    unsorted_noise = set()
    unsorted_counters = set()

    for p in plt_infs.values():
        unsorted_benchmarks.add(p.benchmark)
        unsorted_systems.add(p.system)
        # NO_NOISE does not have a dedicated plot and should therefore not occupy any space.
        if p.noise_pattern != "NO_NOISE":
            unsorted_noise.add(p.noise_pattern)
        unsorted_counters.add(p.counter)

    # These establish global orderings within each figure
    benchmark_indices = util.sorted_index_map(unsorted_benchmarks)
    system_indices = util.sorted_index_map(unsorted_systems)
    noise_indices = util.sorted_index_map(unsorted_noise)
    counter_indices = {}

    if settings.sorted:
        sel = copy(settings.selection)
        sel.lump_noise = True
        sel.lump_params = True
        sel.lump_systems = True
        sel.lump_resources = True
        sel.lump_benchmarks = True

        lumped_infs = util.available_measurements(experiment_dir, sel)
        scores = {}
        for inf in tqdm(lumped_infs.values(), "Scoring"):
            if inf.noise_pattern == "NO_NOISE":
                continue
            key = inf.key()
            scores[key] = scr.score(inf, lumped_infs[inf.noiseless_key()], sel)
        sgp = scr.score_group(scores)
        scores = {c: s for c, s in scores.items() if not np.isinf(s.rel_resilience)}

        sort_crit = lambda it: it[1].rel_resilience
        access = lambda it: lumped_infs[it[0]].counter
        counter_indices = util.sorted_index_map(scores.items(), key=sort_crit, reverse=False, elem_transform=access)

    else:
        counter_indices = util.sorted_index_map(unsorted_counters)

    cached_plots = {}

    # Globally largest deviation. Used for determining x-axis length
    max_deviation = 0

    def prepare_plot_wrapper(p: util.measurement_info):
        plt_cache = prepare_plot(settings, p)
        return (p.system, p.benchmark, p.counter, p.noise_pattern), plt_cache

    # Calculate plots for measurements without noise
    with ThreadPoolExecutor() as exec:
        futures = []
        for p in plt_infs.values():
            futures.append(exec.submit(prepare_plot_wrapper, p))
        for f in tqdm(futures, desc="Preparing"):
            k, v = f.result()
            max_deviation = max(max_deviation, v.max_deviation)
            cached_plots[k] = v

    splitting_enabled = settings.split_after > 0
    split_after = settings.split_after if splitting_enabled else 1e9

    for p in plt_infs.values():
        if p.counter not in counter_indices:
            continue
        p.counter_index = counter_indices[p.counter] % split_after

    plot_rows = len(noise_indices)
    plot_cols = len(benchmark_indices)
    vslack = 0
    fig_width = settings.plot_width * plot_cols
    figs = {}
    axes = {}
    n_parts = int(len(counter_indices) / split_after)

    for p in tqdm(plt_infs.values(), desc="Plotting"):
        if p.counter not in counter_indices:
            continue
        part_idx = int(counter_indices[p.counter] / split_after)
        counter_rows = split_after if part_idx < n_parts else len(counter_indices) % split_after
        fig_height = settings.plot_height * (plot_rows * counter_rows) + vslack
        fig_id = (p.system, part_idx)
        ax_id = (p.system, p.benchmark, p.noise_pattern, part_idx)
        # Noiseless plots are drawn each time the corresponding noisy plot is drawn and don't need their own plots.
        if p.noise_pattern == "NO_NOISE":
            continue
        # A figure is created for each new system.
        if fig_id not in figs:
            figs[fig_id] = plt.figure(
                f"{p.system}_{part_idx}",
                figsize=(
                    fig_width,
                    fig_height,
                ),
            )
        fig = figs[fig_id]

        # A subplot is created for each system x benchmark x noise_pattern combination.
        # All counters for such a combination are placed within the same subplot.
        if ax_id not in axes:
            width = plot_cols
            x = benchmark_indices[p.benchmark]
            y = noise_indices[p.noise_pattern]
            ax = fig.add_subplot(
                plot_rows,
                plot_cols,
                y * width + x + 1,
            )

            counter_names = [name for name, idx in counter_indices.items() if part_idx == int(idx / split_after)]
            setup_chart(ax, settings, p, p.noise_pattern, counter_names)
            if max_deviation <= 100:
                ax.set_xlim(-settings.extended_zero_area, 100)
            axes[ax_id] = ax

        # plot both noisy and clean measurements.
        plot(
            axes[ax_id],
            cached_plots[(p.system, p.benchmark, p.counter, p.noise_pattern)],
            cached_plots[(p.system, p.benchmark, p.counter, "NO_NOISE")],
            settings,
        )

    # Add benchmark labels
    for key, ax in axes.items():
        # Only add a benchmark label at the very top
        if noise_indices[key[2]] != 0:
            continue
        bb = ax.bbox.get_points()
        axx, axy, axw, axh = (
            bb[0][0],
            bb[0][1],
            bb[1][0] - bb[0][0],
            bb[1][1] - bb[0][1],
        )
        ax.annotate(
            key[1],
            xy=(0.5, 1.0 + ((settings.font_size * 2) / axh)),
            xycoords="axes fraction",
            horizontalalignment="center",
            verticalalignment="top",
            fontsize=settings.font_size,
        )

    # Sanitize format and save plots.
    # The format probably still turns out weird because there is so much to draw
    # but it should be fine in the exported plots.
    for fig_id, fig in figs.items():
        fig.set_figwidth(settings.plot_width * plot_cols)
        fig.tight_layout()
        system = fig_id[0]
        part = fig_id[1]
        fig.savefig(f"{system}_{part}.svg", bbox_inches="tight")


def main():
    if len(sys.argv) < 2:
        print("Usage: norhc_plot" "DIR")
        exit(1)

    parser = argparse.ArgumentParser()

    parser.add_argument("experiment_root")
    parser.add_argument("-m", "--mode", dest="plot_mode", action="store", default="sum")
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
    parser.add_argument("-b", "--bands", type=int, dest="n_bands", action="store", default=0)
    parser.add_argument("--benchmark", type=str, action="store", default="")
    parser.add_argument("--system", type=str, action="store", default="")
    parser.add_argument("--noise", type=str, action="store", default="")
    parser.add_argument("--counter", type=str, action="store", default="")

    parser.add_argument("-g", "--groupings", type=str, action="store", default="res,par")

    parser.add_argument("--fontsize", type=int, action="store", default=30)
    parser.add_argument("--width", type=float, action="store", default=10)
    parser.add_argument("--height", type=float, action="store", default=6)

    parser.add_argument("--deviation_cutoff", type=int, action="store", default=-1)

    parser.add_argument(
        "--sorted",
        action="store_true",
    )

    # More than a million plots are unlikely.
    parser.add_argument("--split", type=int, action="store", default=0)

    args = parser.parse_args()

    settings = plot_settings()

    settings.plot_mode = args.plot_mode
    settings.selection.contrib_threshold = args.contribution
    settings.selection.visit_threshold = args.visits

    settings.n_bands = args.n_bands
    if settings.n_bands <= 0:
        settings.n_bands = 1 if settings.plot_mode == "sum" else 10000

    settings.selection.filter = util.experiment_filter(
        args.benchmark, args.system, args.noise, args.counter.replace("PAPI_", "")
    )

    settings.font_size = args.fontsize
    settings.plot_width = args.width
    settings.plot_height = args.height

    for gr in args.groupings.split(","):
        group_all = gr.startswith("a")
        settings.selection.lump_benchmarks |= group_all | gr.startswith("b")
        settings.selection.lump_systems |= group_all | gr.startswith("s")
        settings.selection.lump_noise |= group_all | gr.startswith("n")
        settings.selection.lump_params |= group_all | gr.startswith("p")
        settings.selection.lump_resources |= group_all | gr.startswith("r")

    settings.deviation_cutoff = args.deviation_cutoff
    settings.sorted = args.sorted
    settings.split_after = args.split

    plot_all(os.path.join(args.experiment_root, "result", ".deviations"), settings)
    plt.show()


if __name__ == "__main__":
    main()
