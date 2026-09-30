"""Canonical index of every IR record (Parquet under $RIRDB_ROOT/index/).

  index/irs/dataset=<id>/part-0.parquet    one row per IR record
  index/rooms/dataset=<id>/part-0.parquet  one row per room (with curated category)

Paths inside `locator` are relative to raw/<id>/files, so moving the corpus
only means changing RIRDB_ROOT.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from rirdb import paths
from rirdb.adapters import get_adapter
from rirdb.registry import Dataset


def index_dir() -> Path:
    return paths.data_root() / "index"


def irs_path(dataset_id: str) -> Path:
    return index_dir() / "irs" / f"dataset={dataset_id}" / "part-0.parquet"


def rooms_path(dataset_id: str) -> Path:
    return index_dir() / "rooms" / f"dataset={dataset_id}" / "part-0.parquet"


def _hash_fraction(key: str) -> float:
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big") / 2 ** 64


def subsample_mask(df: pd.DataFrame, d: Dataset) -> pd.Series:
    """subsample_v1: which records the first analysis pass covers.

    Full scope: everything. Dense datasets: a deterministic hash rule (stable as
    data is added) keeping `analysis.subsample.fraction` (default 1/16 = 6.25 %),
    always keeping at least one record per room/condition.
    """
    if d.analysis.scope != "subsample_v1":
        return pd.Series(True, index=df.index)
    frac = float((d.analysis.subsample or {}).get("fraction", 1 / 16))
    keep = df["local_key"].map(_hash_fraction) < frac
    group = df["room_id"] + "|" + df["condition_key"].fillna("")
    first = df.sort_values("local_key").groupby(group.loc[df.sort_values("local_key").index]).head(1).index
    keep.loc[first] = True
    return keep


def _curated_rooms(dataset_id: str) -> pd.DataFrame | None:
    p = paths.REGISTRY_DIR / "rooms" / f"{dataset_id}.csv"
    if not p.exists():
        return None
    return pd.read_csv(p, dtype=str).fillna("")


def build_index(d: Dataset) -> dict:
    adapter = get_adapter(d.adapter.name)
    root = paths.files_dir(d.id)
    rows = [r.to_row() for r in adapter.iter_records(d, root)]
    if not rows:
        raise RuntimeError(f"{d.id}: adapter found no IR records under {root}")
    df = pd.DataFrame(rows)
    df["type"] = d.type
    df["measured"] = d.type == "measured"
    df["license_spdx"] = d.license.spdx
    df["redistribute_audio"] = d.license.redistribute_audio
    df["wave"] = d.wave
    dup = df["ir_id"].duplicated()
    if dup.any():
        raise RuntimeError(f"{d.id}: duplicate local keys: {df.loc[dup, 'local_key'].head().tolist()}")
    df["subsample_v1"] = subsample_mask(df, d)

    rooms = (df.groupby("room_id")
               .agg(room_key=("room_key", "first"), room_label=("room_label", "first"),
                    category_hint=("category_hint", "first"), ir_kind=("ir_kind", "first"),
                    n_irs=("ir_id", "size"))
               .reset_index())
    rooms["dataset_id"] = d.id
    rooms["category"] = ""
    cur = _curated_rooms(d.id)
    if cur is not None:
        rooms = rooms.drop(columns=[c for c in ("category",) if c in cur.columns])
        rooms = rooms.merge(cur, on="room_key", how="left", suffixes=("", "_curated"))
        for col in ("room_label", "ir_kind"):
            cc = f"{col}_curated"
            if cc in rooms:
                rooms[col] = rooms[cc].where(rooms[cc].fillna("") != "", rooms[col])
                rooms = rooms.drop(columns=[cc])
        rooms["category"] = rooms.get("category", "").fillna("")

    for path, frame in ((irs_path(d.id), df), (rooms_path(d.id), rooms)):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    return {"dataset": d.id, "n_irs": len(df), "n_rooms": rooms.shape[0],
            "n_subsample_v1": int(df["subsample_v1"].sum()),
            "fs": sorted(df["fs"].unique().tolist()), "channels": sorted(df["n_channels"].unique().tolist())}


def load_irs(dataset_id: str) -> pd.DataFrame:
    return pd.read_parquet(irs_path(dataset_id))
