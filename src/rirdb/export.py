"""Exports: the committed core-metrics snapshot and platform (Postgres) loads.

snapshots/metrics_core/<dataset>.parquet hold the core ISO parameters, grades,
flags and room metadata of every analysed IR (metrics as float32, ZSTD), one
file per dataset so each stays small for git and a refresh only rewrites the
datasets that changed. The numbers survive the scratch purge even if
RIRDB_ROOT is lost.
"""

from __future__ import annotations

import re
from pathlib import Path

from rirdb import paths
from rirdb.query import connect

BANDS = (125, 250, 500, 1000, 2000, 4000, 8000)
CORE = (
    ["ir_id", "dataset_id", "room_id", "category", "room_label", "ir_kind", "type", "measured", "preferred",
     "capture_format", "analysed_role", "license_spdx", "redistribute_audio", "training_use", "volume_m3",
     "fs", "duration_s", "grade", "analyzer_version", "config_sha256",
     "t30_mid", "t20_mid", "edt_mid", "c50_mid", "c80_mid", "d50_mid", "ts_mid", "br", "tr",
     "drr_bb", "sti", "t_mix_ned_ms", "t_mix_edp_ms", "pnr_db", "spectral_tilt_db_per_oct",
     "iacc_e3", "one_minus_iacc_e3", "jlf_low", "onset_s", "noise_burst_db", "noise_drift_db", "tonal_frac"]
    + [f"{m}_{b}" for b in (*BANDS, "bb") for m in ("t30", "edt", "c80")]
    + [f"valid_t30_{b}" for b in (*BANDS, "bb")]
)
MAX_BYTES = 25 * 1024 * 1024


def snapshot(out_dir: Path = paths.REPO_ROOT / "snapshots" / "metrics_core") -> list[Path]:
    con = connect()
    types = {r[0]: r[1] for r in con.execute("DESCRIBE corpus").fetchall()}
    flags = sorted(c for c in types if c.startswith("flag_"))
    cols = [c for c in CORE if c in types] + flags
    sel = ", ".join(f"CAST({c} AS FLOAT) AS {c}" if types[c] == "DOUBLE" else c for c in cols)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for (ds,) in con.execute("SELECT DISTINCT dataset_id FROM corpus ORDER BY 1").fetchall():
        if not re.fullmatch(r"[a-z0-9_]+", ds):
            raise ValueError(f"unexpected dataset id {ds!r}")
        out = out_dir / f"{ds}.parquet"
        con.execute(f"COPY (SELECT {sel} FROM corpus WHERE dataset_id = '{ds}' ORDER BY ir_id) TO '{out}' "
                    "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 19)")
        if out.stat().st_size > MAX_BYTES:
            raise RuntimeError(f"{out.name} is {out.stat().st_size / 1e6:.1f} MB > 25 MB; drop columns")
        written.append(out)
    return written
