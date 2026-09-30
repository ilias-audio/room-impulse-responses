"""Sharded analysis of indexed datasets (SLURM array friendly).

  metrics/v1/<id>/shard-00000-of-00008.parquet  one row per IR: index columns + scalars
  features/v1/<id>/shard-00000-of-00008.h5      fixed-shape arrays stacked per feature, row-aligned with `ir_id`
  metrics/v1/<id>/wide.parquet         merged shards (rirdb merge)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from rirdb import paths
from rirdb.adapters import get_adapter
from rirdb.analysis import ANALYZER_VERSION
from rirdb.analysis.config import load_config
from rirdb.index import load_irs
from rirdb.registry import get_dataset

INDEX_COLUMNS = ["ir_id", "dataset_id", "room_id", "local_key", "condition_key", "src_key", "rcv_key", "preferred",
                 "capture_format", "channel_roles", "ir_kind", "type", "measured", "license_spdx",
                 "redistribute_audio", "src_x", "src_y", "src_z", "rcv_x", "rcv_y", "rcv_z"]


def metrics_dir(dataset_id: str) -> Path:
    return paths.data_root() / "metrics" / f"v{ANALYZER_VERSION.split('.')[0]}" / dataset_id


def features_dir(dataset_id: str) -> Path:
    return paths.data_root() / "features" / f"v{ANALYZER_VERSION.split('.')[0]}" / dataset_id


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "-C", str(paths.REPO_ROOT), "rev-parse", "--short=12", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _select_channels(x: np.ndarray, roles: tuple[str, ...], reference_role: str | None):
    """Keep the channels the analysis needs: pairs/B-format whole, arrays -> one reference channel.

    reference_role "mean" averages all capsules: the order-0 spherical-harmonic
    (omni) component of a rigid spherical array. Open arrays of omni capsules
    use a single capsule instead (averaging spaced capsules low-passes the direct sound).
    """
    if ("L" in roles and "R" in roles) or ("SL" in roles and "SR" in roles):
        return x, roles
    if "W" in roles:                     # Ambisonics: only the first-order channels are used
        keep = [i for i, r in enumerate(roles) if r in ("W", "X", "Y", "Z")]
        return x[keep], tuple(roles[i] for i in keep)
    if reference_role == "mean":
        return x.mean(axis=0, keepdims=True), ("omni_mean",)
    i = roles.index(reference_role) if reference_role in roles else 0
    return x[i:i + 1], (roles[i],)


_WORKER = {}


def _init_worker(dataset_id: str):
    d = get_dataset(dataset_id)
    _WORKER.update(dataset=d, adapter=get_adapter(d.adapter.name, d.adapter.params), root=paths.files_dir(dataset_id),
                   cfg=load_config())


def _analyze_row(row: dict) -> tuple[dict, dict]:
    from rirdb.analysis.pipeline import analyze_ir

    d, adapter, root, cfg = _WORKER["dataset"], _WORKER["adapter"], _WORKER["root"], _WORKER["cfg"]
    t0 = time.perf_counter()
    try:
        x, fs = adapter.load(json.loads(row["locator"]), root)
        roles = tuple(row["channel_roles"].split(","))
        content_sha1 = hashlib.sha1(np.ascontiguousarray(x, dtype=np.float32).tobytes()).hexdigest()
        xs, rs = _select_channels(x, roles, row.get("reference_role") or d.analysis.reference_role)
        a = analyze_ir(xs, fs, roles=rs, capture_format=row["capture_format"], sh_norm=row.get("sh_norm"),
                       orientation_known=bool(row.get("orientation_known", True)), cfg=cfg)
        s = a.scalars
        s["content_sha1"] = content_sha1
        s["error"] = ""
        feats = a.features
    except Exception as e:  # noqa: BLE001 - one bad file must not kill the shard
        s = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2000:], "grade": "D"}
        feats = {}
    s["ir_id"] = row["ir_id"]
    s["analysis_seconds"] = time.perf_counter() - t0
    return s, feats


def shard_rows(dataset_id: str, shard: int, n_shards: int, full: bool = False) -> pd.DataFrame:
    df = load_irs(dataset_id)
    if not full:
        df = df[df["subsample_v1"]]
    df = df.sort_values("ir_id").reset_index(drop=True)
    return df.iloc[shard::n_shards]


def analyze_shard(dataset_id: str, shard: int, n_shards: int, workers: int, full: bool = False,
                  limit: int | None = None) -> Path:
    rows = shard_rows(dataset_id, shard, n_shards, full)
    if limit:
        rows = rows.head(limit)
    records = rows.to_dict("records")
    results: list[tuple[dict, dict]] = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(dataset_id,)) as ex:
        for res in ex.map(_analyze_row, records, chunksize=4):
            results.append(res)

    scal = pd.DataFrame([r[0] for r in results])
    meta = rows[[c for c in INDEX_COLUMNS if c in rows.columns]].reset_index(drop=True)
    scal = scal.drop(columns=[c for c in scal.columns if c in meta.columns and c != "ir_id"])
    out = meta.merge(scal, on="ir_id", how="left")
    out["pyrato_version"] = version("pyrato")
    out["pyfar_version"] = version("pyfar")
    out["code_sha"] = _git_sha()
    mdir = metrics_dir(dataset_id)
    mdir.mkdir(parents=True, exist_ok=True)
    mpath = mdir / f"shard-{shard:05d}-of-{n_shards:05d}.parquet"
    # rows that errored have NaN in boolean columns: keep booleans boolean
    for c in out.columns:
        if c.startswith(("valid_", "flag_")):
            out[c] = out[c].astype("boolean").fillna(False).astype(bool)
        elif out[c].dtype == object:
            out[c] = out[c].map(lambda v: v if isinstance(v, (str, type(None))) else
                                (None if isinstance(v, float) and np.isnan(v) else str(v)))
    out.to_parquet(mpath, index=False)

    _write_features(dataset_id, shard, n_shards, [r[1] for r in results], [r[0]["ir_id"] for r in results])
    return mpath


def _write_features(dataset_id: str, shard: int, n_shards: int, feats: list[dict], ids: list[str]) -> None:
    import h5py

    names = sorted({k for f in feats for k in f})
    if not names:
        return
    fdir = features_dir(dataset_id)
    fdir.mkdir(parents=True, exist_ok=True)
    path = fdir / f"shard-{shard:05d}-of-{n_shards:05d}.h5"
    with h5py.File(path, "w") as h:
        h.create_dataset("ir_id", data=np.array(ids, dtype="S40"))
        h.attrs["analyzer_version"] = ANALYZER_VERSION
        for name in names:
            template = next(f[name] for f in feats if name in f)
            template = np.asarray(template)
            if name == "band_centres":        # varies with fs: pad to 8
                stack = np.full((len(feats), 8), np.nan, dtype=np.float32)
                for i, f in enumerate(feats):
                    if name in f:
                        v = np.asarray(f[name]); stack[i, :v.size] = v
            else:
                stack = np.full((len(feats), *template.shape), np.nan, dtype=template.dtype)
                for i, f in enumerate(feats):
                    if name in f and np.shape(f[name]) == template.shape:
                        stack[i] = f[name]
            h.create_dataset(name, data=stack, compression="gzip", compression_opts=4, shuffle=True)


_SHARD_RE = re.compile(r"shard-(\d{5})-of-(\d{5})\.parquet$")


def merge(dataset_id: str) -> Path:
    """Merge one complete analysis run into wide.parquet.

    The run is the shard count of the newest shard file; shards written by runs
    with another count are ignored (reported, not deleted). Missing shards or
    shards from different analyzer configs are errors, so a partly re-run
    dataset never merges stale rows.
    """
    mdir = metrics_dir(dataset_id)
    shards = [p for p in mdir.glob("shard-*.parquet") if _SHARD_RE.search(p.name)]
    if not shards:
        raise FileNotFoundError(f"no metric shards in {mdir}")
    n = int(_SHARD_RE.search(max(shards, key=lambda p: p.stat().st_mtime).name).group(2))
    current = sorted(p for p in shards if int(_SHARD_RE.search(p.name).group(2)) == n)
    stale = sorted(set(mdir.glob("shard-*.parquet")) - set(current))
    if stale:
        print(f"{dataset_id}: ignoring {len(stale)} shard files from other runs, e.g. {stale[0].name}")
    missing = sorted(set(range(n)) - {int(_SHARD_RE.search(p.name).group(1)) for p in current})
    if missing:
        raise RuntimeError(f"{dataset_id}: {len(missing)} of {n} shards missing, e.g. {missing[:5]}")
    df = pd.concat([pd.read_parquet(p) for p in current], ignore_index=True)
    configs = df["config_sha256"].dropna().unique() if "config_sha256" in df else []
    if len(configs) > 1:
        raise RuntimeError(f"{dataset_id}: shards mix analyzer configs {sorted(configs)}; re-run the stale shards")
    # older shards: index/analyzer column clashes came out as <col>_x / <col>_y; keep the index value
    for c in [c[:-2] for c in df.columns if c.endswith("_x") and f"{c[:-2]}_y" in df.columns]:
        df[c] = df.pop(f"{c}_x")
        df.pop(f"{c}_y")
    df = df.drop_duplicates("ir_id", keep="last").sort_values("ir_id")
    out = mdir / "wide.parquet"
    df.to_parquet(out, index=False)
    return out


def auto_shard() -> tuple[int, int]:
    """(shard, n_shards) from the SLURM array environment."""
    shard = int(os.environ["SLURM_ARRAY_TASK_ID"])
    n = int(os.environ.get("SLURM_ARRAY_TASK_COUNT") or (int(os.environ["SLURM_ARRAY_TASK_MAX"]) + 1))
    return shard, n
