#!/bin/bash
#SBATCH -p compute
#SBATCH -t 48:0:0
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem-per-cpu=2G
#SBATCH -o qlogs/dl_%j.out
#SBATCH -e qlogs/dl_%j.err

# Network layer as a batch job (bash + curl only, no Python). Only usable if
# jobs/net_probe.sh showed compute nodes have internet (see docs/hpc.md).
#   sbatch jobs/download.sh fetch/fetch.sh --wave 1

if [ -f ./.env ]; then
    set -a; source ./.env; set +a
fi

if [ $# -eq 0 ]; then
    echo "Usage: sbatch jobs/download.sh fetch/fetch.sh <args...>"
    exit 1
fi

"$@"
