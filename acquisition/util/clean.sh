#!/bin/bash
# Data acquisition script for clean.sh in the NORC performance measurement pipeline.
#
# Copyright (c) 2026 TU Darmstadt, Germany
# Version: v0.2
# Date: 2025-08-08
#
# Licensed under the BSD 3-Clause License.
# For more information, see the LICENSE file in the project root:
# https://github.com/tuda-parallel/NORC/blob/main/LICENSE
source "$CONFIG_DIR/build_settings.sh"

echo "Removing previous installation and temporary files"

rm -rf "$TMP_DIR"
rm -rf "$INSTALL_DIR"
