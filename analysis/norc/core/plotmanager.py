# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import cProfile
import os
from copy import copy
from threading import Lock
import concurrent.futures
from multiprocessing.pool import ThreadPool
import numpy as np
import time

from PySide6.QtCore import QObject, Signal

import norhc.core.plot_rel_dev as prd
from norhc.core.score import score, score_group
from norhc.helpers.util import measurement_info, available_measurements, experiment_filter, warn


class PlotManager(QObject):
    result_ready = Signal(measurement_info)
    score_ready = Signal(measurement_info)
    reconfigured = Signal()

    def __init__(self):
        super().__init__()

        self.experiment_root = ""

        self.plot_settings = prd.plot_settings()
        self.plot_settings.selection.lump_params = True
        self.plot_settings.selection.lump_resources = True

        # Users can read what options they have from these
        self.benchmarks = set()
        self.systems = set()
        self.noise_patterns = set()
        self.metrics = set()

        self.infos = {}
        self.cached_plots = {}
        self.scores = score_group()

        # Internal state for keeping track of calculations
        self.pending_plots_ = {}
        self.pending_scores_ = {}
        self.config_version_ = 0
        self.config_mutex_ = Lock()
        # TODO: This is currently only a single worker because the performance hit
        # from disk I/O is bigger than the gain from parallel calculations.
        # This may be solvable but until then one thread keeps the UI responsive-ish
        # with visible progress in the score table.
        self.workers_ = concurrent.futures.ThreadPoolExecutor(1)

    # Internal function that updates the plots available from the current settings.
    # This can change when a file is loaded or parameter treatment changes.
    def update_available_measurements_(self):
        # Remove old parameters
        self.infos.clear()

        self.benchmarks.clear()
        self.systems.clear()
        self.noise_patterns.clear()
        self.metrics.clear()

        # Check if there is anything to load
        deviation_dir = os.path.join(self.experiment_root, "result", ".deviations")
        if not os.path.exists(deviation_dir):
            return

        # Get all available plot infos
        self.infos = available_measurements(deviation_dir, self.plot_settings.selection)

        # Repopulate parameters
        for inf in self.infos.values():
            self.benchmarks.add(inf.benchmark)
            self.systems.add(inf.system)
            self.noise_patterns.add(inf.noise_pattern)
            self.metrics.add(inf.counter)

    # Internal function that performs an arbitrary function and clears config-dependent state if necessary.
    # fn must return two booleans, clear_plots and clear_scores, in that order.
    def update_config_(self, fn):
        with self.config_mutex_:
            clear_plots, clear_scores = fn()
            if not (clear_plots or clear_scores):
                # Skip the update if nothing has changed
                return

            self.config_version_ += 1

            if clear_plots:
                self.cached_plots.clear()
                self.pending_plots_.clear()

            if clear_scores:
                self.scores.clear()
                self.pending_scores_.clear()

        self.reconfigured.emit()

    def open_experiment(self, experiment_root):
        def fn():
            self.experiment_root = experiment_root
            self.update_available_measurements_()
            return True, True

        self.update_config_(fn)

    def set_plotmode(self, mode):
        def fn():
            changed = self.plot_settings.plot_mode != mode
            self.plot_settings.plot_mode = mode
            return changed, False

        self.update_config_(fn)

    def set_colorbands(self, bands):
        def fn():
            changed = self.plot_settings.n_bands != bands
            self.plot_settings.n_bands = bands
            return changed, False

        self.update_config_(fn)

    def set_contribution_threshold(self, threshold):
        def fn():
            changed = self.plot_settings.selection.contrib_threshold != threshold
            self.plot_settings.selection.contrib_threshold = threshold
            return changed, changed

        self.update_config_(fn)

    def set_visit_threshold(self, threshold):
        def fn():
            changed = self.plot_settings.selection.visit_threshold != threshold
            self.plot_settings.selection.visit_threshold = threshold
            return changed, changed

        self.update_config_(fn)

    def set_parameter_groupings(self, benchmark: bool, system: bool, resources: bool, params: bool, noise: bool):
        def fn():
            changed = self.plot_settings.selection.lump_benchmarks != benchmark
            changed |= self.plot_settings.selection.lump_systems != system
            changed |= self.plot_settings.selection.lump_resources != resources
            changed |= self.plot_settings.selection.lump_params != params
            changed |= self.plot_settings.selection.lump_noise != noise

            self.plot_settings.selection.lump_benchmarks = benchmark
            self.plot_settings.selection.lump_systems = system
            self.plot_settings.selection.lump_resources = resources
            self.plot_settings.selection.lump_params = params
            self.plot_settings.selection.lump_noise = noise
            self.update_available_measurements_()
            return changed, changed

        self.update_config_(fn)

    def set_filter(self, filter: experiment_filter):
        def fn():
            self.plot_settings.selection.filter = filter
            return True, True

        self.update_config_(fn)

    def plot_calculation_(self, info: measurement_info, config_version):
        # Only start a calculation if the results would still be up to date.
        with self.config_mutex_:
            if config_version != self.config_version_:
                return

        t_start = time.process_time()
        # Calculate the plot for the given plot info
        result = prd.prepare_plot(self.plot_settings, info)

        # Only write the result if it still fits the configuration
        with self.config_mutex_:
            if config_version == self.config_version_:
                key = info.key()
                self.cached_plots[key] = result
                if key in self.pending_plots_:
                    del self.pending_plots_[key]

                self.result_ready.emit(info)
        t_end = time.process_time()
        # print(f"plot  {info.key()}\t done in {t_end - t_start}s")

    def score_calculation_(self, info: measurement_info, config_version):
        try:
            # Only start a calculation if the results would still be up to date.
            with self.config_mutex_:
                if config_version != self.config_version_:
                    return

            if info.noise_pattern == "NO_NOISE":
                # Score request for NO_NOISE rejected. Scores are always for a noisy/reference pair.
                return

            t_start = time.process_time()

            scr = score(info, self.infos[info.noiseless_key()], self.plot_settings.selection)

            # Only write the result if it still fits the configuration.
            with self.config_mutex_:
                if config_version == self.config_version_:
                    key = info.key()
                    self.scores.put(key, scr)
                    if key in self.pending_scores_:
                        del self.pending_scores_[key]
                    self.score_ready.emit(info)

            t_end = time.process_time()
            duration = t_end - t_start
            print(f"score {info.key()}\t done in {t_end - t_start}s")
        except Exception as e:
            print(e)
            raise e

    def request_calculation_(
        self,
        calculation,
        info: measurement_info,
        result_cache: dict,
        pending_in: list,
        pending_out: dict,
    ):

        key = info.key()

        if key not in self.infos:
            warn(f"Non-existent result requested: {key}")
            return None, None

        # Replace partial info with the full one with paths
        info = self.infos[key]

        def is_pending(key):
            for p in pending_in:
                if key in p:
                    return True
            return False

        noisy = None
        reference = None

        with self.config_mutex_:
            if key in result_cache:
                # A result is already available so just use it.
                noisy = result_cache[key]
            elif not is_pending(key):
                # If there is no available or pending result, spawn a new calculation for it.
                pending_out[key] = self.workers_.submit(calculation, info, copy(self.config_version_))

            key_noiseless = info.noiseless_key()
            if key_noiseless in result_cache:
                # A result is already available so just use it.
                reference = result_cache[key_noiseless]
            elif not is_pending(key_noiseless):
                # If there is no available or pending result, spawn a new calculation for it.
                if key_noiseless in self.infos:
                    pending_out[key_noiseless] = self.workers_.submit(
                        calculation,
                        self.infos[key_noiseless],
                        copy(self.config_version_),
                    )

        return noisy, reference

    def request_plot(self, info: measurement_info):
        return self.request_calculation_(
            self.plot_calculation_,
            info,
            self.cached_plots,
            [self.pending_plots_],
            self.pending_plots_,
        )

    def request_score(self, info: measurement_info):
        return self.request_calculation_(
            self.score_calculation_,
            info,
            self.scores.scores,
            [self.pending_scores_],
            self.pending_scores_,
        )

    # Plots the deviation diagram to a specified matplotlib axis
    def get_plot(self, ax, info: measurement_info):
        noisy, reference = self.request_plot(info)
        if noisy is None or reference is None:
            return

        prd.setup_chart(ax, self.plot_settings, info, f"{info.counter} ({info.noise_pattern})", [""])

        prd.plot(ax, noisy, reference, self.plot_settings)
        max_deviation = max(noisy.max_deviation, reference.max_deviation)
        if max_deviation < 100:
            ax.set_xlim(-self.plot_settings.extended_zero_area, 1000)

    def get_score(self, info: measurement_info):
        scr, _ = self.request_score(info)
        if scr is None:
            return None
        return scr

    def clear_cache(self):
        self.cached_plots = {}
