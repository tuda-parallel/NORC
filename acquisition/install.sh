#!/bin/bash
source util/macros.sh

BASE_DIR=$(pwd)
export BASE_DIR
export CONFIG_DIR="$BASE_DIR/config"

source "$CONFIG_DIR/build_settings.sh"

##########################LOCATIONS#########################
export INSTALL_DIR=build
export TMP_DIR=tmp

###########################ENVIRONMENT######################
# Overrides the system path at the start of setup.
# Adding to this may introduce ambiguity and surprises.
export CLEAN_PATH=/bin:/usr/sbin

###########################Globalization####################
mkdir -p "$INSTALL_DIR"
globalize "INSTALL_DIR"
mkdir -p "$INSTALL_DIR/bin"
mkdir -p "$INSTALL_DIR/lib"

mkdir -p "$TMP_DIR"
globalize "TMP_DIR"

export PATH="$CLEAN_PATH"

# Add installed programs and libraries to the path so other scripts can use them
export PATH="$INSTALL_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$INSTALL_DIR/lib:$LD_LIBRARY_PATH"

do_install=true
quiet=false

# Parse command line options
while getopts "fsq" opt; do
  case "${opt}" in
  f)
    print_info "-f specified. Force-rebuilding everything."
    util/clean.sh                          # deleting the old installation forces rebuild
    source "$CONFIG_DIR/build_settings.sh" # recreate deleted folders
    ;;
  s)
    print_info "-s specified. Skipping installation."
    do_install=false
    ;;
  q)
    print_info "-q specified. Skipping interactive prompts."
    quiet=true
    ;;
  *)
    print_warning "Unknown flag $opt found."
    ;;
  esac
done

if [ ! -f "$CONFIG_DIR/config_done" ] && ! $quiet; then
  read -p "Is the configuration updated for this system? [y,N] " -n 1 -r
  echo # (optional) move to a new line
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    chmod +x ./util/config_assistent.sh
    ./util/config_assistent.sh
    check_failure "Configuration not finalized!"
  fi
  touch "$CONFIG_DIR/config_done"
fi

# source again the new build settings
source "$CONFIG_DIR/build_settings.sh"
if [ -f experiment/config/force_local_run ]; then
  LOCAL_RUN=true
else
  LOCAL_RUN=false
fi

# only source modules on cluster
if [ $LOCAL_RUN = true ]; then
  echo "Local installation. Skipping loading modules"
else
  echo "Loading modules"
  source "$CONFIG_DIR/modules.sh"
fi

# The installation directory may be anywhere and doesn't know where the original files are
cp util/macros.sh "$INSTALL_DIR"

# Put something on the stack to prevent exit functions from producing irrelevant popd errors
pushd .

if [ ! -d "$TMP_DIR/.venv" ]; then
  $python_cmd -m venv "$TMP_DIR/.venv"
  source "$TMP_DIR/.venv/bin/activate"
  pip install numpy
  pip install PyYaml
else
  source "$TMP_DIR/.venv/bin/activate"
fi

# The environment script contains variables that are supposed to be present at execution
export ENV_SCRIPT="$INSTALL_DIR/env.sh"
cat >"$ENV_SCRIPT" <<EOL
#!/bin/bash

# Basic environment for running and evaluating benchmarks.
# This script should be sourced before running benchmarks.

EOL
# The init script contains commands to be run before execution
export INIT_SCRIPT="$INSTALL_DIR/init.sh"
cat >"$INIT_SCRIPT" <<EOL
#!/bin/bash

source ./env.sh
EOL

chmod +x "$ENV_SCRIPT"
chmod +x "$INIT_SCRIPT"

print_info "Installing into target directory $INSTALL_DIR"

if $do_install; then
  # Setup virtual environment for Python scripts
  # TODO: Do we really need this? Maybe make this a setting as it takes some time.
  #source util/setup_venv.sh
  #check_failure "Failed to initialize virtual environment"

  # Spack
  if [ $USE_SPACK = true ]; then
    #TODO: This shouldn't be affected by Score-P settings
    source util/install_spack.sh

    # Score-P with PAPI
    print_info "Installing Score-P with Spack."
    spack install scorep@$SCOREP_VERSION +papi +mpi $SPACK_VERSION_SUFFIX
    check_failure "Failed to install Score-P with Spack."
    spack load scorep@$SCOREP_VERSION $SPACK_VERSION_SUFFIX
    check_failure "Spack could install Score-P but not load it."
    cp "$(which scorep-score)" "$INSTALL_DIR/bin"
    check_failure "Failed to place scorep-score in experiment bin directory"
    print_success "Successfully installed Score-P."

    # PAPI
    spack load papi $SPACK_VERSION_SUFFIX
    check_failure "Spack could not load PAPI."
    cp "$(which papi_avail)" "$INSTALL_DIR/bin"
    check_failure "Failed to place papi_avail in experiment bin directory"
    cp "$(which papi_event_chooser)" "$INSTALL_DIR/bin"
    check_failure "Failed to place papi_event_chooser in experiment bin directory"

    # SIONlib
    print_info "Installing SIONlib with Spack."
    spack install sionlib fflags="-fallow-argument-mismatch" $SPACK_VERSION_SUFFIX
    check_failure "Failed to install SIONlib with Spack."
    spack load sionlib fflags="-fallow-argument-mismatch" $SPACK_VERSION_SUFFIX
    check_failure "Spack could install SIONlib but not load it."
    cp "$(which sionconfig)" "$INSTALL_DIR/bin"
    check_failure "Failed to place sionconfig in experiment bin directory"
    print_success "Successfully installed SIONlib."

    # CMake
    print_info "Installing CMake with Spack."
    spack install cmake $SPACK_VERSION_SUFFIX
    check_failure "Failed to install CMake with Spack."
    spack load cmake $SPACK_VERSION_SUFFIX
    check_failure "Spack could install CMake but not load it."
    print_success "Successfully installed CMake."

  fi

  # Noigena is always built since it's configured at build time and doesn't take much time to build anyway
  chmod +x util/install_noigena.sh
  util/install_noigena.sh
  check_failure "Setup failed for NOIGENA"

fi

export PATH="$INSTALL_DIR/bin:$PATH"

# Make the system environment at runtime as restrictive as possible so the programs
# run are the ones just built and not some preexisting version we have no control over
cat >>"$ENV_SCRIPT" <<EOL
export PATH="$PATH"
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH"
export SCOREP_ENABLE_PROFILING="true"
export SCOREP_ENABLE_TRACING="false"
EOL

if [ $USE_SPACK = true ]; then
  cat >>"$ENV_SCRIPT" <<EOL

source "$INSTALL_DIR/spack/share/spack/setup-env.sh"
spack load mpi
EOL
fi

# The temporary binary directory shall only be known at build time and is therefore specified after the environment file is written.
mkdir -p "$TMP_DIR/bin"
export PATH="$PATH:$TMP_DIR/bin"

# Spack calls its Score-P MPI C++ compiler "scorep-mpic++" while other programs tend to call it "scorep-mpicxx".
# Regardless how it's called in this case and for what reason, we create an alias for it so that it can
# always be called as "scorep-mpicxx".
which scorep-mpicxx >/dev/null
if [ $? -ne 0 ]; then
  which scorep-mpic++ >/dev/null
  check_failure "No Score-P MPI C++ compiler found. Expected either 'scorep-mpicxx' or 'scorep-mpic++'."
  ln -s "$(which scorep-mpic++)" "$TMP_DIR/bin/scorep-mpicxx"
fi

which papi_avail >/dev/null
check_failure "No PAPI command found."

if { [ ! -f "$CONFIG_DIR/config_done" ] || [ "$(cat "$CONFIG_DIR/config_done")" != "metrics" ]; } && ! $quiet; then
  read -p "Are the hardware counters configured to match this system? [y,N] " -n 1 -r
  echo # (optional) move to a new line
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    ./util/config_assistent.sh metrics
    check_failure "Configuration not finalized!"
  fi
  echo "metrics" >"$CONFIG_DIR/config_done"
fi

################################################# Experiment Structure #################################################

EXPERIMENT_DIR="$INSTALL_DIR/experiment"

# Remove old experiments that may interfere with the new ones
rm -rf "$EXPERIMENT_DIR"
mkdir -p "$EXPERIMENT_DIR"

# Place central configuration into the experiment directory
cp -r "$BASE_DIR/config" "$EXPERIMENT_DIR"
ensure_newline "$EXPERIMENT_DIR/config/experiments.cfg"
ensure_newline "$EXPERIMENT_DIR/config/metrics.cfg"
ensure_newline "$EXPERIMENT_DIR/config/noise.cfg"

# Put run script in the build directory for execution
cp -r runner/* "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/run_benchmarks.sh"
chmod +x "$INSTALL_DIR"/fake_slurm/*

# Create per-benchmark configuration directory
mkdir -p "$EXPERIMENT_DIR/config/benchmarks"

# only source modules on cluster
if [ $LOCAL_RUN = true ]; then
  echo "Local installation. Skipping loading modules"
else
  echo "Loading modules"
  source "$CONFIG_DIR/modules.sh"
fi

# Automatically install all specified benchmarks
for benchmark_dir in ./benchmarks/*; do
  benchmark=$(basename "$benchmark_dir")

  # Skip if it's the 'template' directory
  if [ "$benchmark" = "template" ]; then
    continue
  fi

  # Skip if not a directory
  if [ ! -d "$benchmark_dir" ]; then
    continue
  fi

  # Skip if 'build.sh' is missing
  if [ ! -f "$benchmark_dir/build.sh" ]; then
    continue
  fi

  # At this point, $benchmark_dir is valid
  echo "Processing benchmark: $benchmark"

  # Put the resources where the runner expects them
  cp -rf "./benchmarks/$benchmark" "$EXPERIMENT_DIR/config/benchmarks/"
  rm -f "$EXPERIMENT_DIR/config/benchmarks/$benchmark/build.sh" # The runner doesn't need the build script

  # Build the benchmark
  if [ -f "$INSTALL_DIR/bin/$benchmark" ]; then
    print_success "$benchmark is already installed"
    continue
  fi
  chmod +x "./benchmarks/$benchmark/build.sh"
  "./benchmarks/$benchmark/build.sh"
  check_failure "Failed to build $benchmark"

done

chmod +x run.sh
exit_success "Successfully installed all components."
