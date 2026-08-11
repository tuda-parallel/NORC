# Artifacts Reproducibility — ProTools '26

Below, we describe how to reproduce the results from the paper entitled:
**"Fantastic Hardware Counters and How to Use Them for Noise-Resilient Performance Modeling"**

The paper closes the loop between noise-resilience analysis and performance modeling. Starting from
[NORC](https://github.com/tuda-parallel/NORC), it adds

1. a **cutoff** on the noise-resilience ranking (manual threshold or automated knee detection),
2. a **modeling-quality module (MQM)** that measures PolyBench kernels with known ground-truth models
   and ranks/filters counters by their *lead-exponent deviation* (ED/MAED), then reduces the set either
   by hierarchical clustering (Ward, Euclidean) or by a rule-based per-category selection,
3. a **measurement orchestration generator** (`norc_generate`) that turns the selected counter set plus
   user-defined parameter ranges into a ready-to-run measurement script, and
4. **HWC-based modeling in Extra-P**, which derives the term structure of a runtime model from the
   hardware-counter models (coefficient-stripped, non-negative constraint) and fits only the
   coefficients to the runtime.

Results were produced on two systems:

| Short | System |
|---|---|
| **LB2** | Lichtenberg II Phase 2, MPI partition: 576 nodes, 2× Intel Xeon Platinum 8470Q (52 cores each), 512 GB DDR5-4800, InfiniBand HDR100 |
| **GH**  | NVIDIA Grace Hopper Superchip server, 72× Neoverse V2 Armv9 cores, 480 GB LPDDR5X |

> The previous ProTools '25 artifact (noise-resilience acquisition and ranking only) is described in
> [`../protools25/README.md`](../protools25/README.md). It is the starting point of stage A below.

---

## Prerequisites

1. **NORC** — install acquisition and/or analysis components, see the
   [installation instructions](https://github.com/tuda-parallel/NORC?tab=readme-ov-file#installation).
   The analysis component provides the CLI entry points used below:
   `norc_gui`, `norc_analyze`, `norc_rank`, `norc_plot`, `norc_generate`, `norc_calc_time`.
2. **Extra-P** with the HWC-based modeling extension (see [Stage D](#stage-d--hwc-based-modeling-in-extra-p)).
3. **Measurement stack** (only needed if you re-run measurements, not for re-analyzing our data):
   Score-P ≥ 8.0 with PAPI support, PAPI, SIONlib, Cube, MPI, OpenMP-capable compiler, Slurm (optional),
   Python ≥ 3.11. On GH, dependencies are installed automatically via Spack (`%gcc@11.4.0`).
4. **Analysis Python deps:** numpy, scipy, matplotlib, pyside6, termcolor, pycubexr, tqdm.
5. **Benchmarks / applications:**
   - [PolyBench-C 4.2.1 OpenMP](https://github.com/EEESlab/PolyBenchC-4.2.1-OpenMP/) (MQM, Stage B)
   - [Kripke](https://github.com/LLNL/Kripke) (Stage D evaluation)
   - RELeARN (Stage D evaluation)
   - NOIGENA, LULESH, LAMMPS, miniFE (only for Stage A, the noise-resilience acquisition)

### Getting the data set

Download the archive from Zenodo (**DOI: TBD — see [Uploads still required](#uploads-still-required)**)
and unzip it:

```sh
wget <zenodo-files-archive-url>
unzip data.zip
```

Expected layout:

```sh
data
├── norc_experiment_lichtenberg_omp_scaled.zip   # Stage A/B input, LB2
├── NORC_experiment_gracehopper.zip              # Stage A/B input, GH (reused from ProTools '25)
├── mqm_polybench_lb2/                           # Stage B PolyBench counter measurements, LB2
├── mqm_polybench_gh/                            # Stage B PolyBench counter measurements, GH
├── kripke_lb2/ , kripke_gh/                     # Stage C/D Extra-P measurement trees
└── relearn_lb2/ , relearn_gh/                   # Stage C/D Extra-P measurement trees
```

Every NORC experiment archive can be opened directly as a `.zip` — no extraction needed.

---

## Stage A — Noise resilience and cutoff (Sec. III-A)

**Input:** a NORC experiment (acquisition with NOIGENA noise patterns).
**Output:** the resilience ranking plots with the knee-detection cutoff (Fig. "Ranking of the counters
available by noise resilience", subfigures for LB2 and GH).

If you want to re-acquire the data instead of using ours, run the NORC acquisition as in the
ProTools '25 artifact (`norc run`). Runtime is ~230 min on a CM-sized allocation and ~2200 min on GH.
The GH experiment from ProTools '25 was reused as-is here; only the ranking was re-run.

```sh
# ranking with knee-based cutoff (default) — reproduces the score plots
norc_rank norc_experiment_lichtenberg_omp_scaled.zip -v 100 -c 1
norc_rank NORC_experiment_gracehopper.zip           -v 100 -c 1
```

`-v 100 -c 1` restricts scoring to call paths with ≥ 100 visits and ≥ 1 % runtime contribution.
Add `--tex` to emit the LaTeX table used in the paper.

**Expected result:** cutoff at resilience ≈ **0.79** on LB2 and ≈ **0.94** on GH — the reason a fixed
threshold (e.g. 0.9) is not used by default.

> **LB2 note:** cluster-wide HWC monitoring on LB2 periodically resets counters, producing arithmetic
> overflows. All counter values above `1e13` are filtered out across LB2 measurements. This is applied
> automatically; the remaining ranks/threads provide sufficient samples.

---

## Stage B — MQM: selecting modeling-capable counters (Sec. III-B)

**Input:** the NORC experiment from Stage A (the counters above the cutoff) + PolyBench-OpenMP.
**Output:** the exponent-deviation heatmaps (LB2 and GH), the clustering dendrograms, and the two
counter sets per system (clustered and rule-based, Tables II and III).

MQM measures PolyBench kernels — no NOIGENA noise is injected, resilience is already established —
sweeping the *medium* preset problem size by factors **1, 2, 4, 8, 16**, with OpenMP threads pinned to
the number of available cores. It then models each counter per kernel with the basic Extra-P modeler
and compares against the ground-truth model via the lead-exponent deviation:

$$\mathrm{ED}(f,g) = e^{*}_f - e^{*}_g, \qquad e^{*}_f = \max_k \{ i_k \mid c_k \neq 0 \}$$

Counters with **MAED > 0.5** are discarded (asymptotically off by $O(\sqrt{n})$). The remainder is
reduced either by hierarchical clustering (Ward's method on the Euclidean distance of the per-kernel
exponent deviations, cut to **6 clusters** by default, each cluster represented by its lowest-MAED
counter) or by the rule-based selection over the six effort-counter categories
(total instructions, branch, floating-point, integer, load, store).

All intermediate results — ranking, MAED table, clustering — are stored in the NORC experiment folder
and can be browsed in the extended NORC analysis GUI (`norc_gui`).

**Expected counter sets:**

| | LB2 (clustered) | GH (clustered) | LB2 (rule-based) | GH (rule-based) |
|---|---|---|---|---|
| | `LD_INS`, `FP_OPS`, `L2_DCA`, `L2_TCR`, `BR_CN`, `SR_INS` | `L2_DCW`, `LD_INS`, `FP_INS`, `L1_TCH`, `L1_TCM`, `TOT_CYC` | `LD_INS`, `FP_OPS`, `TOT_INS`, `BR_INS`, `SR_INS` | `LD_INS`, `FP_OPS`, `TOT_INS`, `SR_INS`, `INT_INS` |

Each set is ordered by increasing exponent deviation. Note that `TOT_INS` does not survive clustering
on either system, and that the paper recommends **excluding `TOT_CYC`** — the GH evaluation is
therefore also reported for the clustered set without it.

Stages A and B only have to be done **once per system**.

---

## Stage C — Measurement orchestration generation (Sec. III-D)

**Input:** the NORC experiment (with the MQM-selected counters) and a Score-P-instrumented run script.
**Output:** a `measure.sh` wrapper that produces an Extra-P-ready directory tree.

The template may be an `sbatch` script or a plain shell script and may contain `@@placeholder@@`
markers that are substituted per configuration:

```sh
norc_generate <experiment.zip> <template_script> \
    --min-resilience 0.9 --top 10 -v 100 -c 1 \
    --var p=2,4,8,16,32 --var zp=8,16,24,32,40 \
    --iterations 5 -o measure.sh
```

Relevant flags: `--top` / `--min-resilience` (counter selection), `--var name=v1,v2,...` (repeatable,
one per placeholder, includes `ntasks`), `--iterations` (repetitions per configuration, ≥ 4 recommended),
`--sbatch` / `--no-sbatch` (override auto-detection), `--prefix` (Extra-P result directory prefix).
See `protools25_data/measure.sh` for a generated example.

Extra-P needs **≥ 5 values per parameter** and **≥ 4 repetitions** per point. The evaluation used:

| App | System | Parameters |
|---|---|---|
| Kripke  | LB2 | $Z_p \in \{8^3,16^3,24^3,32^3,40^3\}$, $G \in \{16,32,48,64,80\}$, $p \in \{2,4,8,16,32\}$, $D=128$, $M=25$, 52 threads/rank |
| Kripke  | GH  | $Z_p \in \{4^3,8^3,12^3,16^3,20^3\}$, $G \in \{24,32,40,48,56\}$, $p \in \{1,2,4,8,16\}$, $D=128$, $M=25$, 2 threads/rank |
| RELeARN | LB2 | $N \in \{250,500,750,1000,1250\}$, $p \in \{2,4,8,16,32\}$, 12 threads/rank |
| RELeARN | GH  | $N \in \{250,500,750,1000,1250\}$, $p \in \{1,2,4,8,16\}$, 2 threads/rank |

Held-out evaluation points: Kripke $Z_p=48^3, G=96, p=64$ (LB2) and $Z_p=24^3, G=64, p=32$ (GH);
RELeARN $N=1500, p=64$ (LB2) and $N=1500, p=32$ (GH).

---

## Stage D — HWC-based modeling in Extra-P (Sec. III-C, IV)

**Input:** the measurement tree from Stage C.
**Output:** the PolyBench MAED plots, the Kripke mean-relative-error and per-parameter MAED plots, and
the RELeARN plots of Sec. IV.

Load the measurement directory in Extra-P and enable HWC-based modeling. Two knobs govern the results
and are swept in the paper:

- **HWC-model selection strategy:** `top exponent` (rank counter models by lead exponent) or
  `top value` (rank by model value).
- **Number of HWC models combined:** 1 … min(#counters, #parameter values − 1).

Coefficient-stripped counter models are summed and the coefficients are refit against the runtime by
non-negative least squares; terms that do not explain enough of the runtime are pruned. Models whose
exponent deviates by more than 0.5 from the runtime-only model are flagged in the Extra-P GUI.

Baselines to compare against: runtime-only models with and without the non-negative coefficient
constraint.

**Expected results:**
- PolyBench: the rule-based set always improves on the runtime-only model; the best configurations
  more than halve the mean exponent deviation on GH and reduce it to roughly a third on LB2.
- Kripke: rule-based + top exponent + 2 HWC models gives max MAED 0.11 across parameters on GH
  (baseline 0.28, or 0.94 with negative coefficients allowed) and up to **75 % lower relative error**.
- RELeARN (LB2): HWC models yield $N\cdot\log(N)^2$ (clustered) and $N\cdot\log(N)^2 + p^{1/4}$
  (rule-based) versus the ground truth $N \cdot \log(N \cdot p)$, both closer than the time-only
  baseline $N^{5/4} + N^{5/4}\log(p)$ (ED 0.25 in $N$).
- Overall recommendation: **rule-based counter set, top-exponent strategy, 2–3 HWC models, no `TOT_CYC`.**

Because the underlying measurements carry run-to-run variability, re-running the campaigns yields
close but not bit-identical numbers. Re-analyzing the published data reproduces the paper exactly.

---

## Uploads still required

The following are referenced above but are **not yet published**; they must be uploaded before the
artifact is complete:

- [ ] **Zenodo record for ProTools '26** — a new DOI is needed. The badge/DOI in this README and the
      footnote in `content/07_acknowledgement.tex` of the paper (currently marked
      `\textcolor{red}{update}` and still pointing at the ProTools '25 record
      [10.5281/zenodo.16786108](https://doi.org/10.5281/zenodo.16786108)) must be updated.
- [ ] **LB2 NORC experiment** `norc_experiment_lichtenberg_omp_scaled.zip` — used for the LB2 score
      plot and as MQM input. Not present in this repository.
- [ ] **GH NORC experiment** — `NORC_experiment_gracehopper.zip` exists locally
      (`protools25_data/`, and an untracked copy in `analysis/`) but is not committed; it is 2 GB and
      belongs on Zenodo, not in git.
- [ ] **MQM PolyBench measurements** for LB2 and GH (counter values, MAED tables, clustering results).
- [ ] **Extra-P measurement trees** for Kripke and RELeARN on both systems, plus the held-out
      evaluation points.
- [ ] **NORC MQM implementation** — the modeling-quality module (knee-based cutoff, PolyBench harness,
      lead-exponent deviation, Ward clustering, rule-based selection) is described in Sec. III-A/III-B
      but is not yet in this repository. `norc_generate` (Stage C) is present; `norc_rank` currently
      has no knee-detection flag.
- [ ] **Extra-P HWC-modeling extension** — the branch/release implementing the coefficient-stripping
      modeler with the top-value / top-exponent strategies must be published and linked here.
- [ ] **Plot scripts** for the paper figures (score plots, deviation heatmaps, dendrograms, the
      PolyBench/Kripke/RELeARN MAED and relative-error plots).
