#!/bin/bash
#SBATCH -J RELeARN
#SBATCH -o %x.%j
#SBATCH -A l0003185
#SBATCH -n 4
#SBATCH -c 12
#SBATCH --mem-per-cpu=3GB
#SBATCH -t 00:10:00

spack load gcc@14.2.0%gcc@11.4.1 openmpi@4.1.7%gcc@14.2.0/sqakqfv boost@1.86.0/uwyzbdx

num_neurons=50000
steps=50000
ranks=$SLURM_NTASKS
threads=12
rep=0

export SCOREP_MACHINE_NAME="Lichtenberg II"
#export SCOREP_ENABLE_PROFILING=false
#export SCOREP_EXPERIMENT_DIRECTORY="relearn.n$num_neurons.s$steps.p$ranks.t$threads.r$rep"
srun -c $threads ./relearn --steps $steps --algorithm barnes-hut --num-neurons-per-rank $num_neurons --openmp $threads --no-print-positions --no-print-network --no-print-plasticity --no-print-calcium --no-print-fire-rate --no-print-fire-steps --no-print-overview --no-print-mapping --no-print-neuron-to-groups --no-print-group-name-to-file-name --no-print-sums