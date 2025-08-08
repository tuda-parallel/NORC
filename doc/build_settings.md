# Build Settings

Build settings can be found in `acquisition/config/build_settings.sh`.

`BUILD_JOBS` should be set to a thread count supported on the system the installation will run on.

Score-P and PAPI can be acquired with Spack or in a user-defined manner (typically module load).
To use Spack, set `USE_SPACK` to true. If this is not set they should be loaded in `acquisition/config/modules.sh`.