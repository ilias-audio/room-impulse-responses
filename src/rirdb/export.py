"""Exports: the committed core-metrics snapshot and platform (Postgres) loads.

snapshots/metrics_core.parquet is small enough for git (<= 25 MB) and holds the
core ISO parameters, grades, flags and room metadata of every analysed IR, so
the numbers survive the scratch purge even if RIRDB_ROOT is lost.
"""

from __future__ import annotations

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
     "iacc_e3", "one_minus_iacc_e3", "jlf_low"]
    + [f"{m}_{b}" for b in (*BANDS, "bb") for m in ("t30", "edt", "c80")]
    + [f"valid_t30_{b}" for b in (*BANDS, "bb")]
)
MAX_BYTES = 25 * 1024 * 1024


def snapshot(out: Path = paths.REPO_ROOT / "snapshots" / "metrics_core.parquet") -> Path:
    con = connect()
    have = {r[0] for r in con.execute("DESCRIBE corpus").fetchall()}
    flags = sorted(c for c in have if c.startswith("flag_"))
    cols = [c for c in CORE if c in have] + flags
    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT {', '.join(cols)} FROM corpus ORDER BY ir_id) TO '{out}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)")
    size = out.stat().st_size
    if size > MAX_BYTES:
        raise RuntimeError(f"snapshot is {size / 1e6:.1f} MB > 25 MB; drop columns or split by wave")
    return out
