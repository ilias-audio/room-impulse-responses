#!/bin/bash
#SBATCH -p gpushort
#SBATCH -t 1:0:0
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-cpu=11G
#SBATCH --gres=gpu:1
#SBATCH -o qlogs/quick_%j.out
#SBATCH -e qlogs/quick_%j.err

# Short GPU job (smoke tests of the embedding pipeline).
#   PIXI_ENV=embed sbatch jobs/quick_gpu.sh pixi run -e embed rirdb embed --dataset mit_survey

export PATH="$HOME/.pixi/bin:$PATH"
source jobs/_preamble.sh

if [ $# -eq 0 ]; then
    echo "Usage: sbatch jobs/quick_gpu.sh <command...>"
    exit 1
fi

"$@"
