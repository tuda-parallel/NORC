"""Convert results.json (pb_run benchmark output) into Extra-P's JSON input format.

Each PolyBench kernel becomes a callpath. All dimensions scale proportionally
with `multiplier`, so that single value is used as the one Extra-P parameter "n".
Metrics are namespaced by run mode: time.wall_clock_seconds, time.reported_seconds,
papi.wall_clock_seconds, papi.<COUNTER>.
"""

import json
import sys
from pathlib import Path

SKIP_KEYS = {"benchmark", "category", "mode", "multiplier", "dims", "status"}

# Raw HW counter values above this are treated as measurement artifacts, same
# threshold as norc.core.redundancy.ARTIFACT_THRESHOLD.
ARTIFACT_THRESHOLD = 1e13


def convert(records):
    measurements = {}
    for r in records:
        if r["status"] != "OK":
            continue
        callpath = r["benchmark"]
        point = [r["multiplier"]]
        prefix = r["mode"]
        for key, value in r.items():
            if key in SKIP_KEYS:
                continue
            value = float(value)
            if value > ARTIFACT_THRESHOLD:
                continue
            if prefix == "papi" and key == "wall_clock_seconds":
                metric = "wall_clock_seconds_papi"
            elif key == "reported_seconds":
                metric = "time"
            else:
                metric = key
            entry = measurements.setdefault(callpath, {}).setdefault(metric, [])
            entry.append({"point": point, "values": [value]})
    return {"parameters": ["n"], "measurements": measurements}


def main():
    src = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).with_name("results.json")
    )
    dst = (
        Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name("results_extrap.json")
    )

    records = json.loads(src.read_text())
    experiment = convert(records)
    dst.write_text(json.dumps(experiment, indent=2))
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
