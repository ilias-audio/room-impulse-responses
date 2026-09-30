#!/bin/bash
#SBATCH -p gpushort
#SBATCH -t 1:0:0
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-cpu=11G
#SBATCH --gres=gpu:1
#SBATCH -o qlogs/garr_%A_%a.out
#SBATCH -e qlogs/garr_%A_%a.err

# Short GPU array job: one shard per task (SLURM_ARRAY_TASK_ID).
#   PIXI_ENV=embed sbatch --array=0-7 jobs/gpu_array.sh pixi run -e embed rirdb embed sriracha --shard auto

export PATH="$HOME/.pixi/bin:$PATH"
source jobs/_preamble.sh

if [ $# -eq 0 ]; then
    echo "Usage: sbatch jobs/quick_gpu.sh <command...>"
    exit 1
fi

"$@"
