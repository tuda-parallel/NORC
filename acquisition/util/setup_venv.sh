#!/bin/bash

pip(){
  command pip $*
  check_failure "Command failed: pip $*"
}

pushd "$TMP_DIR"

export BUILD_VENV_DIR="./.venv"
mkdir -p "$BUILD_VENV_DIR"
globalize "BUILD_VENV_DIR"

if [ -d "BUILD_VENV_DIR" ]; then
  print_info "build virtual environment already exists"
else
  python -m venv "$BUILD_VENV_DIR"
fi
chmod +x "$BUILD_VENV_DIR/bin/activate"
check_failure "Failed to set up virtual environment for building"
source "$BUILD_VENV_DIR/bin/activate"
check_failure "Failed to activate virtual environment for building"

# pip modules for building
pip install PyYaml

print_success "Successfully set up virtual python environment for building"
popd

# Environment and settings for running
pushd "$INSTALL_DIR"

export EXEC_VENV_DIR="./.venv"
mkdir -p "$EXEC_VENV_DIR"
globalize "EXEC_VENV_DIR"

if [ -d "EXEC_VENV_DIR" ]; then
  print_info "execution virtual environment already exists"
else
  python -m venv "$EXEC_VENV_DIR"
fi
chmod +x "$EXEC_VENV_DIR/bin/activate"
check_failure "Failed to set up virtual environment for running"

# pip modules for running
# echo "pip install ..." >> "$INIT_SCRIPT"

echo "source $EXEC_VENV_DIR/bin/activate"

# This file must be sourced in order to see the venv variables so we can't exit here.
print_success "Successfully set up virtual python environment for running"
popd