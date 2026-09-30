#!/bin/bash
# Validate a candidate registry in a job, then atomically replace registry/datasets.yaml.
# Queued jobs that were not submitted with a pinned copy read the live file, so it
# must never be invalid, even briefly.
#
#   cp registry/datasets.yaml .scratch/datasets.next.yaml; <edit it>; jobs/registry_swap.sh .scratch/datasets.next.yaml
set -euo pipefail
cd "$(dirname "$0")/.."
cand=$(realpath "$1")
j=$(sbatch --parsable --wait -p computeshort -t 0:15:0 --export=ALL,RIRDB_REGISTRY="$cand" \
    jobs/quick_cpu.sh pixi run rirdb registry list) || { echo "validation job $j failed:"; tail -5 "qlogs/cpu_$j.err"; exit 1; }
mv "$cand" registry/datasets.yaml
echo "registry replaced (validated by job $j)"
