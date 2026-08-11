# NORC modeling_quality (Phase 3a)

Implements Phase 3a of `norc-modeling-quality-plan.md`: a second, PolyBench-based
calibration pass that checks whether the PAPI counters NORC's regular pipeline
already selected (Phase 1 acquisition + Phase 2 resilience cutoff) actually
grow with problem size the way true computational complexity predicts.

This folder is a standalone top-level project, a sibling of `acquisition/` and
`analysis/`, not a modification of either. It has exactly one integration
seam into the rest of NORC (`generate_papi_counters.py` imports
`norc.core.score`, read-only) and one small additive change to the
external PolyBench checkout (a new `--papi-counters-file` flag on its
`run_benchmarks.py`, described below). Neither `acquisition/` nor `analysis/`
had any existing file changed, so both continue to work exactly as before,
independently of this folder.

Counter selection here is based purely on `norc.core.score`'s resilience
cutoff (contribution >= 1%, visits >= 100 by default); it does not yet apply
`norc.core.redundancy`'s correlation-based filtering (Phase 5 of the plan),
which will be wired in once that function is updated.

Phase 4 (analysis)'s `to_extrap.py`/`compare_to_ground_truth.py` are wired into
`submit_calibration_job.sh` as a best-effort post-processing step (see below).
Phase 3b (MPI-scaling calibration) and 5 (redundancy-filter tie-break) from the
plan are **not** implemented here yet.

## What it does

1. **`generate_papi_counters.py`** reads NORC's Phase-2 counter selection
   (`norc.core.score.counters_above_cutoff` / `ranked_counters_above_cutoff`,
   the same functions `norc_score` uses) for a given experiment root, and
   writes them out as a `papi_counters.list`-format file:

   ```
   python3 generate_papi_counters.py <experiment_root> --ranked -o papi_counters.list
   ```

   `--ranked` orders counters best-to-worst by `rel_resilience` (doesn't change
   the selection, just makes the list reproducible/ordered); omit it for an
   alphabetically-sorted set. `-c/-v/-r` mirror `norc_score`'s
   `--contribution`/`--visits`/`--min-resilience` (defaulting here to 1%
   contribution / 100 visits) so the same cutoff parameters can be reused.

   This step (and the `norc.core.score`/experiment-root dependency that comes
   with it) is entirely optional -- `run_benchmarks.py --papi-counters-file`
   doesn't care where its input file came from, and `submit_calibration_job.sh`
   accepts an explicit counter list or file instead of an experiment root (see
   step 3) to skip it altogether.

2. **PolyBench's `run_benchmarks.py`** gained one new flag,
   `--papi-counters-file PATH`, which parses that file and injects it via the
   existing `write_custom_polybench_source` mechanism (previously only reachable
   via `--all-papi-presets`'s hardware auto-discovery) -- i.e. it compiles a
   private copy of `polybench.c` next to a matching `papi_counters.list` instead
   of touching `utilities/papi_counters.list`. This is the exact seam the plan
   calls for; no other part of `run_benchmarks.py` changed.

   ```
   python3 run_benchmarks.py --papi-counters-file papi_counters.list
   ```

   It also gained `--estimate-only`, which does the same benchmark discovery
   and argument handling but prints `ESTIMATED_SECONDS=<n>` and exits instead
   of compiling/running anything -- `submit_calibration_job.sh` uses this to
   size `--time` (below). Assuming every combo hits its full timeout is wildly
   pessimistic in practice (only a handful of kernels are anywhere near it), so
   the estimate instead assumes at most `ESTIMATE_SLOW_COMBOS_CAP` (5) combos
   per mode need the full timeout and the rest run
   `ESTIMATE_FAST_SPEEDUP`x (100x) faster, plus a fixed per-combo compile-time
   allowance throughout (compiling isn't sped up by any of this).

   This validates "does this counter's growth with problem size `n` reflect
   true computational complexity" against PolyBench's `GROUND_TRUTH.txt` --
   nothing about multi-process behavior (that's Phase 3b, not built yet).

   `--papi-prefix`/`--cc` control the PAPI install and C compiler benchmarks
   are built with. Neither is hardcoded: `--cc` defaults to `$CC` or `gcc`;
   `--papi-prefix` defaults to `$POLYBENCH_PAPI_PREFIX` if set, else whichever
   of `PAPI_ROOT`/`PAPI_DIR`/`PAPI_HOME`/`EBROOTPAPI` a `module load papi` set
   (acquisition's `USE_SPACK=false` path), else `spack location -i papi`
   (acquisition's `USE_SPACK=true` path) -- either way, only resolves in a
   shell that's sourced acquisition's environment, see step 3. If none of
   those find a prefix but the compiler can still reach `<papi.h>`/`-lpapi` on
   its own (a module added them to `CPATH`/`LIBRARY_PATH` without exporting a
   root var), that's used without an explicit prefix (skips `-I`/`-L`, relies
   on those paths already being set at compile *and* run time). Unless
   `--skip-papi` is passed, PAPI being unreachable by any of these is a hard
   error -- it used to silently fall back to TIME-only data, which produces a
   result set that looks complete but is quietly missing every PAPI counter.

   Every requested counter is also validated against `papi_avail -a`'s Yes/No
   availability column before compiling anything. `PAPI_event_name_to_code()`
   failing on even one requested counter crashes the *whole* compiled
   benchmark at runtime (a typo, e.g. `PAPI_TOT_IN` instead of
   `PAPI_TOT_INS`, or a real preset this hardware doesn't support) -- an
   invalid/unavailable name is now a hard error naming exactly which
   counter(s) to fix, instead of a crash discovered only after compiling and
   starting every single benchmark.

3. **`submit_calibration_job.sh`** runs step 1 itself at submission time (it's
   plain Python/file-I/O over already-computed measurements, not worth a node
   allocation), then submits step 2 as a single-node SLURM job, reusing
   acquisition's own per-system config end-to-end instead of carrying a
   separate job template:
   - Sources `acquisition/config/systems/<system>/system.sh` (read-only;
     nothing under `acquisition/` is written) for `PARTITION`/`BUDGET`/
     `CORES_PER_NODE` *and* `JOB_TEMPLATE`.
   - Lifts the SBATCH header (directives/comments, i.e. everything before the
     first real line of shell) straight out of that system's
     `acquisition/config/job_templates/$JOB_TEMPLATE.sh`, plus its
     `batch_prefix` if any -- the exact same two pieces
     `benchmark_util.sh`'s `job_from_template` assembles. If a user has tuned
     partition/hint/mem for their cluster there, a calibration job picks it up
     automatically. Only the header is reused; the rest of those templates is
     acquisition's own NOIGENA-noise benchmark loop, irrelevant to this
     single-shot run.
   - Same submission call as the regular pipeline:
     `sbatch --dependency=singleton job.sh` (no `--array`, since this is one
     calibration run rather than a noise/counter-group sweep).
   - On the `local` system (no real scheduler), runs the job script directly,
     mirroring acquisition's `-l/--local` fallback.
   - Refuses to run at all if `acquisition/config/config_done` doesn't exist
     -- that's `acquisition/install.sh`'s own marker that its config
     assistant has run; without it, `system.sh`'s `CORES_PER_NODE`, the job
     template, and the PAPI/compiler environment (next) are all guesswork.
   - Sources acquisition's environment inside the job, *before* `set -euo
     pipefail` (module systems and Spack's `setup-env.sh` are notorious for
     benign nonzero returns that would otherwise abort the job right there)
     and before anything else runs:
     - `acquisition/config/modules.sh` -- the actual, current `module load
       ...` commands. `acquisition/runner/run_benchmarks.sh` sources a copy
       of this (`experiment/config/modules.sh`, made at install time) before
       submitting real acquisition jobs; we source the source file directly
       instead, since that copy only exists while an `experiment/` dir is
       still around (deleted by e.g. acquisition's `-f`/force-rebuild, or
       just cleaned up by hand). Needed because a module load can set
       `CPATH`/`LIBRARY_PATH`/`PAPI_ROOT`/etc, none of which the next file
       captures.
     - `acquisition/build/env.sh` -- a `PATH`/`LD_LIBRARY_PATH` snapshot
       frozen at install time, plus (if Spack-based) sourcing Spack's
       `setup-env.sh` + `spack load mpi`; this is what makes
       `spack location -i papi` resolve at all.

     Either missing just warns and continues (rather than failing), e.g. if
     acquisition hasn't been fully installed yet -- PAPI/compiler resolution
     then falls back to whatever's already on the job's default PATH.

   ```
   ./submit_calibration_job.sh <system> <experiment_root> [--local] [extra run_benchmarks.py args...]
   ./submit_calibration_job.sh <system> --counters PAPI_A,PAPI_B,... [--experiment-root DIR | --local] [extra args...]
   ./submit_calibration_job.sh <system> --counters-file counters.list [--experiment-root DIR | --local] [extra args...]
   ./submit_calibration_job.sh <system> --resume exec_dir [extra args...]
   # e.g.
   ./submit_calibration_job.sh gh result/kripke.gh
   ./submit_calibration_job.sh local result/kripke.local --multipliers 1,2,4,8,16
   ./submit_calibration_job.sh gh --counters TOT_CYC,TOT_INS,L1_DCM
   ./submit_calibration_job.sh gh result/kripke.gh --local
   ./submit_calibration_job.sh gh --resume result/kripke.gh/modeling_quality/polybench.gh.20260802_014925
   ```

   `--counters`/`--counters-file` skip `generate_papi_counters.py` (and the
   `norc.core.score`/experiment-root dependency it needs) entirely -- useful
   for calibrating a hand-picked or otherwise-sourced counter list without a
   Phase-1/Phase-2 NORC experiment to score. `--counters` accepts bare names
   (`TOT_CYC` gets the same `PAPI_` prefix `generate_papi_counters.py` would
   add); `--counters-file` takes a `papi_counters.list`-format file as-is.

   `--resume` continues a previous run instead of starting a new one (e.g.
   after a job that timed out or got killed partway through): every other
   invocation creates a fresh timestamped `exec_dir`, so `run_benchmarks.py`'s
   own `results.jsonl`-based resume logic (see below) never actually has
   anything to resume *from* on its own -- `--resume exec_dir` reuses that
   prior run's directory as-is (same `papi_counters.list`, same
   `--output-dir`), so `run_benchmarks.py` finds its own `results.jsonl` there
   and skips whatever's already `OK` in it instead of redoing it.

   **Storage location.** By default, results are stored inside the NORC
   experiment itself, under `<experiment_root>/modeling_quality/`, so they sit
   next to the rest of that experiment's data (and travel with it if it's
   copied/archived). `--local` stores under this script's own
   `modeling_quality/exec/` instead. When using `--counters`/`--counters-file`
   (no positional `<experiment_root>`), pass `--experiment-root DIR` to still
   default into `DIR/modeling_quality/`; without it, those two modes fall back
   to `--local`'s `exec/` location, since there's no experiment to store into.

   Everything from a run -- not just the raw results -- is kept under one
   directory instead of being scattered into `benchmarks/polybench/`:

   ```
   <experiment_root>/modeling_quality/polybench.<system>.<timestamp>/   # or modeling_quality/exec/... with --local
   ├── job.sh
   ├── status_out/, status_err/        # SLURM stdout/stderr
   ├── papi_counters.list              # written pre-submission, see step 1
   ├── build/                          # --build-dir, compiled benchmark executables
   └── results/                        # --output-dir
       ├── results.jsonl                #   incremental log; re-running resumes from it
       ├── results.json, time_results.csv, papi_results.csv
       ├── results_extrap.json          #   Phase 4: to_extrap.py's output
       ├── metric_ranking_by_deviation.json
       ├── selected_counters.json          # {"rule_based": {...}, "clustered": {...}}
       └── deviations.csv, deviation_by_metric.png, exponent_accuracy.png,
           deviation_heatmap.pdf, metric_clustering.pdf   # Phase 4: compare_to_ground_truth.py's output
   ```

   The job script deletes `build/` afterwards unless `--keep-build` is passed
   through as an extra arg.

   `compare_to_ground_truth.py` needs the `extrap` package (not one of this
   project's required dependencies, see below). `submit_calibration_job.sh`
   checks for it in acquisition's own build venv (`acquisition/tmp/.venv`,
   created unconditionally by `acquisition/install.sh`) *at submission time*,
   interactively, on the login node -- not inside the job, which has no
   terminal to ask on. If that venv doesn't exist, Phase 4 is skipped for this
   run with a warning. If it exists but lacks `extrap`, you're asked for
   confirmation before it's installed there; declining also just skips Phase 4
   for this run. Either way, nothing under `acquisition/` is ever changed
   without that confirmation.

   `POLYBENCH_DIR` env var overrides where the PolyBench dir is expected
   (default: the vendored `benchmarks/polybench/`, which holds
   `run_benchmarks.py` alongside the `PolyBenchC-4.2.1-OpenMP/` checkout).

   `SLURM_TIME` overrides the SBATCH `--time` request; left unset, it's
   estimated instead of defaulting to a flat guess: `run_benchmarks.py
   --estimate-only` (see below) runs at submission time with the exact same
   args the job will use, printing a worst-case seconds budget without
   compiling or running anything; that gets a +20% margin and becomes
   `--time`. Falls back to `02:00:00` if the estimate can't be parsed.

## Requirements

- The `benchmarks/polybench/` dir, which holds NORC's own `run_benchmarks.py`
  (contains `--papi-counters-file`) alongside a vendored PolyBench/GPU-OpenMP
  checkout at `PolyBenchC-4.2.1-OpenMP/`; override the dir via
  `POLYBENCH_DIR`.
- Only if you're sourcing counters from a NORC experiment (i.e. not using
  `--counters`/`--counters-file`, see step 3): NORC's `analysis` package
  installed (`pip install -e NORC/analysis`) so `generate_papi_counters.py`
  can `import norc.core.score`, and a completed Phase-1/Phase-2 NORC
  experiment (a `norc_redundancy`-ready experiment root) to score.
- Optional: `extrap` + `matplotlib` for Phase 4's `compare_to_ground_truth.py`
  (`to_extrap.py` itself is stdlib-only and always runs). Without `extrap`,
  `submit_calibration_job.sh` skips that one step with a warning.

## Files

```
modeling_quality/
├── README.md
├── generate_papi_counters.py           # Phase 2 -> papi_counters.list bridge
└── submit_calibration_job.sh           # builds job.sh from acquisition's own config + sbatch
```
