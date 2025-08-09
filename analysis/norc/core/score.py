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

from norc.helpers.util import data_selection, measurement_info, available_measurements, warn, load_measurement


# Summarized deviation and susceptibility scores
class score:
    def __init__(self, noisy_info, ref_info, selection):
        noisy_data = get_filtered_data(noisy_info, selection)
        ref_data = get_filtered_data(ref_info, selection)
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

        min_d_normed = min_deviation / max_deviation
        min_s_normed = min_susceptibility / max_susceptibility
        susc_weight = min(1.0, min_s_normed / min_d_normed)
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


def get_filtered_data(info: measurement_info, selection: data_selection):
    visits = []
    contributions = []
    deviations = []
    for path in info.file_paths:
        measurement = load_measurement(path)
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
        mu = sum / total_contrib

        sum = 0.0
        for d, c in zip(dev, con):
            sum += np.sum([(x - mu) ** 2 for x in d]) / len(d) * c
        sigma_sq = sum / total_contrib
        return mu, sigma_sq

    mu_noisy, sigma_sq_noisy = mu_sigma_sq(noisy_dev, noisy_con)
    mu_ref, sigma_sq_ref = mu_sigma_sq(ref_dev, ref_con)

    return abs(mu_noisy - mu_ref) / np.sqrt(sigma_sq_noisy + sigma_sq_ref)


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

    place = 1
    for key, sc in sorted(scores.items(), key=lambda it: it[1].rel_resilience, reverse=True):
        info = measurement_info.from_key(key)
        print(
            f"{place}.\t{info.counter}\tResilience: {sc.rel_resilience:.4f}\tDeviation: {sc.deviation():.4f}%\tSuscept.: {sc.susceptibility:.4f}"
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

    args = parser.parse_args()

    selection = data_selection()
    selection.lump_benchmarks = True
    selection.lump_noise = True
    selection.lump_params = True
    selection.lump_resources = True
    selection.lump_systems = True
    selection.contrib_threshold = args.contribution
    selection.visit_threshold = args.visits

    noisy = {}
    ref = {}
    for info in available_measurements(os.path.join(args.experiment_root, "result", ".deviations"), selection).values():
        key = info.key()
        if info.noise_pattern == "NO_NOISE":
            ref[key] = info
        else:
            noisy[key] = info

    scores = {}
    for key in tqdm(noisy.keys()):
        info_ref = measurement_info.from_key(key)
        scores[key] = score(noisy[key], ref[info_ref.noiseless_key()], selection)

    sgp = score_group(scores)

    if args.tex:
        print_tabular(sgp.scores, selection)
    else:
        print_cli_formatted(sgp.scores, selection)


if __name__ == "__main__":
    main()
