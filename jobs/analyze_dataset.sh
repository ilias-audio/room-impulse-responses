#!/bin/bash
# Submit the analysis of one dataset as a SLURM array + a dependent merge job.
# Bash only (runs on the login node); every Python step runs inside sbatch.
#
#   jobs/analyze_dataset.sh <dataset_id> <n_shards> [extra rirdb analyze args, e.g. --full]
#   TASKS=50-79 jobs/analyze_dataset.sh arni 80     # re-run some shards of an 80-shard run
#
# The registry is copied at submission and the jobs read that copy (RIRDB_REGISTRY),
# so editing registry/datasets.yaml cannot break queued or running tasks.
set -euo pipefail
cd "$(dirname "$0")/.."
ds=$1; n=$2; shift 2
tasks=${TASKS:-0-$((n - 1))}
snap="$PWD/qlogs/registry_$(date +%Y%m%dT%H%M%S)_${ds}.yaml"
cp registry/datasets.yaml "$snap"
arr=$(sbatch --parsable --export=ALL,RIRDB_REGISTRY="$snap" --array=${tasks}%50 -J "an_${ds}" jobs/cpu_array.sh \
      pixi run rirdb analyze --dataset "$ds" --shard auto --n-shards "$n" "$@")
mrg=$(sbatch --parsable --export=ALL,RIRDB_REGISTRY="$snap" --dependency=afterok:${arr} -p computeshort -t 0:30:0 \
      -J "mg_${ds}" jobs/quick_cpu.sh pixi run rirdb merge "$ds")
echo "$ds: analyze array $arr (tasks $tasks of $n shards), merge $mrg"
