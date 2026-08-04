#!/usr/bin/env python3
"""
Orchestrator for the PolyBench/GPU-OpenMP suite.

Compiles and runs every benchmark under OpenMP/ at problem sizes that are
integer multiples of each benchmark's MEDIUM_DATASET size, collecting both
wall-clock TIME data (-DPOLYBENCH_TIME) and PAPI hardware-counter data
(-DPOLYBENCH_PAPI). Each run is appended to results.jsonl in --output-dir as
soon as it finishes; results.json + the CSVs are (re)written from that once
everything's done. Re-running with the same --output-dir resumes: any
benchmark/multiplier/mode combo already OK in results.jsonl is skipped.

Usage:
  python3 run_benchmarks.py [--multipliers 1,2,4,8,16] [--timeout 300]
                            [--mem-limit-gb 16] [--papi-prefix PATH] [--cc gcc]
                            [--benchmarks name1,name2,...]
                            [--skip-time] [--skip-papi]
                            [--papi-counters-file counters.list]
                            [--output-dir pb_run/results]

Without --papi-prefix (or POLYBENCH_PAPI_PREFIX), the PAPI install prefix is
resolved from whichever of PAPI_ROOT/PAPI_DIR/PAPI_HOME/EBROOTPAPI a `module
load papi` set, else via `spack location -i papi` -- either way, the same PAPI
acquisition/install.sh installs, which only resolves in a shell that's sourced
acquisition's environment (see submit_calibration_job.sh). If neither finds a
prefix but the compiler can still reach <papi.h>/-lpapi on its own (module
added them to CPATH/LIBRARY_PATH without exporting a root var), that's used
without an explicit prefix. Unless --skip-papi is passed, PAPI being
unreachable by any of these is a hard error, not a silent fallback to
TIME-only data.

Every requested PAPI counter is also checked against `papi_avail -a`'s Yes/No
availability column before compiling anything: PAPI_event_name_to_code()
failing on even one requested counter crashes the whole compiled benchmark at
runtime (a typo like PAPI_TOT_IN instead of PAPI_TOT_INS, or a real preset
this hardware just doesn't support), so an invalid/unavailable name is a hard
error naming exactly which counter(s) to fix, not a mid-run crash discovered
after compiling and starting every benchmark.
"""
import argparse
import csv
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import time

# stdout is block-buffered once SLURM redirects it to a file (#SBATCH --output=...),
# so progress prints would otherwise only show up in bursts instead of as they happen.
sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POLYBENCH_ROOT = os.path.join(SCRIPT_DIR, "PolyBenchC-4.2.1-OpenMP")
UTIL_DIR = os.path.join(POLYBENCH_ROOT, "utilities")
POLYBENCH_C = os.path.join(UTIL_DIR, "polybench.c")
PAPI_COUNTERS_LIST = os.path.join(UTIL_DIR, "papi_counters.list")

# Macros that represent iteration/time-step counts rather than problem size.
# These are kept at their MINI_DATASET value instead of being scaled.
FIXED_MACROS = {"TSTEPS", "TMAX", "NITER"}

# Rough per-combo compile-time allowance for --estimate-only: compile_benchmark()
# itself has no timeout, so a worst-case wall-clock budget needs some slack on
# top of each run's own --timeout to cover the gcc invocation before it.
COMPILE_OVERHEAD_SECONDS = 10

# --estimate-only assumes at most this many combos (per mode) actually need
# their full --timeout; the rest are assumed to run roughly this much faster.
# Treating every combo as a worst-case timeout (as if they all hung) massively
# overestimates the real budget, since in practice only a handful of kernels
# are anywhere near the timeout and most finish in a small fraction of it.
ESTIMATE_SLOW_COMBOS_CAP = 5
ESTIMATE_FAST_SPEEDUP = 100

# Env vars a plain `module load papi` (acquisition's USE_SPACK=false path) commonly
# sets to the install prefix -- varies by site/module system (Lmod, EasyBuild, ...),
# so try the usual suspects rather than assuming one.
PAPI_MODULE_ENV_VARS = ["PAPI_ROOT", "PAPI_DIR", "PAPI_HOME", "EBROOTPAPI"]


def resolve_papi_prefix(explicit_prefix):
    """An explicit --papi-prefix/POLYBENCH_PAPI_PREFIX wins; otherwise check the env vars
    a `module load papi` typically sets, then ask Spack for the same `papi` package
    acquisition/install.sh installs via Spack (`spack load papi`) -- either way, this is
    only correct in a shell that's sourced acquisition's build/env.sh (which puts either
    the loaded module's env or Spack's setup-env.sh + `spack load` in place)."""
    if explicit_prefix:
        return explicit_prefix
    for var in PAPI_MODULE_ENV_VARS:
        if os.environ.get(var):
            return os.environ[var]
    try:
        proc = subprocess.run(["spack", "location", "-i", "papi"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def papi_available_via_default_paths(cc):
    """Many module systems add PAPI's headers/libs to CPATH/LIBRARY_PATH/LD_LIBRARY_PATH
    without exporting any root-style env var to point resolve_papi_prefix() at -- so before
    giving up, actually try compiling+linking against <papi.h>/-lpapi with no explicit -I/-L
    at all, the same way it'd work from an interactive shell with the module loaded."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "papi_probe.c")
        with open(src, "w") as f:
            f.write("#include <papi.h>\nint main(void) { return 0; }\n")
        try:
            proc = subprocess.run(
                [cc, src, "-lpapi", "-o", os.path.join(tmp, "papi_probe")],
                capture_output=True, text=True,
            )
        except FileNotFoundError:
            return False
        return proc.returncode == 0


def discover_benchmarks():
    """Find every benchmark directory with -omp.c version + matching .h (excluding utilities)."""
    benchmarks = []
    for root, dirs, files in os.walk(SCRIPT_DIR):
        dirs[:] = [d for d in dirs if d != "utilities" and not d.startswith(".")]
        # Look for -omp.c files
        omp_c_files = [f for f in files if f.endswith("-omp.c")]
        if not omp_c_files:
            continue
        if len(omp_c_files) > 1:
            continue
        c_file = omp_c_files[0]
        # Extract base name by removing -omp.c suffix
        name = c_file[:-6]  # Remove "-omp.c"
        h_file = name + ".h"
        if h_file not in files:
            continue
        rel = os.path.relpath(root, SCRIPT_DIR)
        benchmarks.append({
            "name": name,
            "dir": root,
            "category": os.path.dirname(rel),
            "c_file": os.path.join(root, c_file),
            "h_file": os.path.join(root, h_file),
        })
    benchmarks.sort(key=lambda b: (b["category"], b["name"]))
    return benchmarks


DATASET_NAMES = ["MINI_DATASET", "SMALL_DATASET", "MEDIUM_DATASET", "LARGE_DATASET", "EXTRALARGE_DATASET"]


def parse_dataset(header_path, dataset_name):
    """Extract the {MACRO: value} map defined under #ifdef <dataset_name>."""
    text = open(header_path).read()
    m = re.search(rf"#\s*ifdef\s+{dataset_name}\b(.*?)#\s*endif", text, re.S)
    if not m:
        return {}
    block = m.group(1)
    return {name: int(val) for name, val in re.findall(r"#\s*define\s+(\w+)\s+(\d+)", block)}


def parse_papi_counter_names(list_path):
    text = open(list_path).read()
    text = re.sub(r"//.*", "", text)
    return re.findall(r'"([^"]+)"', text)


def find_papi_avail(papi_prefix):
    """Locate the papi_avail binary + the env to run it with. papi_prefix=None means PAPI was
    resolved via the compiler's default search paths (see papi_available_via_default_paths())
    rather than a known prefix -- fall back to PATH, which is where a module load would have
    put it too. Returns (None, None) if it can't be found."""
    if papi_prefix is None:
        papi_avail_bin = shutil.which("papi_avail")
        return (papi_avail_bin, os.environ.copy()) if papi_avail_bin else (None, None)
    papi_avail_bin = os.path.join(papi_prefix, "bin", "papi_avail")
    if not os.path.isfile(papi_avail_bin):
        return None, None
    env = os.environ.copy()
    lib = os.path.join(papi_prefix, "lib")
    if os.path.isdir(lib):
        env["LD_LIBRARY_PATH"] = lib + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return papi_avail_bin, env


def query_papi_avail(papi_prefix):
    """Run `papi_avail -a` and return {event_name: available_on_this_hardware}. Empty dict
    if papi_avail can't be found/run at all -- callers should treat that as "unknown", not
    "every counter is invalid"."""
    papi_avail_bin, env = find_papi_avail(papi_prefix)
    if not papi_avail_bin:
        return {}
    proc = subprocess.run([papi_avail_bin, "-a"], capture_output=True, text=True, env=env)
    events = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^(PAPI_\w+)\b(.*)$", line)
        if not m:
            continue
        name, rest = m.groups()
        avail_m = re.search(r"\b(Yes|No)\b", rest)
        events[name] = (avail_m.group(1) == "Yes") if avail_m else True
    return events


def validate_papi_counters(papi_counter_names, papi_prefix):
    """Return the subset of papi_counter_names that papi_avail doesn't recognize or marks
    unavailable on this hardware. PAPI_event_name_to_code() failing on any single requested
    counter crashes the *entire* compiled benchmark (see polybench.c's papi_init), so this is
    meant to be checked before compiling anything instead of discovered mid-run."""
    events = query_papi_avail(papi_prefix)
    if not events:
        return []  # papi_avail itself unavailable/unreadable here -- can't validate, don't block
    return [name for name in papi_counter_names if not events.get(name, False)]


def discover_papi_preset_counters(papi_prefix):
    """Every PAPI preset event the hardware actually supports (per `papi_avail -a`'s Yes/No
    availability column, not just every name it lists)."""
    events = query_papi_avail(papi_prefix)
    names = [name for name, available in events.items() if available]
    if not names:
        print("[WARN] papi_avail found no available preset events (or couldn't be run)",
              file=sys.stderr)
    return names


def write_custom_polybench_source(build_dir, papi_counter_names):
    """Create a private copy of polybench.c plus a matching papi_counters.list.

    polybench.c does `#include "papi_counters.list"` (quoted form), which GCC resolves
    relative to polybench.c's own directory before consulting any -I path. So the only way
    to swap in an auto-discovered counter list without mutating utilities/papi_counters.list
    is to compile from a private copy of polybench.c that sits next to the generated list.
    """
    custom_dir = os.path.join(build_dir, "papi_presets")
    os.makedirs(custom_dir, exist_ok=True)
    shutil.copyfile(POLYBENCH_C, os.path.join(custom_dir, "polybench.c"))
    list_path = os.path.join(custom_dir, "papi_counters.list")
    with open(list_path, "w") as f:
        f.write("// Auto-generated by --all-papi-presets\n")
        for name in papi_counter_names:
            f.write(f'"{name}",\n')
    return os.path.join(custom_dir, "polybench.c")


def load_existing_results(jsonl_path):
    """Read a results.jsonl from a previous (possibly interrupted) run.

    Returns the completed OK records, keyed by (benchmark, multiplier, mode) --
    anything not OK (failed/timeout/crashed mid-write) is left out so the main
    loop retries it instead of trusting a half-finished result.
    """
    completed = {}
    if not os.path.isfile(jsonl_path):
        return completed
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("status") == "OK":
                completed[(record["benchmark"], record["multiplier"], record["mode"])] = record
    return completed


def estimate_seconds(n_benchmarks, n_multipliers, do_time, do_papi, timeout, papi_timeout):
    """At most ESTIMATE_SLOW_COMBOS_CAP combos (per mode) are assumed to need
    their full timeout; the rest are assumed ESTIMATE_FAST_SPEEDUP times faster.
    Every combo still gets the per-combo compile-time allowance regardless
    (compile_benchmark() has no timeout of its own, and compiling isn't sped up)."""
    combos = n_benchmarks * n_multipliers
    n_slow = min(ESTIMATE_SLOW_COMBOS_CAP, combos)
    n_fast = combos - n_slow

    def mode_seconds(per_combo_timeout):
        return (n_slow * per_combo_timeout
                + n_fast * (per_combo_timeout / ESTIMATE_FAST_SPEEDUP)
                + combos * COMPILE_OVERHEAD_SECONDS)

    total = 0.0
    if do_time:
        total += mode_seconds(timeout)
    if do_papi:
        total += mode_seconds(papi_timeout)
    return total


def _test_estimate_seconds():
    # 3 benchmarks x 2 multipliers = 6 combos (< cap of 5? no, 6 > 5, so 5 slow + 1 fast)
    assert estimate_seconds(3, 2, True, True, 100, 500) == (
        (5 * 100 + 1 * (100 / 100) + 6 * 10) + (5 * 500 + 1 * (500 / 100) + 6 * 10)
    )
    assert estimate_seconds(3, 2, True, False, 100, 500) == 5 * 100 + 1 * 1 + 6 * 10
    assert estimate_seconds(3, 2, False, False, 100, 500) == 0
    # fewer combos than the cap -> every combo counted as slow, none fast
    assert estimate_seconds(2, 2, True, False, 100, 500) == 4 * 100 + 4 * 10


def scaled_defines(base, multiplier):
    defines = {}
    for macro, val in base.items():
        defines[macro] = val if macro in FIXED_MACROS else val * multiplier
    return defines


def _test_load_existing_results():
    import tempfile
    lines = [
        {"benchmark": "2mm", "multiplier": 1, "mode": "time", "status": "OK"},
        {"benchmark": "2mm", "multiplier": 2, "mode": "time", "status": "TIMEOUT"},
        {"benchmark": "3mm", "multiplier": 1, "mode": "papi", "status": "OK"},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in lines:
            f.write(json.dumps(r) + "\n")
        path = f.name
    try:
        completed = load_existing_results(path)
        assert set(completed) == {("2mm", 1, "time"), ("3mm", 1, "papi")}
        assert load_existing_results(path + ".missing") == {}
    finally:
        os.remove(path)


def compile_benchmark(bench, mode, defines, out_path, papi_prefix, extra_cflags, cc="gcc", polybench_c=POLYBENCH_C):
    """papi_prefix=None means PAPI was resolved via the compiler's default search paths
    (see papi_available_via_default_paths()) -- skip the explicit -I/-L/-rpath and rely on
    CPATH/LIBRARY_PATH/LD_LIBRARY_PATH already covering it, the same way an interactive
    shell with the module loaded would."""
    mode_macro = "POLYBENCH_TIME" if mode == "time" else "POLYBENCH_PAPI"
    cmd = [cc, "-O2", "-fopenmp", "-I", UTIL_DIR]
    if mode == "papi" and papi_prefix is not None:
        cmd += ["-I", os.path.join(papi_prefix, "include")]
    cmd += [f"-D{mode_macro}"]
    for macro, val in defines.items():
        cmd += [f"-D{macro}={val}"]
    cmd += extra_cflags
    cmd += [bench["c_file"], polybench_c, "-o", out_path]
    if mode == "papi":
        if papi_prefix is not None:
            lib = os.path.join(papi_prefix, "lib")
            cmd += ["-L", lib, f"-Wl,-rpath,{lib}"]
        cmd += ["-lpapi"]
    cmd += ["-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0, proc.stderr, cmd


def make_preexec(mem_limit_bytes):
    if not mem_limit_bytes:
        return None

    def _limit():
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit_bytes, mem_limit_bytes))
    return _limit


def run_benchmark(exe_path, timeout, mem_limit_bytes, omp_threads, omp_places, omp_proc_bind):
    env = os.environ.copy()
    if omp_threads:
        env["OMP_NUM_THREADS"] = str(omp_threads)
    if omp_places:
        env["OMP_PLACES"] = omp_places
    if omp_proc_bind:
        env["OMP_PROC_BIND"] = omp_proc_bind
    start = time.time()
    try:
        proc = subprocess.run(
            [exe_path], capture_output=True, text=True, timeout=timeout,
            env=env, preexec_fn=make_preexec(mem_limit_bytes),
        )
        wall = time.time() - start
        return {
            "status": "OK" if proc.returncode == 0 else "RUN_FAILED",
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "wall_clock_seconds": wall,
        }
    except subprocess.TimeoutExpired as e:
        return {
            "status": "TIMEOUT",
            "returncode": None,
            "stdout": e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            "stderr": e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
            "wall_clock_seconds": timeout,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--multipliers", default="1,2,4,8,16",
                     help="Comma-separated multiples of the base dataset to sweep (default: 1,2,4,8,16)")
    ap.add_argument("--base-dataset", default="MEDIUM", choices=["MINI", "SMALL", "MEDIUM", "LARGE", "EXTRALARGE"],
                     help="Which POLYBENCH_*_DATASET size to use as the x1 base (default: MEDIUM)")
    ap.add_argument("--benchmarks", default=None,
                     help="Comma-separated benchmark names to restrict to (default: all)")
    ap.add_argument("--timeout", type=float, default=120,
                     help="Per-run wall-clock timeout in seconds for TIME-mode runs; PAPI-mode "
                          "runs get this multiplied by the number of counters being measured, "
                          "since PAPI multiplexes them across repeated executions (default: 120)")
    ap.add_argument("--mem-limit-gb", type=float, default=16,
                     help="Per-run address-space limit in GB, 0 = unlimited (default: 16)")
    ap.add_argument("--papi-prefix", default=os.environ.get("POLYBENCH_PAPI_PREFIX"),
                     help="PAPI install prefix (must contain include/ and lib/). Default: "
                          f"whichever of {PAPI_MODULE_ENV_VARS} a `module load papi` set, else "
                          "`spack location -i papi` -- acquisition's own PAPI install, not a "
                          "hardcoded path -- if that fails to find one.")
    ap.add_argument("--cc", default=os.environ.get("CC", "gcc"),
                     help="C compiler to build benchmarks with (default: $CC, or 'gcc')")
    ap.add_argument("--skip-time", action="store_true", help="Do not collect TIME data")
    ap.add_argument("--skip-papi", action="store_true", help="Do not collect PAPI data")
    ap.add_argument("--all-papi-presets", action="store_true",
                     help="Auto-discover every hardware-available PAPI preset event via "
                          "`papi_avail -a` and measure all of them instead of the counters "
                          "listed in utilities/papi_counters.list")
    ap.add_argument("--papi-counters-file", default=None,
                     help="Path to a papi_counters.list-format file (one \"PAPI_XXX\", entry "
                          "per line, // comments allowed) whose counters replace the ones in "
                          "utilities/papi_counters.list, via the same private-polybench.c "
                          "mechanism as --all-papi-presets. Takes precedence over "
                          "--all-papi-presets if both are given. Intended for NORC's "
                          "modeling_quality/generate_papi_counters.py output.")
    ap.add_argument("--omp-threads", type=int, default=os.cpu_count(),
                     help="Sets OMP_NUM_THREADS for reproducibility (default: os.cpu_count(), 0 = OpenMP default)")
    ap.add_argument("--omp-places", default="cores",
                     help="Sets OMP_PLACES for thread pinning, empty string to leave unset (default: cores)")
    ap.add_argument("--omp-proc-bind", default="close",
                     help="Sets OMP_PROC_BIND, empty string to leave unset (default: close)")
    ap.add_argument("--output-dir", default=os.path.join(SCRIPT_DIR, "pb_run", "results"),
                     help="Directory to write CSV/JSON results into")
    ap.add_argument("--build-dir", default=os.path.join(SCRIPT_DIR, "pb_run", "build"),
                     help="Directory to place compiled executables into")
    ap.add_argument("--keep-build", action="store_true", help="Do not delete the build dir when finished")
    ap.add_argument("--estimate-only", action="store_true",
                     help="Print a worst-case wall-clock budget across every benchmark/multiplier/"
                          "mode combo as 'ESTIMATED_SECONDS=<n>' and exit, without compiling or "
                          "running anything (e.g. to size a SLURM --time request beforehand).")
    args = ap.parse_args()

    multipliers = [int(x) for x in args.multipliers.split(",") if x.strip()]
    mem_limit_bytes = int(args.mem_limit_gb * (1024 ** 3)) if args.mem_limit_gb else None

    do_time = not args.skip_time
    do_papi = not args.skip_papi

    if do_papi:
        args.papi_prefix = resolve_papi_prefix(args.papi_prefix)
        papi_valid = args.papi_prefix and (
            os.path.isdir(os.path.join(args.papi_prefix, "include"))
            and os.path.isdir(os.path.join(args.papi_prefix, "lib"))
        )
        if not papi_valid and not args.estimate_only and papi_available_via_default_paths(args.cc):
            # No PAPI_ROOT/PAPI_DIR/.../spack hit, but the compiler can already reach
            # <papi.h>/-lpapi on its own (module added them to CPATH/LIBRARY_PATH/etc.
            # without exporting a root var) -- papi_prefix=None tells compile_benchmark()/
            # discover_papi_preset_counters() to skip explicit -I/-L and rely on that.
            print("PAPI resolved via the compiler's default search paths (no explicit "
                  "prefix needed)")
            args.papi_prefix = None
            papi_valid = True
        if not papi_valid:
            if args.estimate_only:
                # The resolved (or unresolved) prefix is often only meaningful on
                # compute nodes, not wherever --estimate-only gets run from (e.g. a
                # login node at submission time), and --estimate-only doesn't
                # actually touch PAPI -- don't let this undercount the PAPI budget.
                print(f"[WARN] no valid PAPI prefix (got '{args.papi_prefix}'); "
                      "estimate still assumes PAPI-mode combos run.", file=sys.stderr)
            else:
                # PAPI was requested (no --skip-papi) -- silently dropping to
                # TIME-only data would produce a result set that looks complete
                # but is missing every PAPI counter, so fail instead of warning.
                sys.exit(
                    f"error: PAPI data requested but no valid PAPI prefix found, and the "
                    f"compiler can't reach <papi.h>/-lpapi on its own either "
                    f"(got prefix '{args.papi_prefix}'). Pass --papi-prefix, set "
                    f"POLYBENCH_PAPI_PREFIX, source acquisition's build/env.sh so a loaded "
                    f"module's {PAPI_MODULE_ENV_VARS} or `spack location -i papi` resolves, "
                    f"or pass --skip-papi."
                )

    if not args.estimate_only:
        os.makedirs(args.output_dir, exist_ok=True)
        os.makedirs(args.build_dir, exist_ok=True)

    polybench_c = POLYBENCH_C
    if do_papi and args.papi_counters_file:
        papi_counter_names = parse_papi_counter_names(args.papi_counters_file)
        if papi_counter_names:
            print(f"Using {len(papi_counter_names)} counter(s) from '{args.papi_counters_file}'")
            if not args.estimate_only:
                polybench_c = write_custom_polybench_source(args.build_dir, papi_counter_names)
        else:
            print(f"[WARN] '{args.papi_counters_file}' contained no counters; "
                  "falling back to utilities/papi_counters.list", file=sys.stderr)
            papi_counter_names = parse_papi_counter_names(PAPI_COUNTERS_LIST)
    elif do_papi and args.all_papi_presets:
        discovered = discover_papi_preset_counters(args.papi_prefix)
        if discovered:
            print(f"Auto-discovered {len(discovered)} available PAPI preset counters")
            papi_counter_names = discovered
            if not args.estimate_only:
                polybench_c = write_custom_polybench_source(args.build_dir, papi_counter_names)
        else:
            print("[WARN] Falling back to utilities/papi_counters.list", file=sys.stderr)
            papi_counter_names = parse_papi_counter_names(PAPI_COUNTERS_LIST)
    else:
        papi_counter_names = parse_papi_counter_names(PAPI_COUNTERS_LIST) if do_papi else []

    # TODO: Fix check and reenable
    # if do_papi and papi_counter_names:
    #     invalid = validate_papi_counters(papi_counter_names, args.papi_prefix)
    #     if invalid:
    #         # PAPI_event_name_to_code() failing on even one requested counter crashes the
    #         # *whole* compiled benchmark at runtime (polybench.c's papi_init test_fail()s),
    #         # discovered only after compiling and starting every single benchmark -- so
    #         # fail fast here instead, with the exact names to fix.
    #         sys.exit(
    #             f"error: {len(invalid)} requested PAPI counter(s) are not valid/available "
    #             f"presets on this hardware (per `papi_avail -a`): {invalid}. Fix the counter "
    #             f"list (check for typos against real preset names, e.g. PAPI_TOT_INS not "
    #             f"PAPI_TOT_IN) or drop them."
    #         )

    # PAPI multiplexes counters that don't fit in hardware simultaneously across
    # repeated executions, so a run with more counters takes proportionally longer.
    papi_timeout = args.timeout * max(1, len(papi_counter_names))

    benchmarks = discover_benchmarks()
    if args.benchmarks:
        wanted = set(args.benchmarks.split(","))
        benchmarks = [b for b in benchmarks if b["name"] in wanted]

    if args.estimate_only:
        estimated = estimate_seconds(len(benchmarks), len(multipliers), do_time, do_papi,
                                      args.timeout, papi_timeout)
        print(f"ESTIMATED_SECONDS={int(estimated)}")
        return

    base_dataset = args.base_dataset + "_DATASET"

    print(f"Discovered {len(benchmarks)} benchmarks; base={base_dataset}; multipliers={multipliers}; "
          f"modes={'time ' if do_time else ''}{'papi' if do_papi else ''}")

    # Incremental log: one JSON object per line, flushed to disk right after each
    # run finishes. Re-running with the same --output-dir resumes from it --
    # combos already recorded as OK are skipped instead of recompiled/rerun.
    jsonl_path = os.path.join(args.output_dir, "results.jsonl")
    completed = load_existing_results(jsonl_path)
    if completed:
        print(f"Resuming: {len(completed)} combo(s) already OK in '{jsonl_path}', skipping those")
    all_results = list(completed.values())

    total_runs = len(benchmarks) * len(multipliers) * (int(do_time) + int(do_papi))
    done = 0

    with open(jsonl_path, "a") as jsonl_f:
        for bench in benchmarks:
            base = parse_dataset(bench["h_file"], base_dataset)
            if not base:
                print(f"[SKIP] {bench['name']}: could not parse {base_dataset} macros")
                continue

            for multiplier in multipliers:
                defines = scaled_defines(base, multiplier)
                modes = ([("time", "POLYBENCH_TIME")] if do_time else []) + \
                        ([("papi", "POLYBENCH_PAPI")] if do_papi else [])

                for mode, _ in modes:
                    done += 1
                    tag = f"[{done}/{total_runs}] {bench['name']:<16} x{multiplier:<4} {mode:<4}"

                    if (bench["name"], multiplier, mode) in completed:
                        print(f"{tag}: SKIP (already OK)")
                        continue

                    exe_path = os.path.join(
                        args.build_dir, f"{bench['name']}_{mode}_x{multiplier}"
                    )
                    ok, compile_err, cmd = compile_benchmark(
                        bench, mode, defines, exe_path, args.papi_prefix,
                        extra_cflags=[], cc=args.cc, polybench_c=polybench_c,
                    )
                    record = {
                        "benchmark": bench["name"],
                        "category": bench["category"],
                        "mode": mode,
                        "multiplier": multiplier,
                        "dims": json.dumps(defines),
                    }
                    if not ok:
                        print(f"{tag}: COMPILE_FAILED")
                        record.update({"status": "COMPILE_FAILED", "error": compile_err.strip()[-2000:]})
                        all_results.append(record)
                        jsonl_f.write(json.dumps(record) + "\n")
                        jsonl_f.flush()
                        continue

                    timeout = papi_timeout if mode == "papi" else args.timeout
                    run_res = run_benchmark(exe_path, timeout, mem_limit_bytes,
                                             args.omp_threads, args.omp_places, args.omp_proc_bind)
                    record["wall_clock_seconds"] = run_res["wall_clock_seconds"]
                    record["status"] = run_res["status"]

                    if run_res["status"] != "OK":
                        print(f"{tag}: {run_res['status']}")
                        record["error"] = (run_res["stdout"] + run_res["stderr"]).strip()[-2000:]
                    else:
                        if mode == "time":
                            try:
                                record["reported_seconds"] = float(run_res["stdout"].strip().split()[0])
                            except (ValueError, IndexError):
                                record["status"] = "PARSE_FAILED"
                                record["error"] = run_res["stdout"][-500:]
                        else:
                            values = run_res["stdout"].split()
                            if len(values) >= len(papi_counter_names) and papi_counter_names:
                                for name, val in zip(papi_counter_names, values):
                                    record[name] = val
                            else:
                                record["status"] = "PARSE_FAILED"
                                record["error"] = (run_res["stdout"] + run_res["stderr"])[-500:]
                        print(f"{tag}: {record['status']}"
                              + (f" ({record.get('reported_seconds')}s)" if mode == "time" and "reported_seconds" in record else ""))

                    all_results.append(record)
                    jsonl_f.write(json.dumps(record) + "\n")
                    jsonl_f.flush()

    # --- consolidate outputs (results.jsonl is the resumable log; these are the report) ---
    json_path = os.path.join(args.output_dir, "results.json")
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    time_rows = [r for r in all_results if r["mode"] == "time"]
    papi_rows = [r for r in all_results if r["mode"] == "papi"]

    if time_rows:
        time_csv = os.path.join(args.output_dir, "time_results.csv")
        fields = ["benchmark", "category", "multiplier", "dims", "status",
                  "reported_seconds", "wall_clock_seconds", "error"]
        with open(time_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in time_rows:
                w.writerow(r)
        print(f"Wrote {time_csv}")

    if papi_rows:
        papi_csv = os.path.join(args.output_dir, "papi_results.csv")
        fields = ["benchmark", "category", "multiplier", "dims", "status",
                  "wall_clock_seconds"] + papi_counter_names + ["error"]
        with open(papi_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in papi_rows:
                w.writerow(r)
        print(f"Wrote {papi_csv}")

    print(f"Wrote {json_path}")

    n_ok = sum(1 for r in all_results if r["status"] == "OK")
    n_fail = len(all_results) - n_ok
    print(f"\nSummary: {n_ok} OK, {n_fail} failed/timeout out of {len(all_results)} runs")

    if not args.keep_build:
        shutil.rmtree(args.build_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
