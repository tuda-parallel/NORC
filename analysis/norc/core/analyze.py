# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
import sys
import numpy as np
from copy import copy

from pycubexr import CubexParser
from tqdm import tqdm
from norc.helpers.util import (
    dir_info,
    warn,
    iterate_measurements,
    callpath_data,
    write_measurement,
    load_measurement,
    open_experiment_source,
    ExperimentTree,
)

flt_isdir = lambda e: e[2] and not e[0].startswith(".")

# Raw HW counter values above this are treated as measurement artifacts
# (e.g. from contention with cluster-wide monitoring such as ClusterCockpit
# reprogramming/resetting counter registers mid-run) rather than genuine
# readings, and are excluded from deviation statistics.
ARTIFACT_THRESHOLD = 1e13


def measurement_pickle_names(info: dir_info):
    """Names of the pickle files ``analyze()`` writes for this measurement."""
    selected_metrics = info.counters.strip(",").split(",") + ["time", "visits"]
    return [
        f"{info.benchmark}.{info.params}.{info.noise_pattern}.{info.system}.{info.res_cfg}.{metric}.pickle"
        for metric in selected_metrics
        if metric != "visits"
    ]


def analyze(tree: ExperimentTree, output_dir, info: dir_info):
    counter_data = {}
    callpath_names = {}
    callpath_id_mapping = {}

    selected_metrics = info.counters.strip(",").split(",") + ["time", "visits"]

    for metric_name in selected_metrics:
        counter_data[metric_name] = {}

    # Total number of threads across all nodes and processes
    n_threads = info.n_nodes * info.n_processes * info.n_threads

    experiment_dirs = []
    for d in info.dirs:
        experiment_dirs += [path for _, path, _ in filter(flt_isdir, tree.scandir(d))]

    for exdir in experiment_dirs:
        cubex_path = os.path.join(exdir, "profile.cubex")
        if not tree.exists(cubex_path):
            continue

        try:
            with tree.cubex_source(cubex_path) as cubex_source, CubexParser(cubex_source) as experiment:
                for metric_name in selected_metrics:
                    metric_values = experiment.get_metric_values(experiment.get_metric_by_name(metric_name),allow_full_uint64_values=True)

                    total_callpaths = 0
                    skipped_name = 0
                    skipped_threadcount = 0
                    skipped_artifacts = 0

                    def iterate_cnodes(cnode, path):
                        nonlocal total_callpaths
                        nonlocal skipped_name
                        nonlocal skipped_threadcount
                        nonlocal skipped_artifacts

                        for child in cnode.get_children():
                            iterate_cnodes(child, path + [child.region.name])

                        if cnode.id not in metric_values.cnode_indices:
                            return

                        region = cnode.region
                        vals = np.abs(metric_values.cnode_values(cnode))
                        artifact_mask = vals > ARTIFACT_THRESHOLD
                        if artifact_mask.any():
                            skipped_artifacts += artifact_mask.sum()
                            vals = np.where(artifact_mask, np.nan, vals)
                        total_callpaths += 1

                        # Skip callpaths with missing threads
                        if len(vals) != n_threads:
                            skipped_threadcount += 1
                            return

                        cnode_idx = cnode.id
                        # Store a human-readable-ish region name for each callpath.
                        if cnode_idx not in callpath_names:
                            callpath_names[cnode_idx] = region.name
                            callpath_id_mapping[tuple(path)] = cnode_idx
                        elif callpath_names[cnode_idx] != region.name:
                            path_tpl = tuple(path)
                            if path_tpl in callpath_id_mapping:
                                cnode_idx = callpath_id_mapping[path_tpl]
                            else:
                                skipped_name += 1
                                return

                        if cnode_idx not in counter_data[metric_name]:
                            counter_data[metric_name][cnode_idx] = []
                        counter_data[metric_name][cnode_idx].append(vals)

                    for cnode_ in experiment.get_root_cnodes():
                        iterate_cnodes(cnode_, [cnode_.region.name])

                    description = f"{info.benchmark}.{info.params}.{info.noise_pattern}.{info.system}.{info.res_cfg}.{metric_name}"
                    if skipped_name > 0:
                        warn(f"{skipped_name}/{total_callpaths} callpaths skipped due to name mismatch ({description})")
                    if skipped_threadcount > 0:
                        warn(
                            f"{skipped_threadcount}/{total_callpaths} callpaths skipped due to thread count mismatch ({description})"
                        )
                    if skipped_artifacts > 0:
                        warn(
                            f"{skipped_artifacts} thread values excluded as measurement artifacts ({description})"
                        )

        except KeyboardInterrupt:
            print("Exiting on keyboard interrupt")
            exit(0)
        except:
            warn(f"Skipping {exdir}")
            continue

    for metric, callpaths in counter_data.items():
        # Visits are stored in each file but no calculations on them are necessary.
        if metric == "visits":
            continue

        callpath_datas = []
        # Since each thread should have the same number of repetitions per call path, the mean can act as a surrogate sum for contribution calculation.
        total_mean = 0
        for cnode_idx, values in callpaths.items():

            cpd = callpath_data(callpath_names[cnode_idx])
            # Threads whose value was flagged as a measurement artifact are NaN
            # (see ARTIFACT_THRESHOLD above); nanmean excludes them from the mean
            # for that thread rather than discarding the whole callpath/run.
            mean = np.nanmean(values, axis=0)  # mean for each thread across runs

            # It is not possible to calculate a meaningful deviation coefficient for zero-mean measurements.
            # For that reason and because these measurements will typically be all zeros anyway, blowing the zero-bin
            # out of proportion, these measurements are omitted.
            # A thread whose every repetition was an artifact has an all-NaN mean;
            # `nan != 0` is True in numpy, so isfinite() is needed to exclude it too.
            non_zero_mask = (mean != 0) & np.isfinite(mean)

            # Record visits alongside deviation for filtering
            cpd.visits = np.sum(counter_data["visits"][cnode_idx])

            # This is used to calculate the callpath's contribution later.
            total_mean += np.sum(mean[non_zero_mask])

            # Calculate the relative deviation from mean, excluding any
            # repetitions that were flagged as artifacts for this thread.
            for thread_mean, thread_vals in zip(mean[non_zero_mask], np.transpose(values)[non_zero_mask]):
                finite_vals = thread_vals[np.isfinite(thread_vals)]
                cpd.deviations += list(100 * abs(finite_vals - thread_mean) / thread_mean)

            # Callpaths are stored alongside their total mean from which the contribution can be calculated later
            callpath_datas.append((np.sum(mean[non_zero_mask]), cpd))

        # Calculate each call path's contribution once the total is known
        callpaths_only = []
        for mean, cpd in callpath_datas:
            if not cpd.deviations:
                continue  # Skip empty callpaths
            # Record contribution alongside deviation for filtering
            cpd.contribution = 100 * mean / total_mean
            callpaths_only.append(cpd)

        pickle_name = (
            f"{info.benchmark}.{info.params}.{info.noise_pattern}.{info.system}.{info.res_cfg}.{metric}.pickle"
        )
        write_measurement(tree, os.path.join(output_dir, pickle_name), callpaths_only)


def analyze_experiment(experiment_root, progress_callback=None, resume=False):
    """Calculate per-callpath deviations for an experiment and write them to
    ``result/.deviations``.

    ``progress_callback``, when given, is called as ``progress_callback(done, total)``
    once before any work (``done == 0``) and again after each measurement is
    analysed. It lets a GUI drive a progress window; when omitted a ``tqdm`` bar
    is printed to the command line instead (the behaviour used by ``main()``).

    With ``resume=True``, an existing ``.deviations`` directory is kept and only
    measurements whose pickle files are missing are (re-)calculated, so an
    interrupted run can be continued instead of starting over.
    """
    with open_experiment_source(experiment_root) as tree:
        result_dir = os.path.join(tree.root, "result")
        output_dir = os.path.join(tree.root, "result", ".deviations")
        if not resume:
            tree.remove_subtree(output_dir)

        try:
            # First, collect all the files belonging to measurements with identical parameters.
            # These are then analyzed together.
            measurements = {}
            for meas in iterate_measurements(tree, result_dir):
                key = meas.tuple()
                if key not in measurements:
                    measurements[key] = meas
                else:
                    measurements[key].dirs += meas.dirs

                # Noisy measurements are also added to an umbrella noise pattern that combines all noisy measurements.
                # NOTE: Doing it like this is not the most efficent approach since it requires each file to be loaded and processed twice.
                if meas.noise_pattern != "NO_NOISE":
                    meas_allnoise = copy(meas)
                    meas_allnoise.noise_pattern = "ALL_NOISE"
                    key = meas_allnoise.tuple()
                    if key not in measurements:
                        measurements[key] = meas_allnoise
                    else:
                        measurements[key].dirs += meas_allnoise.dirs

            # Analyse and store each measurement
            # NOTE: Parallelizing this doesn't seem to help since most time is spent doing file IO.
            values = list(measurements.values())
            def is_done(path):
                return tree.exists(path) and load_measurement(tree, path) is not None

            if resume:
                values = [
                    meas
                    for meas in values
                    if not all(is_done(os.path.join(output_dir, name)) for name in measurement_pickle_names(meas))
                ]
            if progress_callback is not None:
                progress_callback(0, len(values))
                for done, meas in enumerate(values, start=1):
                    analyze(tree, output_dir, meas)
                    progress_callback(done, len(values))
            else:
                for meas in tqdm(values):
                    analyze(tree, output_dir, meas)
        except BaseException:
            if not resume:
                # A partial .deviations directory would be indistinguishable from a
                # complete one to callers that only check whether it exists, so make
                # sure an interrupted or failed run leaves nothing behind.
                tree.remove_subtree(output_dir)
            raise


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--resume"):
        print("Usage: nohc_analyze <experiment_root> [--resume]")
    else:
        analyze_experiment(sys.argv[1], resume=len(sys.argv) == 3)


if __name__ == "__main__":
    main()
