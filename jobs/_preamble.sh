#!/bin/bash
# Shared preamble for GPU jobs (embeddings). Sourced, not executed, inside
# jobs/quick_gpu.sh and jobs/gpu.sh on the compute node, before Python.
#   - Load .env (RIRDB_ROOT, HF_HOME).
#   - Load the CUDA toolchain matching pixi's pytorch-gpu build.
#   - Fail fast if PyTorch cannot see the GPU.

set -e

if [ -f ./.env ]; then
    set -a; source ./.env; set +a
fi

module load cuda/12.6 cudnn/9.2
unset LD_LIBRARY_PATH

pixi run ${PIXI_ENV:+-e $PIXI_ENV} python -c "
import torch
print('torch', torch.__version__, 'cuda build:', torch.version.cuda)
assert torch.cuda.is_available(), 'CUDA NOT available — aborting'
print('device:', torch.cuda.get_device_name(0))
"
