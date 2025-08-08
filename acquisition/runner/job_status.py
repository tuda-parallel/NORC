# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import sys
import os.path
import time
import argparse


class job_count:
    def __init__(self):
        self.running = 0
        self.finished = 0
        self.failed = 0
        self.pending = 0

    def add(self, other: "job_count"):
        self.running += other.running
        self.finished += other.finished
        self.failed += other.failed
        self.pending += other.pending

    def total(self):
        return self.running + self.finished + self.failed + self.pending


class screen:
    def __init__(self):
        self.lines = []

    def putln(self, ln: str):
        self.lines.append(ln)

    def print(self):
        sys.stdout.write(f"\033[{len(self.lines)}A")

        maxlen = 0
        for ln in self.lines:
            maxlen = max(maxlen, len(ln))

        for ln in self.lines:
            # Print all lines padded so that older lines don't protrude from them
            print(ln.ljust(maxlen + 5))


job_queue = set()
# Used to determine the current phase of progress indication


def draw_screen(row_names, col_names, ctrs, progress_counter=0):
    scr = screen()
    progress = ["   ", ".  ", ".. ", "..."]
    for benchmark, cnt in ctrs.items():
        total_jobs = cnt.total()
        scr.putln(
            f"Benchmark {benchmark} {progress[progress_counter % len(progress)]}:"
        )
        scr.putln(f"  finished: {cnt.finished}/{total_jobs}")
        scr.putln(f"  failed: {cnt.failed}/{total_jobs}")
        scr.putln(f"  running: {cnt.running}/{total_jobs}")
        scr.putln(f"  pending: {cnt.pending}/{total_jobs}")

    scr.print()


def split_array(task_array: str):
    parts = task_array.split("_")
    if len(parts) < 2:
        return [task_array]  # single task
    job = parts[0]
    ranges = parts[1].replace("[", "").replace("]", "").split(",")
    tasks = []
    for r in ranges:
        lu = r.split("-")
        if len(lu) < 2:
            tasks.append(f"{job}_{lu[0]}")
            continue
        for t in range(int(lu[0]), int(lu[1]) + 1):
            tasks.append(f"{job}_{t}")
    return tasks


def update_queue():
    global job_queue
    job_queue.clear()
    for l in os.popen('squeue --me -h -o "%i"').readlines():
        jobs = split_array(l.rstrip())
        for j in jobs:
            job_queue.add(j)


def is_queued(id: str):
    # A job is queued if it is either in the queue itself (when using job arrays)
    # or if the job it's a step of is in the queue (when using iterative jobs).
    return id in job_queue or id.split("_")[0] in job_queue


def check_job(id: str, cnt: job_count, dir):
    if os.path.exists(f"{dir}/jobs/{id}"):
        with open(f"{dir}/jobs/{id}") as f:
            l = f.readline()
            try:
                # If the status is a number the job has terminated in some way.
                exit_code = int(l)
                if exit_code == 0:
                    cnt.finished += 1
                else:
                    cnt.failed += 1
                return
            except ValueError:
                if is_queued(id):
                    cnt.running += 1
                else:
                    cnt.failed += 1
    else:
        # If there is no status file for this job it's either pending or was cancelled before it started.
        if is_queued(id):
            cnt.pending += 1
        else:
            cnt.failed += 1


def show_status(jobs, dir, once=False):
    # Unfinished jobs have yet to reach their final status (i.e. they are running / pending).
    has_unfinished_jobs = True
    has_failed_jobs = False

    row_names = set()
    col_names = set()

    progress_counter = 0

    while has_unfinished_jobs:
        update_queue()
        status_ctrs = {}
        for line in jobs:
            line = (
                line.rstrip()
            )  # Trailing newline characters would confuse the path library.
            parts = line.split(" ")
            descr = parts[0]
            job_id = parts[1]
            benchmark, system, res_cfg, counters, noise_pattern, benchmark_params = (
                descr.split(".")
            )

            if benchmark not in status_ctrs:
                col_names.add(benchmark)
                status_ctrs[benchmark] = job_count()

            cnt = status_ctrs[benchmark]
            check_job(str(job_id), cnt, dir)

            has_unfinished_jobs = cnt.running > 0 or cnt.pending > 0
            has_failed_jobs = has_failed_jobs or (cnt.failed > 0)

        draw_screen(row_names, col_names, status_ctrs, progress_counter)
        progress_counter += 1

        if once:
            break

        time.sleep(1)

    return not has_failed_jobs


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Displays the status of a running hardware counter noise resilience experiment"
    )

    parser.add_argument(
        "dir",
        nargs="?",
        default="./status",
        help="Path to the experiment's status directory",
    )
    parser.add_argument(
        "-o",
        "--once",
        action="store_true",
        help="Exit after checking the status once",
    )
    args = parser.parse_args()

    try:
        f = open(f"{args.dir}/job_map", "r")
        jobs = f.readlines()
        f.close()
        exit(0 if show_status(jobs, args.dir, args.once) else 1)
    except KeyboardInterrupt:
        # Don't show the user a crash log as it was obviously intended.
        exit(0)
    except Exception as e:
        print("Job tracking failed:", e)
        exit(2)
