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
                   r.volume_m3, i.locator, i.fs AS fs_file, i.duration_s AS duration_file_s
            FROM metrics m
            LEFT JOIN rooms r USING (room_id)
            LEFT JOIN irs i USING (ir_id);
    """)
    return con


def query(where: str, columns: list[str] | None = None, limit: int = 50, order_by: str | None = None):
    con = connect()
    cols = ", ".join(columns or DEFAULT_COLUMNS)
    sql = f"SELECT {cols} FROM corpus WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return con.execute(sql).df()
