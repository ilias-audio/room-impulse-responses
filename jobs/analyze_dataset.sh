#!/bin/bash
# Submit the analysis of one dataset as a SLURM array + a dependent merge job.
# Bash only (runs on the login node); every Python step runs inside sbatch.
#
#   jobs/analyze_dataset.sh <dataset_id> <n_shards> [extra rirdb analyze args, e.g. --full]
set -euo pipefail
cd "$(dirname "$0")/.."
ds=$1; n=$2; shift 2
max=$((n - 1))
arr=$(sbatch --parsable --array=0-${max}%50 -J "an_${ds}" jobs/cpu_array.sh \
      pixi run rirdb analyze --dataset "$ds" --shard auto "$@")
mrg=$(sbatch --parsable --dependency=afterok:${arr} -p computeshort -t 0:30:0 -J "mg_${ds}" \
      jobs/quick_cpu.sh pixi run rirdb merge "$ds")
echo "$ds: analyze array $arr ($n shards), merge $mrg"
