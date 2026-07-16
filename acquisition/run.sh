#!/bin/bash
# Main execution script for running data acquisition experiments.
#
# Copyright (c) 2026 TU Darmstadt, Germany
# Version: v0.2
# Date: 2025-08-08
#
# Licensed under the BSD 3-Clause License.
# For more information, see the LICENSE file in the project root:
# https://github.com/tuda-parallel/NORC/blob/main/LICENSE
cd build || exit 1

# Copying the build directory (e.g. via a network share or archive) doesn't
# reliably preserve the executable bit, so ensure it's set before running.
chmod +x ./run_benchmarks.sh
./run_benchmarks.sh "$@"