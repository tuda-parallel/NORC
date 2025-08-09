# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import pickle
import logging
import numpy as np
from pathlib import Path
from scipy import signal


def write_measurement(destination, obj):
    try:
        with open(destination, "wb") as out:
            pickle.dump(obj, out, protocol=pickle.HIGHEST_PROTOCOL)

    except Exception as e:
        logging.error(f"Encountered error while writing measurement: {e}")


def generate_deterministic(path, value, measurements, meas_size):
    contributions = signal.hann(measurements) * 200 / measurements
    # Ensure that the total contribution is exactly 100%
    contributions[0] += 100.0 - np.sum(contributions)
    print(np.sum(contributions))
    deviations = [[value] * meas_size] * measurements
    write_measurement(path, [contributions, deviations])


def main():
    clean_path = Path("test/test/test/test/NO_NOISE")
    noisy_path = Path("test/test/test/test/NOISE")
    clean_path.mkdir(parents=True, exist_ok=True)
    noisy_path.mkdir(parents=True, exist_ok=True)
    generate_deterministic(clean_path / "test.pickle", 42, 10000, 100)
    generate_deterministic(noisy_path / "test.pickle", 42, 10000, 100)


if __name__ == "__main__":
    main()
