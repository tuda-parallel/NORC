#!/bin/bash
# Data acquisition script for system.sh in the NORC performance measurement pipeline.
#
# Copyright (c) 2026 TU Darmstadt, Germany
# Version: v0.2
# Date: 2025-08-08
#
# Licensed under the BSD 3-Clause License.
# For more information, see the LICENSE file in the project root:
# https://github.com/tuda-parallel/NORC/blob/main/LICENSE
export CORES_PER_NODE=72
export JOB_TEMPLATE="local_strided_rankfile"