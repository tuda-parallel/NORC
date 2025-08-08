source "$CONFIG_DIR/build_settings.sh"
source "$BASE_DIR/util/macros.sh"

pushd "$TMP_DIR"

# acquire LAMMPS from its repository
if [ ! -d lammps ]; then
  print_info "Downloading LAMMPS"
  git clone -b stable https://github.com/lammps/lammps.git lammps
  check_failure "Failed to clone LAMMPS"
else
  print_info "LAMMPS directory already exists. Not re-downloading."
fi

cd lammps
if [ ! -f OPARI_patched ]; then
  patch src/OPENMP/fix_omp.cpp <<EOL
--- lammps/src/OPENMP/fix_omp.cpp
+++ lammps/src/OPENMP/fix_omp.cpp
@@ -70,11 +70,12 @@
   int nthreads = 1;
   if (narg > 3) {
 #if defined(_OPENMP)
-    if (strcmp(arg[3],"0") == 0)
+    if (strcmp(arg[3],"0") == 0) {
 #pragma omp parallel LMP_DEFAULT_NONE LMP_SHARED(nthreads)
       nthreads = omp_get_num_threads();
-    else
+    } else {
       nthreads = utils::inumeric(FLERR,arg[3],false,lmp);
+    }
 #endif
   }
EOL
  check_failure "Failed to patch LAMMPS for profiling with Score-P."
  touch OPARI_patched
fi

mkdir -p _build
cd _build

# configure
SCOREP_WRAPPER=off cmake \
  -DBUILD_MPI=yes \
  -DBUILD_OMP=yes \
  -DPKG_SRD=yes \
  -DPKG_OPENMP=yes \
  -DENABLE_MPI=On \
  -DCMAKE_C_COMPILER=scorep-mpicc \
  -DCMAKE_CXX_COMPILER=scorep-mpicxx \
  ../cmake
check_failure "Failed to configure LAMMPS"

# build
SCOREP_WRAPPER_COMPILER_FLAGS="-DSCOREP_ENABLED=1 -fopenmp" make -j $BUILD_JOBS
check_failure "Failed to build LAMMPS"

# place executable in executable directory under the benchmark's name
cp lmp "$INSTALL_DIR/bin/lammps"

# Create experiment tree

check_failure "Failed to create benchmark LAMMPS"

exit_success "Successfully installed LAMMPS"
