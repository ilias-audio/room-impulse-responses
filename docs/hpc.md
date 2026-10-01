# HPC (Apocrita)

## Critical rule

**Every Python invocation goes through `sbatch`.** Bare `python`, `pixi run python`
or `pixi run rirdb` on the login node destabilises the shared system. This matches
`../FDN2FDN/docs/hpc.md`.

The only things that run directly on the login node are:

- `pixi install` (package download, not Python compute);
- the network layer in `fetch/*.sh` (bash + curl + jq, low CPU), ideally inside
  `tmux` and with `nice -n19`, **only if compute nodes have no internet** (see below);
- `git`, `squeue`, `sbatch`, reading logs.

## Job scripts

| Script | Use for | Partition | Time | Resources |
|---|---|---|---|---|
| `jobs/quick_cpu.sh` | tests, registry compile, index, merge, reports, extraction | default (`compute`) | 6 h | 8 CPU, 8 G/CPU |
| `jobs/cpu_array.sh` | sharded analysis (`--shard auto` reads `SLURM_ARRAY_TASK_ID`) | default | 6 h/task | 4 CPU, 4 G/CPU |
| `jobs/quick_gpu.sh` | embedding smoke tests | `gpushort` | 1 h | 1 GPU |
| `jobs/gpu.sh` | long embedding runs | `sae` (account `pilot_sae_gpu`; the `gpu` partition is not available to this account) | 12 h | 1 GPU |
| `jobs/net_probe.sh` | checks compute-node internet (no Python) | `computeshort` | 10 min | 1 CPU |
| `jobs/download.sh` | network layer as a batch job (bash only) | `compute` | 48 h | 2 CPU |

Every script exports `PATH="$HOME/.pixi/bin:$PATH"`, sources `.env` (for
`RIRDB_ROOT`), then runs `"$@"`. CPU scripts set `OMP_NUM_THREADS=1` so that
process pools do not oversubscribe cores.

## Usage

```bash
sbatch jobs/quick_cpu.sh pixi run test
sbatch -p computeshort -t 1:0:0 jobs/quick_cpu.sh pixi run rirdb registry compile
jobs/analyze_dataset.sh openair 16                     # analysis array + merge (registry pinned)
EMBED_SHARDS=2 jobs/analyze_dataset.sh soundcam 4      # ... + CLAP embeddings after the merge
TASKS=50-79 jobs/analyze_dataset.sh arni 80            # re-run some shards with the full shard count
```

Short jobs (< 1 h) queue much faster on `computeshort`: override with
`sbatch -p computeshort -t 1:0:0 ...`.

## Registry and running jobs

Jobs import the code and read `registry/datasets.yaml` from the working tree
when they start, not when they are submitted. A registry that is invalid for a
few minutes fails every task that starts in that window (this happened once:
30 analysis and 38 embedding tasks). Two safeguards:

- `jobs/analyze_dataset.sh` copies the registry to `qlogs/registry_<time>_<id>.yaml`
  at submission and the jobs read the copy (`RIRDB_REGISTRY`). Pass the same
  `--export=ALL,RIRDB_REGISTRY=<copy>` when submitting arrays by hand.
- Edit a copy and swap it in only after a job has validated it:
  `cp registry/datasets.yaml .scratch/datasets.next.yaml`, edit, then
  `jobs/registry_swap.sh .scratch/datasets.next.yaml`.

When re-running part of an array, pass `--n-shards N` (or use `TASKS=`):
`--shard auto` otherwise infers the shard count from the partial array.
`rirdb merge` only merges one complete shard set with a single analyzer config.

## Monitoring

```bash
squeue -u $USER
tail -f qlogs/cpu_<JOBID>.out
cat qlogs/cpu_<JOBID>.err
scancel <JOBID>
```

## Environment install

```bash
CONDA_OVERRIDE_CUDA=12.6 pixi install -e default -e embed
```

The login node has no GPU, so `CONDA_OVERRIDE_CUDA` is needed to solve the
`pytorch-gpu` build. The same env runs on CPU nodes.

## Storage (scratch)

- Data root: `$RIRDB_ROOT=/gpfs/scratch/eey119/rir-data` (never in git).
- Quota (`mmlsquota -u eey119 gpfsFlash`): **3 TB soft / 6 TB hard, 10 M files**.
- Scratch files are **deleted 65 days after last modification**. The fetch layer
  extracts with `unzip -DD` / `tar --touch` so extracted files get fresh mtimes,
  and all locks + manifests are in git so `rirdb verify` can detect purged files
  and `fetch/fetch.sh` can re-download them.
- This git working copy is on scratch too: push after every phase.

## Compute-node internet

**Yes** (probe job 29569651 on `ddy122`, 2026-09-30): no proxy needed; Zenodo,
DepositOnce, figshare, Hugging Face, York (OpenAIR), conda-forge and PyPI all
returned HTTP 200. A 100 MB ranged Zenodo download ran at ~11 MB/s.

So the network layer runs as a batch job:

```bash
sbatch jobs/download.sh fetch/fetch.sh --wave 1
```

Keep at most ~4 concurrent transfers per host.
