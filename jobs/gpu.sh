#!/bin/bash
#SBATCH -p sae
#SBATCH -A pilot_sae_gpu
#SBATCH -t 12:0:0
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-cpu=11G
#SBATCH --gres=gpu:1
#SBATCH -o qlogs/gpu_%j.out
#SBATCH -e qlogs/gpu_%j.err

# Longer GPU job (full-corpus embeddings) on the sae partition (account pilot_sae_gpu,
# shared with FDN2FDN training: prefer several gpushort jobs when they fit in 1 h).
#   PIXI_ENV=embed sbatch jobs/gpu.sh pixi run -e embed rirdb embed --wave 1

export PATH="$HOME/.pixi/bin:$PATH"
source jobs/_preamble.sh

if [ $# -eq 0 ]; then
    echo "Usage: sbatch jobs/gpu.sh <command...>"
    exit 1
fi

"$@"
