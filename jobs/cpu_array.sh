#!/bin/bash
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH -t 6:0:0
#SBATCH --mem-per-cpu=6G
#SBATCH -o qlogs/arr_%A_%a.out
#SBATCH -e qlogs/arr_%A_%a.err

# Sharded analysis: each array task processes shard $SLURM_ARRAY_TASK_ID.
#   sbatch --array=0-N%50 jobs/cpu_array.sh pixi run rirdb analyze --dataset X --shard auto
# Keep arrays <= 1000 tasks.

export PATH="$HOME/.pixi/bin:$PATH"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
# CPU nodes have no CUDA driver; the pytorch-gpu build still runs on CPU.
export CONDA_OVERRIDE_CUDA=12.6

if [ -f ./.env ]; then
    set -a; source ./.env; set +a
fi

if [ $# -eq 0 ]; then
    echo "Usage: sbatch --array=0-N jobs/cpu_array.sh <command...>"
    exit 1
fi

"$@"
