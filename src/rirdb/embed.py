"""Learned audio embeddings (CLAP) of every analysed IR (GPU; `-e embed` env).

Per IR (onset-aligned, first analysed channel, 48 kHz, peak-normalised):
  - "ir":            the IR itself, zero-padded / cropped to exactly 10 s
  - "<SOURCE>":      each dry reference signal convolved with the IR (first 10 s, RMS-normalised)
  - "reverb_vector": mean over sources of emb(source * IR) - emb(source)

Inputs are made exactly 10 s long before the feature extractor sees them, so
its default repeat-padding / random-crop paths never run (the defaults would
repeat or randomly crop an IR). Model: laion/clap-htsat-unfused, as FDN2FDN.

Output: $RIRDB_ROOT/embeddings/<model>/<dataset>.npz with `ir_id` and one
float16 [n_ir, 512] array per signal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from rirdb import paths

MODEL = "laion/clap-htsat-unfused"
SR = 48000
N = 10 * SR
SOURCES_DIR = Path("/gpfs/scratch/eey119/FDN2FDN/learn-fdn-iir/AUDIO/SOURCE")
SOURCES = ["SPEECH", "VOCAL", "PIANO", "DRUMS", "AC_GTR", "ELEC_GTR"]


def _fix(x: np.ndarray) -> np.ndarray:
    y = np.zeros(N, dtype=np.float32)
    y[: min(N, len(x))] = x[:N]
    return y


def load_sources() -> tuple[dict[str, np.ndarray], dict[str, str]]:
    import soundfile as sf
    import soxr

    out, sums = {}, {}
    for name in SOURCES:
        p = SOURCES_DIR / f"{name}.wav"
        sums[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        x, fs = sf.read(str(p), dtype="float64", always_2d=True)
        x = x.mean(axis=1)
        if fs != SR:
            x = soxr.resample(x, fs, SR)
        out[name] = _fix(x / (np.sqrt(np.mean(x ** 2)) + 1e-12))
    return out, sums


class Embedder:
    def __init__(self, device: str = "cuda"):
        import torch
        from transformers import ClapModel, ClapProcessor

        self.torch = torch
        self.device = device
        self.model = ClapModel.from_pretrained(MODEL).to(device).eval()
        self.proc = ClapProcessor.from_pretrained(MODEL)

    def __call__(self, audios: list[np.ndarray]) -> np.ndarray:
        inp = self.proc(audio=audios, sampling_rate=SR, return_tensors="pt")
        inp = {k: v.to(self.device) for k, v in inp.items()}
        with self.torch.no_grad():
            e = self.model.get_audio_features(**inp)
        return e.float().cpu().numpy()


def _ir_signal(row: dict, adapter, root: Path, d, cfg) -> np.ndarray | None:
    import soxr

    from rirdb.analysis.preprocess import prepare
    from rirdb.run import _select_channels

    x, fs = adapter.load(json.loads(row["locator"]), root)
    roles = tuple(row["channel_roles"].split(","))
    xs, _ = _select_channels(x, roles, row.get("reference_role") or d.analysis.reference_role)
    p = prepare(xs[:1], fs, cfg)
    if p.x.shape[1] < 16:
        return None
    ir = p.x[0]
    if fs != SR:
        ir = soxr.resample(ir, fs, SR)
    peak = np.max(np.abs(ir))
    return (ir / peak).astype(np.float32) if peak > 0 else None


def embed_dataset(dataset_id: str, batch: int = 16, device: str = "cuda", shard: int = 0, n_shards: int = 1) -> Path:
    import torch

    from rirdb.adapters import get_adapter
    from rirdb.analysis.config import load_config
    from rirdb.registry import get_dataset
    from rirdb.run import metrics_dir

    d = get_dataset(dataset_id)
    adapter = get_adapter(d.adapter.name, d.adapter.params)
    root = paths.files_dir(dataset_id)
    cfg = load_config()
    idx = pd.read_parquet(paths.data_root() / "index" / "irs" / f"dataset={dataset_id}" / "part-0.parquet")
    done = pd.read_parquet(metrics_dir(dataset_id) / "wide.parquet", columns=["ir_id", "error"])
    ids = set(done.loc[done["error"].fillna("") == "", "ir_id"])
    rows = idx[idx["ir_id"].isin(ids)].sort_values("ir_id").to_dict("records")[shard::n_shards]

    emb = Embedder(device)
    sources, sums = load_sources()
    dry = {k: v for k, v in zip(SOURCES, emb([sources[s] for s in SOURCES]))}
    src_t = {k: torch.from_numpy(v).to(device) for k, v in sources.items()}

    out_ids: list[str] = []
    store: dict[str, list[np.ndarray]] = {k: [] for k in ["ir", *SOURCES, "reverb_vector"]}
    for i in range(0, len(rows), batch):
        irs, bid = [], []
        for r in rows[i:i + batch]:
            try:
                s = _ir_signal(r, adapter, root, d, cfg)
            except Exception:  # noqa: BLE001 - skip unreadable records, keep the batch going
                s = None
            if s is not None:
                irs.append(s)
                bid.append(r["ir_id"])
        if not irs:
            continue
        store["ir"].append(emb([_fix(s) for s in irs]))
        per_src = {}
        for name in SOURCES:
            wet = []
            for s in irs:
                h = torch.from_numpy(s[:N]).to(device)
                # power-of-two FFT: arbitrary sizes (~1M samples) hit cuFFT internal errors
                nfft = 1 << int(np.ceil(np.log2(N + h.numel() - 1)))
                y = torch.fft.irfft(torch.fft.rfft(src_t[name], nfft) * torch.fft.rfft(h, nfft), nfft)[:N]
                y = y / (torch.sqrt(torch.mean(y ** 2)) + 1e-12)
                wet.append(y.float().cpu().numpy())
            per_src[name] = emb(wet)
            store[name].append(per_src[name])
        store["reverb_vector"].append(np.mean([per_src[n] - dry[n][None, :] for n in SOURCES], axis=0))
        out_ids += bid

    out_dir = paths.data_root() / "embeddings" / MODEL.replace("/", "__")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (f"{dataset_id}.npz" if n_shards == 1 else f"{dataset_id}.part{shard:03d}-of-{n_shards:03d}.npz")
    np.savez_compressed(out, ir_id=np.array(out_ids), source_sha256=json.dumps(sums),
                        **{k: np.concatenate(v).astype(np.float16) for k, v in store.items() if v})
    return out
