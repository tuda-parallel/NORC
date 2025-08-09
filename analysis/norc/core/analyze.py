# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
import sys
import shutil
import numpy as np
from copy import copy

from pycubexr import CubexParser
from tqdm import tqdm
from norc.helpers.util import dir_info, warn, iterate_measurements, callpath_data, write_measurement

flt_isdir = lambda f: f.is_dir() and not f.name.startswith(".")


def analyze(output_dir, info: dir_info):
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
        experiment_dirs += filter(flt_isdir, os.scandir(d))

    for exdir in experiment_dirs:
        if not os.path.exists(os.path.join(exdir, "profile.cubex")):
            continue

        try:
            with CubexParser(os.path.join(exdir, "profile.cubex")) as experiment:
                for metric_name in selected_metrics:
                    metric_values = experiment.get_metric_values(experiment.get_metric_by_name(metric_name))

                    total_callpaths = 0
                    skipped_name = 0
                    skipped_threadcount = 0

                    def iterate_cnodes(cnode, path):
                        nonlocal total_callpaths
                        nonlocal skipped_name
                        nonlocal skipped_threadcount

                        for child in cnode.get_children():
                            iterate_cnodes(child, path + [child.region.name])

                        if cnode.id not in metric_values.cnode_indices:
                            return

                        region = cnode.region
                        vals = np.abs(metric_values.cnode_values(cnode))
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
            mean = np.mean(values, axis=0)  # mean for each thread across runs

            # It is not possible to calculate a meaningful deviation coefficient for zero-mean measurements.
            # For that reason and because these measurements will typically be all zeros anyway, blowing the zero-bin
            # out of proportion, these measurements are omitted.
            non_zero_mask = mean != 0

            # Record visits alongside deviation for filtering
            cpd.visits = np.sum(counter_data["visits"][cnode_idx])

            # This is used to calculate the callpath's contribution later.
            total_mean += np.sum(mean)

            # Calculate the relative deviation from mean
            for thread_mean, thread_vals in zip(mean[non_zero_mask], np.transpose(values)[non_zero_mask]):
                cpd.deviations += list(100 * abs(thread_vals - thread_mean) / thread_mean)

            # Callpaths are stored alongside their total mean from which the contribution can be calculated later
            callpath_datas.append((np.sum(mean), cpd))

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
        write_measurement(os.path.join(output_dir, pickle_name), callpaths_only)


def analyze_experiment(experiment_root):
    result_dir = os.path.join(experiment_root, "result")
    output_dir = os.path.join(result_dir, ".deviations")
    shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir)

    # First, collect all the files belonging to measurements with identical parameters.
    # These are then analyzed together.
    measurements = {}
    for meas in iterate_measurements(result_dir):
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
    for meas in tqdm(measurements.values()):
        analyze(output_dir, meas)


def main():
    if len(sys.argv) != 2:
        print("Usage: norhc_analyze  <experiment_root>")
    else:
        analyze_experiment(sys.argv[1])


if __name__ == "__main__":
    main()
