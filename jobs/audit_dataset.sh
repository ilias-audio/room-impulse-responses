#!/bin/bash
# Signal-integrity audit of one analysed dataset: SLURM array + dependent merge (registry pinned).
#   jobs/audit_dataset.sh <dataset_id> <n_shards>
set -euo pipefail
cd "$(dirname "$0")/.."
ds=$1; n=$2
snap="$PWD/qlogs/registry_$(date +%Y%m%dT%H%M%S)_${ds}_audit.yaml"
cp registry/datasets.yaml "$snap"
arr=$(sbatch --parsable --export=ALL,RIRDB_REGISTRY="$snap" --array=0-$((n - 1))%50 -J "au_${ds}" jobs/cpu_array.sh \
      pixi run rirdb audit --dataset "$ds" --shard auto --n-shards "$n")
mrg=$(sbatch --parsable --export=ALL,RIRDB_REGISTRY="$snap" --dependency=afterok:${arr} -p computeshort -t 0:20:0 \
      -J "am_${ds}" jobs/quick_cpu.sh pixi run rirdb audit-merge "$ds")
echo "$ds: audit array $arr ($n shards), merge $mrg"
