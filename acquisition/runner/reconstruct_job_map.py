"""
One-off repair tool for a job_map whose second column lost the real Slurm
array-job IDs (e.g. they were parsed as a banner token like "Plugin_11"
instead of "53405717_11").

It rebuilds the mapping from the on-disk status files in <status_dir>/jobs/,
which the job scripts name "${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}".

Matching logic
--------------
Each Slurm array corresponds to exactly one exec dir, i.e. one
"<benchmark>.<system>.<res_cfg>" prefix (the first three dotted fields of a
descriptor). run_benchmarks.sh submits those arrays in `ls exec/` order, so
the k-th distinct prefix (in job_map appearance order) was assigned the k-th
smallest array-job ID. That submission order is the primary matcher.

As an independent check we also compare task-ID sets: an array's status files
should cover a subset of its group's task IDs (a subset, not necessarily equal,
because tasks that never started leave no status file). Any disagreement is
reported so a bad reconstruction is never written silently.

Usage
-----
    python reconstruct_job_map.py <status_dir>            # dry run -> job_map.reconstructed
    python reconstruct_job_map.py <status_dir> --apply    # back up to job_map.broken, overwrite job_map
"""

import argparse
import os
import sys
from collections import OrderedDict


def task_id_of(token):
    """"Plugin_11" / "53405717_11" -> "11"."""
    return token.rsplit("_", 1)[-1]


def read_groups(job_map_path):
    """Return (raw_lines, groups) where groups maps prefix -> [task_id, ...]
    in first-appearance order."""
    raw_lines = []
    groups = OrderedDict()
    with open(job_map_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            raw_lines.append(line)
            descr, token = line.split(" ")
            prefix = ".".join(descr.split(".")[:3])
            groups.setdefault(prefix, []).append(task_id_of(token))
    return raw_lines, groups


def read_array_tasks(jobs_dir):
    """Return array_id -> set(task_id) parsed from status file names."""
    array_tasks = {}
    for name in os.listdir(jobs_dir):
        if "_" not in name:
            continue
        arr, task = name.rsplit("_", 1)
        array_tasks.setdefault(arr, set()).add(task)
    return array_tasks


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?", default="./status",
                    help="Path to the experiment's status directory")
    ap.add_argument("--apply", action="store_true",
                    help="Overwrite job_map (original backed up to job_map.broken). "
                         "Without this flag the result is written to job_map.reconstructed.")
    args = ap.parse_args()

    job_map_path = os.path.join(args.dir, "job_map")
    jobs_dir = os.path.join(args.dir, "jobs")

    if not os.path.isfile(job_map_path):
        sys.exit(f"No job_map at {job_map_path}")
    if not os.path.isdir(jobs_dir):
        sys.exit(f"No jobs directory at {jobs_dir}")

    raw_lines, groups = read_groups(job_map_path)
    array_tasks = read_array_tasks(jobs_dir)

    group_prefixes = list(groups.keys())
    array_ids = sorted(array_tasks, key=int)  # submission order == ascending id

    print(f"job_map groups : {len(group_prefixes)}")
    print(f"array IDs found : {len(array_ids)}  ({', '.join(array_ids) or 'none'})")

    warnings = []
    if len(array_ids) < len(group_prefixes):
        warnings.append(
            f"Fewer array IDs ({len(array_ids)}) than groups ({len(group_prefixes)}): "
            "some group never wrote a status file, so its ID cannot be recovered.")
    if len(array_ids) > len(group_prefixes):
        warnings.append(
            f"More array IDs ({len(array_ids)}) than groups ({len(group_prefixes)}): "
            "status/jobs may contain leftovers from another run.")

    # Primary match: appearance order <-> ascending array id.
    assignment = OrderedDict()
    for prefix, arr in zip(group_prefixes, array_ids):
        assignment[prefix] = arr

    # Cross-check each pairing against the task-ID sets.
    print("\nMapping:")
    for prefix in group_prefixes:
        arr = assignment.get(prefix)
        gset = set(groups[prefix])
        if arr is None:
            print(f"  {prefix}  ->  (UNRECOVERABLE: no array id)")
            continue
        aset = array_tasks[arr]
        extra = aset - gset  # status tasks not present in this group
        note = ""
        if extra:
            note = f"  [!] {len(extra)} status task(s) not in this group -> order likely wrong"
            warnings.append(f"{prefix} <-> {arr}: task-set mismatch ({sorted(extra)[:5]}...)")
        started = len(aset & gset)
        print(f"  {prefix}  ->  {arr}   ({started}/{len(gset)} tasks have a status file){note}")

    # Rebuild, preserving original line order.
    out_lines = []
    unrecoverable = 0
    for line in raw_lines:
        descr, token = line.split(" ")
        prefix = ".".join(descr.split(".")[:3])
        tid = task_id_of(token)
        arr = assignment.get(prefix)
        if arr is None:
            out_lines.append(line)  # leave broken line untouched
            unrecoverable += 1
        else:
            out_lines.append(f"{descr} {arr}_{tid}")

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    if args.apply:
        if unrecoverable:
            sys.exit(f"\nRefusing to --apply: {unrecoverable} line(s) unrecoverable. "
                     "Review the dry-run output first.")
        backup = job_map_path + ".broken"
        if not os.path.exists(backup):
            os.replace(job_map_path, backup)
            print(f"\nOriginal backed up to {backup}")
        else:
            print(f"\nBackup {backup} already exists, leaving it as is.")
        with open(job_map_path, "w") as f:
            f.write("\n".join(out_lines) + "\n")
        print(f"Rewrote {job_map_path}")
    else:
        out_path = job_map_path + ".reconstructed"
        with open(out_path, "w") as f:
            f.write("\n".join(out_lines) + "\n")
        print(f"\nDry run: wrote {out_path}")
        print("Inspect it, then re-run with --apply to replace job_map.")


if __name__ == "__main__":
    main()