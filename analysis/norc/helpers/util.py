# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
import pickle
import copy
import re
from matplotlib import ticker
from termcolor import colored


class dir_info:
    def __init__(self):
        self.benchmark = ""
        self.params = ""
        self.system = ""
        self.res_cfg = ""
        self.noise_pattern = ""
        self.counters = ""

        self.n_nodes = 0
        self.n_processes = 0
        self.n_threads = 0

        self.dirs = [""]

    def tuple(self):
        return (
            self.benchmark,
            self.system,
            self.noise_pattern,
            self.counters,
            self.n_nodes,
            self.n_processes,
            self.n_threads,
        )

    def __eq__(self, other):
        return self.tuple() == other.tuple()

    def __hash__(self):
        return hash(self.tuple())


class measurement_info:
    def __init__(self):
        self.benchmark = "NONE"
        self.system = "NONE"
        self.noise_pattern = "NO_NOISE"
        self.counter = "NONE"

        self.counter_index = 0
        self.file_paths = []

    def key(self):
        return (self.benchmark, self.system, self.noise_pattern, self.counter)

    def noiseless_key(self):
        return (self.benchmark, self.system, "NO_NOISE", self.counter)

    def from_key(self, k):
        info = measurement_info()
        info.benchmark = k[0]
        info.system = k[1]
        info.noise_pattern = k[2]
        info.counter = k[3]
        return info


class experiment_filter:
    def __init__(self, benchmarks="", systems="", noise_patterns="", counters=""):
        def comma_separated_filter(items):
            if len(items) > 0:
                return lambda x: x in items.split(",")
            return lambda x: True

        # ALL_NOISE is loaded as its own result and should therefore be spared by the filters. Groupings will take care of it.
        if noise_patterns:
            noise_patterns += ",ALL_NOISE"

        self.flt_benchmark = comma_separated_filter(benchmarks)
        self.flt_system = comma_separated_filter(systems)
        self.flt_noise = comma_separated_filter(noise_patterns)
        self.flt_counter = comma_separated_filter(counters)

    def check(self, info):
        return (
            self.flt_benchmark(info.benchmark)
            and self.flt_system(info.system)
            and (info.noise_pattern == "NO_NOISE" or self.flt_noise(info.noise_pattern))
            and self.flt_counter(info.counter)
        )


class data_selection:
    def __init__(self):
        # Dimension groupings: If one of these is true measurements different members
        # of that dimension are lumped into a single member of the parent dimension.
        self.lump_benchmarks = False
        self.lump_systems = False
        self.lump_resources = False
        self.lump_params = False
        self.lump_noise = False

        # Filter for measurements. Empty filters accept everything.
        self.filter = experiment_filter()

        # Callpaths that fall below these thresholds are ignored in the result.
        self.visit_threshold = 0.0
        self.contrib_threshold = 0.0


class callpath_data:
    def __init__(self, name: str):
        self.name = name
        self.deviations = []
        self.visits = 0
        self.contribution = 0


class counted_set:
    def __init__(self):
        self.current_count = 0
        self.counts = {}

    def insert(self, el):
        if el not in self.counts:
            self.counts[el] = self.current_count
            self.current_count += 1

    # returns all items as a list indexed according to their indices
    def ordered_elements(self):
        inverted = {cnt: el for el, cnt in self.counts.items()}
        els = []
        for i in range(len(inverted.items())):
            els.append(inverted[i])
        return els


# Copied from original codebase
class SplitLocator(ticker.Locator):
    def __init__(self, locator_a, locator_b, threshold) -> None:
        self.locator_a = locator_a
        self.locator_b = locator_b
        self.threshold = threshold
        super().__init__()

    def __call__(self):
        """Return the locations of the ticks."""
        # Note, these are untransformed coordinates
        vmin, vmax = self.axis.get_view_interval()
        return self.tick_values(vmin, vmax)

    def tick_values(self, vmin, vmax):
        if vmax < vmin:
            vmin, vmax = vmax, vmin
        ticks_a = self.locator_a.tick_values(vmin, self.threshold)
        ticks_b = self.locator_b.tick_values(self.threshold, vmax)
        return [t for t in ticks_a if t <= self.threshold] + [t for t in ticks_b if t > self.threshold]


# Sorts a list and returns a mapping from list element to sorted index
def sorted_index_map(l, key=None, reverse=False, elem_transform=lambda x: x):
    mp = {}
    for i, x in enumerate(sorted(l, key=key, reverse=reverse)):
        mp[elem_transform(x)] = i
    return mp


def available_measurements(experiment_dir, selection: data_selection):
    # Items can be excluded by prepending a ".".
    flt_is_pickle = lambda f: f.name.endswith(".pickle") and not f.name.startswith(".")
    plt_infs = {}
    # f"{info.benchmark}.{info.params}.{info.noise_pattern}.{info.system}.{info.res_cfg}.{metric.name}.pickle"
    for meas in filter(flt_is_pickle, os.scandir(experiment_dir)):
        components = meas.name.split(".")
        p = measurement_info()

        p.noise_pattern = components[2]
        p.benchmark = components[0]
        p.system = components[3]
        p.counter = components[5].replace("PAPI_", "")

        # Ignore measurements that aren't accepted by the filter
        if not selection.filter.check(p):
            continue

        # Noise lumping is a bit special since it's done during analysis and therefore just a matter of skipping all single-noise measurements.
        if selection.lump_noise and p.noise_pattern not in ["NO_NOISE", "ALL_NOISE"]:
            continue
        if not selection.lump_noise and p.noise_pattern == "ALL_NOISE":
            continue

        if not selection.lump_params:
            p.benchmark += f"({components[1]})"

        if selection.lump_benchmarks:
            p.benchmark = "ALL_BENCHMARKS"

        if selection.lump_systems:
            p.system = "ALL_SYSTEMS"

        if not selection.lump_resources:
            # Form separate "systems" for distinct resource configurations
            p.system += f" ({components[4]})"

        k = p.key()
        if k not in plt_infs:
            plt_infs[k] = p
        plt_infs[k].file_paths.append(meas)
    return plt_infs


class NochrUnpickler(pickle.Unpickler):

    def find_class(self, module, name):
        if module == "util" and name == "callpath_data":
            return callpath_data
        return super().find_class(module, name)


def load_measurement(path):
    try:
        with open(path, "rb") as f:
            unpickler = NochrUnpickler(f)
            return unpickler.load()
    except Exception as e:
        print(f"Failed to load measurement {path}: {e}")


def write_measurement(destination, obj):
    try:
        with open(destination, "wb") as out:
            pickle.dump(obj, out, protocol=pickle.HIGHEST_PROTOCOL)

    except Exception as e:
        print(f"Failed to write measurement {destination}: {e}")


def iterate_measurements(root):
    inf = dir_info()

    flt = lambda f: os.path.isdir(f) and not f.name.startswith(".")
    for benchmark in filter(flt, os.scandir(root)):
        inf.benchmark = benchmark.name
        for system in filter(flt, os.scandir(benchmark)):
            inf.system = system.name
            for res_cfg in filter(flt, os.scandir(system)):
                inf.res_cfg = res_cfg.name
                inf.n_nodes, inf.n_processes, inf.n_threads = list(map(int, (re.findall(r"\d+", res_cfg.name))))
                for counter in filter(flt, os.scandir(res_cfg)):
                    inf.counters = counter.name
                    for measurement in filter(flt, os.scandir(counter)):
                        parts = measurement.name.split(".")
                        inf.noise_pattern = parts[0]
                        inf.params = parts[1]
                        inf.dirs = [measurement]
                        yield copy.copy(inf)


def warn(msg):
    print(colored(f"[WARNING] {msg}", "yellow"))
