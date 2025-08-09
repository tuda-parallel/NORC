#!/bin/bash

# This needs to be sourced to have any effect

# Spack doesn't require building so it can just be cloned into the build directory
pushd "$INSTALL_DIR"

if [ ! -d "spack" ]; then
  print_info "Downloading Spack"
  git clone -c feature.manyFiles=true https://github.com/spack/spack.git
  check_failure "Failed to download Spack"
else
  print_info "Spack is already installed"
fi

#if spack exist prior, unload it
if ! command -v spack >/dev/null 2>&1; then
  if [ -f ../config/force_local_run ]; then
    # Remove Spack shell functions
    unset -f spack
    unset SPACK_ROOT
    unset SPACK_ENV
    unset SPACK_USER_CACHE
  else
    module unload spack
  fi
fi

# Always use local Spack regardless of system install
export SPACK_ROOT=$(pwd)/spack
source "$SPACK_ROOT/share/spack/setup-env.sh"
check_failure "Failed to setup environment for using Spack"
# add new compilers to spack

if ! spack compiler find; then
  spack compiler find /usr/bin /bin /usr/local/bin
  check_failure "Failed to setup compilers for using Spack"
fi

print_success "Successfully installed Spack"
popd
