#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH -t 6:0:0
#SBATCH --mem-per-cpu=8G
#SBATCH -o qlogs/cpu_%j.out
#SBATCH -e qlogs/cpu_%j.err

# Generic CPU job: tests, registry compile, index, merge, reports, extraction.
#   sbatch jobs/quick_cpu.sh pixi run rirdb verify --wave 1
#   sbatch -p computeshort -t 1:0:0 jobs/quick_cpu.sh pixi run test

# Ensure pixi is on PATH (SLURM batch jobs don't source ~/.bashrc).
export PATH="$HOME/.pixi/bin:$PATH"
# Process pools do the parallelism; stop BLAS from oversubscribing the cores.
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# CPU nodes have no CUDA driver; the pytorch-gpu build still runs on CPU.
export CONDA_OVERRIDE_CUDA=12.6

if [ -f ./.env ]; then
    set -a; source ./.env; set +a
fi

if [ $# -eq 0 ]; then
    echo "Usage: sbatch jobs/quick_cpu.sh <command...>"
    echo "Example: sbatch jobs/quick_cpu.sh pixi run test"
    exit 1
fi

"$@"
