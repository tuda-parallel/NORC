# This file is part of the NORC software
#
# Copyright (c) 2024-2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
import pickle
import copy
import re
import zipfile
import shutil
import tempfile
import contextlib
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

    @classmethod
    def from_key(cls, k):
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


class ExperimentTree:
    """Read/write view over an experiment's directory tree (raw measurements plus the
    derived `.deviations` cache).

    Backed either by the real filesystem or directly by a zip archive (read and written
    on the fly, entry by entry, without extracting the archive to disk upfront).
    """

    def scandir(self, path):
        """Returns (name, path, is_dir) tuples for the children of `path`."""
        raise NotImplementedError

    def isdir(self, path):
        raise NotImplementedError

    def exists(self, path):
        raise NotImplementedError

    def open_binary(self, path):
        """Returns a readable binary file-like object for `path`."""
        raise NotImplementedError

    @contextlib.contextmanager
    def cubex_source(self, path):
        """Yields whatever CubexParser should be constructed with for `path`: a real
        filesystem path where one exists (letting tarfile open it by name, exactly as
        before this abstraction existed), or a readable stream otherwise (zip archives).
        """
        with self.open_binary(path) as f:
            yield f

    def write_bytes(self, path, data: bytes):
        raise NotImplementedError

    def remove_subtree(self, path):
        """Removes `path` and everything below it, if present."""
        raise NotImplementedError

    def close(self):
        """Releases any underlying resources (e.g. flushes a zip archive to disk).

        Writes are not guaranteed to be visible to other readers of the same source
        until this is called.
        """

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class DirTree(ExperimentTree):
    def __init__(self, root):
        self.root = root

    def scandir(self, path):
        return [(e.name, e.path, e.is_dir()) for e in os.scandir(path)]

    def isdir(self, path):
        return os.path.isdir(path)

    def exists(self, path):
        return os.path.exists(path)

    def open_binary(self, path):
        return open(path, "rb")

    @contextlib.contextmanager
    def cubex_source(self, path):
        # A real path here, so CubexParser opens it by name exactly like before this
        # abstraction existed -- no wrapping file object, no behavior change.
        yield path

    def write_bytes(self, path, data: bytes):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            out.write(data)

    def remove_subtree(self, path):
        shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path, exist_ok=True)


class ZipTree(ExperimentTree):
    def __init__(self, zip_path):
        self.zip_path = os.path.abspath(zip_path)
        self._zf = zipfile.ZipFile(self.zip_path, "a")
        self._reindex()

        # A zipped experiment directory is often wrapped in one extra top-level folder
        # (e.g. `zip -r experiment.zip experiment/`). Descend into it until the expected
        # `result` folder is found or there's no single unambiguous subdirectory left.
        self.root = self._find_root()

    def _reindex(self):
        self._dirs = {""}
        self._files = set()
        for name in self._zf.namelist():
            norm = name.replace("\\", "/").rstrip("/")
            if not norm:
                continue
            is_dir_entry = name.endswith("/")
            parts = norm.split("/")
            n_dir_parts = len(parts) if is_dir_entry else len(parts) - 1
            for i in range(n_dir_parts):
                self._dirs.add("/".join(parts[: i + 1]))
            if not is_dir_entry:
                self._files.add(norm)

    def _find_root(self):
        base = ""
        while (f"{base}/result" if base else "result") not in self._dirs:
            children = self._direct_children(base)
            subdirs = [c for c in children if c in self._dirs]
            if len(children) == 1 and len(subdirs) == 1:
                base = subdirs[0]
            else:
                break
        return base

    def _direct_children(self, rel):
        prefix = f"{rel}/" if rel else ""
        children = set()
        for p in self._dirs | self._files:
            if p == rel or not p.startswith(prefix):
                continue
            remainder = p[len(prefix) :]
            children.add(prefix + remainder.split("/", 1)[0])
        return children

    def _rel(self, path):
        path = path.replace("\\", "/")
        if path in ("", self.root):
            return self.root
        return path

    def scandir(self, path):
        rel = self._rel(path)
        entries = []
        for child in self._direct_children(rel):
            name = child.rsplit("/", 1)[-1]
            entries.append((name, os.path.join(path, name), child in self._dirs))
        return entries

    def isdir(self, path):
        return self._rel(path) in self._dirs

    def exists(self, path):
        rel = self._rel(path)
        return rel in self._dirs or rel in self._files

    def open_binary(self, path):
        return self._zf.open(self._rel(path), "r")

    def write_bytes(self, path, data: bytes):
        rel = self._rel(path)
        self._zf.writestr(rel, data)
        parts = rel.split("/")
        for i in range(len(parts) - 1):
            self._dirs.add("/".join(parts[: i + 1]))
        self._files.add(rel)

    def remove_subtree(self, path):
        rel = self._rel(path)
        if rel not in self._dirs and rel not in self._files:
            return

        self._zf.close()
        fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=os.path.dirname(self.zip_path) or ".")
        os.close(fd)
        try:
            with zipfile.ZipFile(self.zip_path, "r") as src, zipfile.ZipFile(
                tmp_path, "w", zipfile.ZIP_DEFLATED
            ) as dst:
                for item in src.infolist():
                    norm = item.filename.replace("\\", "/").rstrip("/")
                    if norm == rel or norm.startswith(rel + "/"):
                        continue
                    dst.writestr(item, src.read(item.filename))
            shutil.move(tmp_path, self.zip_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        self._zf = zipfile.ZipFile(self.zip_path, "a")
        self._reindex()

    def close(self):
        self._zf.close()


def open_experiment_source(path) -> ExperimentTree:
    """Opens an experiment directory or a zip archive of one for reading."""
    if os.path.isdir(path):
        return DirTree(path)
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        return ZipTree(path)
    raise FileNotFoundError(f"'{path}' is neither a directory nor a zip archive")


def available_measurements(tree: ExperimentTree, experiment_dir, selection: data_selection):
    # Items can be excluded by prepending a ".".
    flt_is_pickle = lambda e: e[0].endswith(".pickle") and not e[0].startswith(".")
    plt_infs = {}
    # f"{info.benchmark}.{info.params}.{info.noise_pattern}.{info.system}.{info.res_cfg}.{metric.name}.pickle"
    for name, path, _ in filter(flt_is_pickle, tree.scandir(experiment_dir)):
        components = name.split(".")
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
        plt_infs[k].file_paths.append(path)
    return plt_infs


class NochrUnpickler(pickle.Unpickler):

    def find_class(self, module, name):
        if module == "util" and name == "callpath_data":
            return callpath_data
        return super().find_class(module, name)


def load_measurement(tree: ExperimentTree, path):
    try:
        with tree.open_binary(path) as f:
            unpickler = NochrUnpickler(f)
            return unpickler.load()
    except Exception as e:
        print(f"Failed to load measurement {path}: {e}")


def write_measurement(tree: ExperimentTree, destination, obj):
    try:
        tree.write_bytes(destination, pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception as e:
        print(f"Failed to write measurement {destination}: {e}")


def iterate_measurements(tree: ExperimentTree, root):
    inf = dir_info()

    flt = lambda e: e[2] and not e[0].startswith(".")
    for benchmark_name, benchmark_path, _ in filter(flt, tree.scandir(root)):
        inf.benchmark = benchmark_name
        for system_name, system_path, _ in filter(flt, tree.scandir(benchmark_path)):
            inf.system = system_name
            for res_cfg_name, res_cfg_path, _ in filter(flt, tree.scandir(system_path)):
                inf.res_cfg = res_cfg_name
                inf.n_nodes, inf.n_processes, inf.n_threads = list(map(int, (re.findall(r"\d+", res_cfg_name))))
                for counter_name, counter_path, _ in filter(flt, tree.scandir(res_cfg_path)):
                    inf.counters = counter_name
                    for meas_name, meas_path, _ in filter(flt, tree.scandir(counter_path)):
                        parts = meas_name.split(".")
                        inf.noise_pattern = parts[0]
                        inf.params = parts[1]
                        inf.dirs = [meas_path]
                        yield copy.copy(inf)


def warn(msg):
    print(colored(f"[WARNING] {msg}", "yellow"))
