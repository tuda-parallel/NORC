#!/bin/bash

source "$CONFIG_DIR/build_settings.sh"
source "$BASE_DIR/util/macros.sh"

pushd "$TMP_DIR"

APP_FOLDER="tmp"

if [ ! -d $APP_FOLDER ]; then
  git clone https://github.com/<path>.git $APP_FOLDER
  check_failure "Failed to clone $APP_FOLDER"
fi

# build as usual
cd $APP_FOLDER
make CC=scorep-mpicc CXX=scorep-mpicxx -j $BUILD_JOBS
check_failure "Failed to make $APP_FOLDER"

cp EXECUTABLE_NAME "$INSTALL_DIR/bin/$APP_FOLDER"

exit_success "Successfully installed $APP_FOLDER"
