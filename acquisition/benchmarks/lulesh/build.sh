#!/bin/bash

source "$CONFIG_DIR/build_settings.sh"
source "$BASE_DIR/util/macros.sh"

pushd "$TMP_DIR"

if [ ! -d LULESH ]; then
  git clone https://github.com/LLNL/LULESH.git
  check_failure "Failed to download LULESH"
fi

cd LULESH

# Default CXXFlags enable OpenMP as well
make "CXX=scorep-mpicxx -DUSE_MPI=1"
check_failure "Failed to build LULESH"

cp lulesh2.0 "$INSTALL_DIR/bin/lulesh"

exit_success "Successfully built LULESH"
