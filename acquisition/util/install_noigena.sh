#!/bin/bash

source "$CONFIG_DIR/build_settings.sh"
source "$BASE_DIR/util/macros.sh"

if [ "$BASE_DIR/config/noigena_cfg.yaml" -ot "$INSTALL_DIR/bin/NOIGENA" ]; then
  print_success "No changes to noise patterns detected. Skipping NOIGENA build"
  exit 0
fi

source "$TMP_DIR/.venv/bin/activate"

if [ ! -d "$TMP_DIR/noigena" ]; then
  git clone https://codebase.helmholtz.cloud/g.corbin/noigena-tool.git "$TMP_DIR/noigena" || echo "NOIGENA Repo exists"
  check_failure "No Noigena folder found"
else
  echo "NOIGENA Repo already exists"
fi

pushd "$TMP_DIR"

cd noigena
check_failure "Failed to navigate to Noigena directory"
cp "$BASE_DIR/config/noigena_cfg.yaml" .
check_failure "Noigena config (noigena_cfg.yaml) missing"

chmod +x noigena.sh
# Noigena has to be rebuilt when reconfigured and old binaries may not work in every environment
./noigena.sh --clean
./noigena.sh --usercfg
check_failure "Failed to configure Noigena"
(
source ./noigena.sh
check_prerequisite_modules
if [ $prerequisite_modules_set = "False" ]; then
  exit 1
fi
)
check_failure "Failed to find prerequisites. SIONLIB and MPI are required."
./noigena.sh --make
check_failure "Failed to build Noigena"
cp NOIGENA "$INSTALL_DIR/bin/"

exit_success "Successfully installed Noigena"
