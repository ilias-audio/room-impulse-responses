-- rirdb platform schema (Postgres / Supabase). Maps 1:1 onto the Parquet tables
-- under $RIRDB_ROOT (index/, metrics/v1/, embeddings/). Load with DuckDB's
-- postgres extension, e.g.:
--   ATTACH 'postgresql://...' AS pg (TYPE postgres);
--   INSERT INTO pg.metrics SELECT ... FROM read_parquet('metrics/v1/*/wide.parquet');
-- Not applied anywhere yet (future step: the online IR picker).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE datasets (
    id                 text PRIMARY KEY,
    name               text NOT NULL,
    year               int,
    type               text NOT NULL CHECK (type IN ('measured', 'production', 'simulated')),
    license_spdx       text NOT NULL,
    license_url        text,
    redistribute_audio text NOT NULL CHECK (redistribute_audio IN ('yes', 'unaltered_only', 'no', 'unknown')),
    training_use       text NOT NULL CHECK (training_use IN ('allowed', 'prohibited', 'ask', 'unknown')),
    homepage           text,
    doi                text,
    citation           text
);

CREATE TABLE rooms (
    room_id       text PRIMARY KEY,             -- <dataset>/<slug>
    dataset_id    text NOT NULL REFERENCES datasets(id),
    room_label    text,
    category      text NOT NULL,                -- vocabulary in src/rirdb/rooms.py
    ir_kind       text NOT NULL,                -- room | outdoor | vehicle | scale_model | virtual | device | anechoic | ...
    volume_m3     double precision,
    description   text,
    materials     text,
    n_irs         int
);

CREATE TABLE irs (
    ir_id              text PRIMARY KEY,        -- <dataset>:<blake2b(local_key)>
    dataset_id         text NOT NULL REFERENCES datasets(id),
    room_id            text NOT NULL REFERENCES rooms(room_id),
    local_key          text NOT NULL,
    condition_key      text,
    src_key            text,
    rcv_key            text,
    src_xyz            double precision[3],
    rcv_xyz            double precision[3],
    capture_format     text NOT NULL,
    channel_roles      text NOT NULL,
    fs                 int NOT NULL,
    duration_s         double precision,
    ir_kind            text NOT NULL,
    preferred          boolean NOT NULL DEFAULT true,
    audio_uri          text,                    -- only when datasets.redistribute_audio allows it
    UNIQUE (dataset_id, local_key)
);

-- One row per analysed IR. The ~40 most-used parameters are columns (indexed for
-- constraint queries); everything else (all bands, all flags) is in `extra`.
CREATE TABLE metrics (
    ir_id              text PRIMARY KEY REFERENCES irs(ir_id),
    analyzer_version   text NOT NULL,
    config_sha256      text NOT NULL,
    grade              char(1) NOT NULL,
    t30_mid double precision, t20_mid double precision, edt_mid double precision,
    c50_mid double precision, c80_mid double precision, d50_mid double precision, ts_mid double precision,
    br double precision, tr double precision, drr_bb double precision, sti double precision,
    t_mix_ned_ms double precision, iacc_e3 double precision, jlf_low double precision,
    t30_125 double precision, t30_250 double precision, t30_500 double precision, t30_1000 double precision,
    t30_2000 double precision, t30_4000 double precision, t30_8000 double precision,
    valid_t30_500 boolean, valid_t30_1000 boolean,
    extra              jsonb NOT NULL DEFAULT '{}'   -- remaining metric_* / valid_* / flag_* columns
);
CREATE INDEX metrics_t30_mid ON metrics (t30_mid);
CREATE INDEX metrics_c80_mid ON metrics (c80_mid);
CREATE INDEX metrics_drr     ON metrics (drr_bb);
CREATE INDEX metrics_grade   ON metrics (grade);

-- Learned embeddings (CLAP): one row per IR x model x signal (ir | speech | ... | reverb_vector)
CREATE TABLE embeddings (
    ir_id      text NOT NULL REFERENCES irs(ir_id),
    model      text NOT NULL,                  -- e.g. laion/clap-htsat-unfused
    signal     text NOT NULL,
    embedding  vector(512) NOT NULL,
    PRIMARY KEY (ir_id, model, signal)
);
CREATE INDEX embeddings_hnsw ON embeddings USING hnsw (embedding vector_cosine_ops);
