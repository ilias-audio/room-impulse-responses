"""DuckDB views over the Parquet index and metrics: the prototype of the IR picker.

    rirdb query "t30_mid BETWEEN 1.2 AND 1.8 AND c80_mid > 0 AND measured" --columns ir_id,room_id,t30_mid

Views (all read straight from $RIRDB_ROOT, nothing copied):
  irs      one row per IR record (index)
  rooms    one row per room (with curated category)
  metrics  one row per analysed IR (metrics/v1/*/wide.parquet)
  corpus   metrics joined with room category/label and IR locator
"""

from __future__ import annotations

import duckdb

from rirdb import paths

DEFAULT_COLUMNS = ["ir_id", "dataset_id", "room_id", "grade", "t30_mid", "edt_mid", "c80_mid", "d50_mid",
                   "drr_bb", "sti", "br", "tr"]


def connect() -> duckdb.DuckDBPyConnection:
    root = paths.data_root()
    con = duckdb.connect()
    # signal-integrity audit (rirdb audit), when it has been run
    if any((root / "audit" / "v1").glob("*/audit.parquet")):
        con.execute(f"""CREATE VIEW audit AS SELECT COLUMNS(c -> c <> 'audit_traceback')
                        FROM read_parquet('{root}/audit/v1/*/audit.parquet', union_by_name = true)""")
    else:
        con.execute("CREATE VIEW audit AS SELECT NULL::VARCHAR AS ir_id WHERE false")
    con.execute(f"""
        CREATE VIEW irs AS SELECT * FROM read_parquet('{root}/index/irs/*/*.parquet', hive_partitioning = true,
                                                      union_by_name = true);
        CREATE VIEW rooms AS SELECT * FROM read_parquet('{root}/index/rooms/*/*.parquet', hive_partitioning = true,
                                                        union_by_name = true);
        CREATE VIEW metrics AS SELECT * FROM read_parquet('{root}/metrics/v1/*/wide.parquet', union_by_name = true);
        CREATE VIEW corpus AS
            -- ir_kind / preferred come from the current index, so room curation needs no re-analysis
            SELECT m.* EXCLUDE (ir_kind, preferred, license_spdx, redistribute_audio), i.ir_kind, i.preferred,
                   i.license_spdx, i.redistribute_audio, i.training_use, r.category, r.room_label,
                   r.volume_m3, i.locator, i.fs AS fs_file, i.duration_s AS duration_file_s,
                   a.* EXCLUDE (ir_id)
            FROM metrics m
            LEFT JOIN rooms r USING (room_id)
            LEFT JOIN irs i USING (ir_id)
            LEFT JOIN audit a USING (ir_id);
        -- exact duplicates: identical decoded samples (float32 sha1) under different records
        CREATE VIEW duplicates AS
            SELECT content_sha1, count(*) AS n, list(ir_id ORDER BY ir_id) AS ir_ids,
                   list(DISTINCT dataset_id) AS datasets, min(ir_id) AS keep_ir_id
            FROM metrics WHERE content_sha1 IS NOT NULL
            GROUP BY content_sha1 HAVING count(*) > 1;
        CREATE VIEW corpus_dedup AS
            SELECT c.*, d.keep_ir_id AS dup_of FROM corpus c
            LEFT JOIN duplicates d ON c.content_sha1 = d.content_sha1 AND c.ir_id <> d.keep_ir_id;
    """)
    # measured room IRs, one representation per position, no duplicates, and (once audited) no
    # sweeps, tonal or non-decaying content or dropouts; add grade or noise conditions on top as needed
    audited = "flag_sweep_like" in {r[0] for r in con.execute("DESCRIBE audit").fetchall()}
    content_ok = (" AND NOT coalesce(flag_sweep_like OR flag_tonal OR flag_not_decaying OR flag_dropout, false)"
                  if audited else "")
    con.execute("CREATE VIEW clean_rooms AS SELECT * FROM corpus_dedup WHERE measured AND ir_kind = 'room' "
                f"AND preferred AND dup_of IS NULL AND coalesce(error, '') = ''{content_ok}")
    return con


VIEWS = ("corpus", "corpus_dedup", "clean_rooms")


def query(where: str, columns: list[str] | None = None, limit: int = 50, order_by: str | None = None,
          view: str = "corpus"):
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}")
    con = connect()
    cols = ", ".join(columns or DEFAULT_COLUMNS)
    sql = f"SELECT {cols} FROM {view} WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql).df()
