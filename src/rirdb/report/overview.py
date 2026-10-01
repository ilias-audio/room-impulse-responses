"""Corpus overview: filtering guide, signal integrity, metric distributions and the CLAP map.

    rirdb report overview      -> reports/overview/overview.json, clap_map.json, index.html, README.md

Distributions are computed for nested subsets (all analysed IRs -> measured -> measured room IRs ->
clean measured rooms) and two weightings: per IR, and per room (the median of each room), because the
dense single-room datasets (SRIRACHA, Arni, TAU, ...) dominate per-IR counts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from rirdb import paths
from rirdb.query import connect

BANDS = [63, 125, 250, 500, 1000, 2000, 4000, 8000, "bb"]
AUDIT_FLAGS = ["flag_sweep_like", "flag_tonal", "flag_not_decaying", "flag_dropout", "flag_nonstationary_noise",
               "flag_quantized_tail"]
CLEAN = ("measured AND ir_kind = 'room' AND preferred AND dup_of IS NULL "
         "AND NOT coalesce(flag_sweep_like OR flag_tonal OR flag_not_decaying OR flag_dropout, false)")
SUBSETS = {
    "all": ("All analysed IRs", "TRUE"),
    "measured": ("Measured", "measured"),
    "measured_rooms": ("Measured room IRs", "measured AND ir_kind = 'room'"),
    "clean_rooms": ("Clean measured rooms", CLEAN),
}
QUALITY_FLAGS = ["flag_clipped", "flag_dc_offset", "flag_pre_onset_energy", "flag_low_pnr", "flag_lundeby_failed_any",
                 "flag_no_noise_floor", "flag_tail_truncated", "flag_curved_decay", "flag_nonlinear_decay",
                 "flag_implausible_hf_decay", "flag_filter_bias_risk", "flag_edc_method_disagreement"]


def _bins():
    lg = lambda a, b, n: np.logspace(np.log10(a), np.log10(b), n + 1)  # noqa: E731
    return {
        "t": lg(0.05, 20, 48), "c": np.arange(-15, 36, 1.0), "d50": np.arange(0, 1.0001, 0.025),
        "drr": np.arange(-25, 31, 1.0), "sti": np.arange(0, 1.0001, 0.025), "br": lg(0.3, 3, 30),
        "tmix": np.arange(0, 151, 5.0), "pnr": np.arange(0, 141, 2.5), "onset": lg(1e-4, 10, 30),
        "burst": np.arange(0, 41, 1.0), "drift": np.arange(-20, 21, 1.0), "vol": lg(1, 1e5, 30),
    }


def _hist(v: pd.Series, edges: np.ndarray) -> dict:
    v = v.dropna().to_numpy(dtype=float)
    h, _ = np.histogram(np.clip(v, edges[0], edges[-1] - 1e-9), bins=edges)
    q = np.percentile(v, [5, 25, 50, 75, 95]).round(4).tolist() if v.size else [None] * 5
    return {"edges": np.round(edges, 5).tolist(), "counts": h.tolist(), "n": int(v.size), "q": q}


def _box(v: pd.Series) -> dict:
    v = v.dropna().to_numpy(dtype=float)
    if not v.size:
        return {"n": 0}
    return {"n": int(v.size), "q": np.percentile(v, [5, 25, 50, 75, 95]).round(4).tolist()}


def _valid(df: pd.DataFrame, metric: str, band) -> pd.Series:
    col, vcol = f"{metric}_{band}", f"valid_{metric}_{band}"
    if col not in df:
        return pd.Series(dtype=float)
    v = df[col]
    return v.where(df[vcol].fillna(False).astype(bool)) if vcol in df else v


def _per_room(df: pd.DataFrame, s: pd.Series) -> pd.Series:
    return s.groupby(df["room_id"]).median()


def load_frame() -> pd.DataFrame:
    con = connect()
    have = {r[0] for r in con.execute("DESCRIBE corpus_dedup").fetchall()}
    want = (["ir_id", "dataset_id", "room_id", "room_label", "category", "ir_kind", "type", "measured", "preferred",
             "dup_of", "grade", "capture_format", "fs", "duration_s", "onset_s", "leading_silence_s",
             "trailing_zeros_s", "onset_spread_ms", "pnr_db", "drr_bb", "sti", "valid_sti", "br", "tr", "t_mix_ned_ms",
             "volume_m3", "t30_mid", "edt_mid", "c80_mid", "d50_mid", "edc_mode_bb", "tonal_frac", "tonal_prom_db", "glide_db",
             "env_slope_db_s", "active_s", "crest_db", "dropout_ms", "zero_frac", "quant_range_db", "noise_seg_s", "noise_burst_db", "noise_drift_db",
             "local_key", "license_spdx", "training_use"]
            + [f"{p}{m}_{b}" for m in ("t30", "t20", "edt", "c80", "d50") for b in BANDS for p in ("", "valid_")]
            + QUALITY_FLAGS + AUDIT_FLAGS)
    cols = [c for c in dict.fromkeys(want) if c in have]
    return con.execute(f"SELECT {', '.join(cols)} FROM corpus_dedup WHERE coalesce(error, '') = ''").df()


def _subset_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    import duckdb

    con = duckdb.connect()
    con.register("d", df)
    out = {}
    for key, (_, where) in SUBSETS.items():
        ids = set(con.execute(f"SELECT ir_id FROM d WHERE {where}").df()["ir_id"])
        out[key] = df["ir_id"].isin(ids)
    return out


def distributions(df: pd.DataFrame, masks: dict) -> dict:
    B = _bins()
    hist_specs = {"t30_bb": ("t30", "bb", "t"), "t30_mid": ("t30_mid", None, "t"), "edt_mid": ("edt_mid", None, "t"),
                  "t20_bb": ("t20", "bb", "t"), "c80_mid": ("c80_mid", None, "c"), "d50_mid": ("d50_mid", None, "d50"),
                  "drr_bb": ("drr_bb", None, "drr"), "sti": ("sti", None, "sti"), "br": ("br", None, "br"),
                  "tr": ("tr", None, "br"), "t_mix_ned_ms": ("t_mix_ned_ms", None, "tmix"),
                  "volume_m3": ("volume_m3", None, "vol")}
    out = {}
    for key, m in masks.items():
        d = df[m]
        res = {"n_irs": int(len(d)), "n_rooms": int(d["room_id"].nunique()), "n_datasets": int(d["dataset_id"].nunique()),
               "hist": {"ir": {}, "room": {}}, "bands": {"ir": {}, "room": {}}, "validity": {}}
        for name, (metric, band, b) in hist_specs.items():
            if metric not in d and f"{metric}_{band}" not in d:
                continue
            s = _valid(d, metric, band) if band else (d[metric].where(d["valid_sti"].fillna(False).astype(bool))
                                                      if metric == "sti" else d[metric])
            res["hist"]["ir"][name] = _hist(s, B[b])
            res["hist"]["room"][name] = _hist(_per_room(d, s), B[b])
        for metric in ("t30", "t20", "edt", "c80", "d50"):
            res["bands"]["ir"][metric] = {str(b): _box(_valid(d, metric, b)) for b in BANDS}
            res["bands"]["room"][metric] = {str(b): _box(_per_room(d, _valid(d, metric, b))) for b in BANDS}
            res["validity"][metric] = {str(b): round(float(d[f"valid_{metric}_{b}"].fillna(False).astype(bool).mean()), 4)
                                       for b in BANDS if f"valid_{metric}_{b}" in d}
        res["grades"] = d["grade"].value_counts().reindex(list("ABCD"), fill_value=0).astype(int).to_dict()
        res["kinds"] = d["ir_kind"].value_counts().astype(int).to_dict()
        cat = d.groupby("category")
        res["categories"] = sorted(
            [{"category": c, "n_irs": int(len(g)), "n_rooms": int(g["room_id"].nunique()),
              "t30_mid_room": _box(_per_room(g, g["t30_mid"]))} for c, g in cat], key=lambda r: -r["n_rooms"])
        out[key] = res
    return out


def integrity(df: pd.DataFrame, masks: dict) -> dict:
    B = _bins()
    d = df[masks["all"]]
    onset = d["onset_s"]
    out = {
        "onset": {"hist": _hist(onset.where(onset > 0), B["onset"]), "n_zero": int((onset <= 0).sum()),
                  "share_over_10ms": round(float((onset > 0.01).mean()), 4),
                  "share_over_100ms": round(float((onset > 0.1).mean()), 4)},
        "leading_silence_share": round(float((d["leading_silence_s"] > 0).mean()), 4),
        "trailing_zeros_share": round(float((d["trailing_zeros_s"] > 0).mean()), 4),
        "pnr": _hist(d["pnr_db"], B["pnr"]),
        "noise_burst": _hist(d.get("noise_burst_db", pd.Series(dtype=float)), B["burst"]),
        "noise_drift": _hist(d.get("noise_drift_db", pd.Series(dtype=float)), B["drift"]),
        "edc_mode_bb": d["edc_mode_bb"].fillna("n/a").value_counts().astype(int).to_dict(),
        "audited": int(d["tonal_frac"].notna().sum()) if "tonal_frac" in d else 0,
    }
    rows = []
    for ds, g in d.groupby("dataset_id"):
        r = {"dataset": ds, "n": int(len(g)), "kind": ", ".join(g["ir_kind"].value_counts().index[:2]),
             "onset_ms_med": round(float(g["onset_s"].median() * 1e3), 1), "pnr_med": round(float(g["pnr_db"].median()), 1),
             "noise_burst_med": round(float(g["noise_burst_db"].median()), 1) if "noise_burst_db" in g and g["noise_burst_db"].notna().any() else None,
             "floor_share": round(float((g["edc_mode_bb"] == "lundeby").mean()), 3)}
        for f in AUDIT_FLAGS + QUALITY_FLAGS:
            if f in g:
                r[f] = round(float(g[f].fillna(False).astype(bool).mean()), 4)
        r["grades"] = g["grade"].value_counts().reindex(list("ABCD"), fill_value=0).astype(int).tolist()
        r["t30_mid_med"] = round(float(g["t30_mid"].median()), 3) if g["t30_mid"].notna().any() else None
        rows.append(r)
    out["per_dataset"] = rows
    ex = {}
    for f in AUDIT_FLAGS:
        if f in d:
            sel = d[d[f].fillna(False).astype(bool)]
            ex[f] = {"n": int(len(sel)), "by_dataset": sel["dataset_id"].value_counts().astype(int).to_dict(),
                     "examples": sel.sort_values("ir_id").groupby("dataset_id").head(4)[
                         ["ir_id", "dataset_id", "local_key", "tonal_frac", "glide_db", "env_slope_db_s",
                          "noise_burst_db", "noise_drift_db"]].head(40).round(3).replace({np.nan: None}).to_dict("records")}
    out["audit"] = ex
    return out


def clap_map(df: pd.DataFrame, cap: int = 1200, k: int = 10, seed: int = 0) -> dict:
    """2-D UMAP of CLAP embeddings ('ir' and 'reverb_vector') for a capped, per-room stratified sample."""
    import umap

    root = paths.data_root() / "embeddings" / "laion__clap-htsat-unfused"
    keep = df[df["preferred"].astype(bool) & df["dup_of"].isna()].copy()
    rng = np.random.default_rng(seed)
    parts = []
    for ds, g in keep.groupby("dataset_id"):
        if len(g) > cap:          # stratified by room: every room keeps at least one IR
            g = g.sample(frac=1.0, random_state=int(rng.integers(1 << 31)))
            first = g.groupby("room_id").head(1)
            rest = g.drop(first.index).head(max(cap - len(first), 0))
            g = pd.concat([first, rest])
        parts.append(g)
    sel = pd.concat(parts).sort_values("ir_id").reset_index(drop=True)
    want = set(sel["ir_id"])
    emb = {"ir": {}, "reverb_vector": {}}
    for f in sorted(root.glob("*.npz")):
        with np.load(f, allow_pickle=False) as z:
            ids = z["ir_id"].astype(str)
            m = np.isin(ids, list(want))
            if not m.any():
                continue
            for key in emb:
                if key in z:
                    for i, v in zip(ids[m], z[key][m]):
                        emb[key][i] = v.astype(np.float32)
    sel = sel[sel["ir_id"].isin(emb["ir"].keys() & emb["reverb_vector"].keys())].reset_index(drop=True)
    maps = {}
    for key, label in (("ir", "IR embedding"), ("reverb_vector", "Reverb effect on 6 dry sources")):
        X = np.stack([emb[key][i] for i in sel["ir_id"]])
        Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
        xy = umap.UMAP(n_neighbors=30, min_dist=0.15, metric="cosine", random_state=seed).fit_transform(Xn)
        xy = (xy - xy.min(0)) / (xy.max(0) - xy.min(0) + 1e-12)
        ds = sel["dataset_id"].to_numpy()
        nn, dist, nnx, distx = [], [], [], []

        def topk(sim):
            top = np.argpartition(-sim, k, axis=1)[:, :k]
            order = np.take_along_axis(sim, top, axis=1).argsort(axis=1)[:, ::-1]
            top = np.take_along_axis(top, order, axis=1)
            return top, 1 - np.take_along_axis(sim, top, axis=1)

        for s in range(0, len(Xn), 2048):
            sim = Xn[s:s + 2048] @ Xn.T
            for r, row in enumerate(sim):
                row[s + r] = -np.inf
            a, b = topk(sim)
            nn.append(a), dist.append(b)
            sim[ds[s:s + 2048][:, None] == ds[None, :]] = -np.inf   # neighbours from other datasets only
            a, b = topk(sim)
            nnx.append(a), distx.append(b)
        # integers keep the page small: xy in 1e-4 of the unit square, cosine distance in 1e-3
        maps[key] = {"label": label, "xy": np.round(xy * 1e4).astype(int).tolist(), "nn": np.concatenate(nn).tolist(),
                     "dist": np.round(np.concatenate(dist).astype(np.float64) * 1e3).astype(int).tolist(),
                     "nn_x": np.concatenate(nnx).tolist(),
                     "dist_x": np.round(np.concatenate(distx).astype(np.float64) * 1e3).astype(int).tolist()}
    # how well do neighbours agree acoustically? share of nearest neighbours with T30 (mid) within 20 %
    t30 = sel["t30_mid"].to_numpy(dtype=float)
    for key, m in maps.items():
        q = {}
        for name, col in (("any", "nn"), ("other", "nn_x")):
            j = np.array(m[col])[:, 0]
            ok = np.isfinite(t30) & np.isfinite(t30[j])
            q[name] = {"t30_within_20pct": round(float(np.mean(np.abs(np.log(t30[j][ok] / t30[ok])) < np.log(1.2))), 3),
                       "same_dataset": round(float(np.mean(sel["dataset_id"].to_numpy()[j] == sel["dataset_id"].to_numpy())), 3)}
        perm = np.random.default_rng(seed).permutation(len(t30))
        ok = np.isfinite(t30) & np.isfinite(t30[perm])
        q["random_t30_within_20pct"] = round(float(np.mean(np.abs(np.log(t30[perm][ok] / t30[ok])) < np.log(1.2))), 3)
        m["agreement"] = q
    cats = {c: sorted(sel[c].fillna("unknown").astype(str).unique().tolist()) for c in ("dataset_id", "category", "ir_kind")}
    labels = sorted(sel["room_label"].fillna(sel["room_id"]).astype(str).unique().tolist())
    lab_ix = {v: i for i, v in enumerate(labels)}
    num = lambda c, n: [None if not np.isfinite(v) else round(float(v), n) for v in sel[c].to_numpy(dtype=float)]  # noqa: E731
    return {
        "n": int(len(sel)), "cap_per_dataset": cap, "k": k, "maps": maps, "cats": cats, "room_labels": labels,
        "points": {
            "ir_id": sel["ir_id"].tolist(), "key": [re.sub(r"\s+", " ", str(v))[-56:] for v in sel["local_key"]],
            "dataset": [cats["dataset_id"].index(v) for v in sel["dataset_id"]],
            "category": [cats["category"].index(v) for v in sel["category"].fillna("unknown").astype(str)],
            "kind": [cats["ir_kind"].index(v) for v in sel["ir_kind"].fillna("unknown").astype(str)],
            "room": [lab_ix[v] for v in sel["room_label"].fillna(sel["room_id"]).astype(str)],
            "t30": num("t30_mid", 3), "edt": num("edt_mid", 3), "c80": num("c80_mid", 1),
            "drr": num("drr_bb", 1), "grade": sel["grade"].fillna("?").tolist(),
        },
    }


def build(out_dir: Path = paths.REPORTS_DIR / "overview") -> Path:
    from rirdb.analysis import ANALYZER_VERSION

    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_frame()
    masks = _subset_masks(df)
    data = {
        "generated": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "analyzer_version": ANALYZER_VERSION,
        "subsets": {k: v[0] for k, v in SUBSETS.items()},
        "subset_sql": {k: v[1] for k, v in SUBSETS.items()},
        "distributions": distributions(df, masks),
        "integrity": integrity(df, masks),
    }
    data = _clean(data)
    (out_dir / "overview.json").write_text(json.dumps(data, separators=(",", ":"), allow_nan=False, default=str))
    cmap = _clean(clap_map(df))
    (out_dir / "clap_map.json").write_text(json.dumps(cmap, separators=(",", ":"), allow_nan=False))
    tpl = (Path(__file__).parent / "overview_template.html").read_text()
    js = lambda o: json.dumps(o, separators=(",", ":"), default=str).replace("</", "<\\/")  # noqa: E731
    html = tpl.replace("/*OVERVIEW_JSON*/null", js(data)) \
              .replace("/*CLAP_JSON*/null", js(cmap))
    (out_dir / "index.html").write_text(html)
    (out_dir / "README.md").write_text(markdown(data, cmap))
    return out_dir / "index.html"


def _clean(o):
    """JSON-safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def markdown(data: dict, cmap: dict) -> str:
    dist, integ = data["distributions"], data["integrity"]
    md = ["# Corpus overview", "",
          f"Generated {data['generated']} by `rirdb report overview` (analyzer {data['analyzer_version']}). "
          "The interactive version with all charts and the CLAP map is `index.html` in this folder.", "",
          "## Subsets", "", "| subset | SQL predicate over `corpus_dedup` | IRs | rooms | datasets |", "|---|---|---|---|---|"]
    for k, label in data["subsets"].items():
        s = dist[k]
        md.append(f"| {label} | `{data['subset_sql'][k]}` | {s['n_irs']:,} | {s['n_rooms']:,} | {s['n_datasets']} |")
    md += ["", "## T30 per octave band, clean measured rooms (median per room; p5 / p25 / p50 / p75 / p95, s)", "",
           "| band | rooms | p5 | p25 | p50 | p75 | p95 | valid share (per IR) |", "|---|---|---|---|---|---|---|---|"]
    cr = dist["clean_rooms"]
    for b, box in cr["bands"]["room"]["t30"].items():
        q = box.get("q") or [None] * 5
        md.append(f"| {b} | {box['n']} | " + " | ".join("" if v is None else f"{v:.2f}" for v in q)
                  + f" | {cr['validity']['t30'].get(b, 0) * 100:.0f} % |")
    md += ["", "## Signal integrity (all analysed IRs)", "",
           f"- Audited: {integ['audited']:,} IRs.",
           f"- Pre-delay before the direct sound in the files: {integ['onset']['share_over_10ms'] * 100:.1f} % over 10 ms, "
           f"{integ['onset']['share_over_100ms'] * 100:.1f} % over 100 ms. The analysis crops every IR at its ISO 3382-1 "
           "onset (20 dB below the peak); the source files are not modified.",
           f"- Broadband noise floor found (Lundeby): {integ['edc_mode_bb'].get('lundeby', 0):,}; decaying to the end of "
           f"the file (no floor): {integ['edc_mode_bb'].get('schroeder_nofloor', 0):,}; failed: {integ['edc_mode_bb'].get('failed', 0):,}.", ""]
    for f, e in integ["audit"].items():
        md.append(f"- `{f}`: {e['n']:,} IRs" + (" (" + ", ".join(f"{k} {v}" for k, v in e["by_dataset"].items()) + ")" if e["n"] else ""))
    md += ["", f"## CLAP map", "", f"{cmap['n']:,} IRs (preferred, de-duplicated, at most {cmap['cap_per_dataset']} per dataset, "
           f"every room kept), UMAP of the CLAP `ir` and `reverb_vector` embeddings; {cmap['k']} nearest neighbours by cosine "
           "distance in the full 512-d space. Open `index.html`.", ""]
    return "\n".join(md) + "\n"
