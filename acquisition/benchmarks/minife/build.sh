#!/bin/bash

source "$CONFIG_DIR/build_settings.sh"
source "$BASE_DIR/util/macros.sh"

pushd "$TMP_DIR"

if [ ! -d miniFE ]; then
  git clone https://github.com/Mantevo/miniFE.git
  check_failure "Failed to clone MiniFE"
fi

# There are several different implementations of MiniFE supporting different concurrency schemes.
# These may be used as separate benchmarks.
cd miniFE/openmp/src
make CC=scorep-mpicc CXX=scorep-mpicxx -j $BUILD_JOBS
check_failure "Failed to make MiniFE"

cp miniFE.x "$INSTALL_DIR/bin/minife"

exit_success "Successfully installed MiniFE"