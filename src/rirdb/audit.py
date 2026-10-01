"""Signal-integrity audit: is each analysed file an impulse response, and is its noise floor stationary?

Runs after the analysis, on the channel the analysis used, onset-cropped exactly as the
analyzer does (`analysis.preprocess.prepare`), and reads the broadband Lundeby
intersection from the merged metrics. Output: audit/v1/<id>/audit.parquet, joined into the
`corpus` view.

Not an impulse response (sweeps, music, speech): frames of ~43 ms over the first 10 s after
the onset, keeping frames within 30 dB of the loudest one.
  tonal_frac        share of those frames holding a spectral line: a peak >= 15 dB above the mean of its
                    +-1/3-octave neighbourhood (Hann main lobe excluded), 100 Hz-16 kHz; noise peaks: 8-10 dB
  env_slope_db_s    least-squares slope of frame level over time (an IR decays at -60/T dB/s)
  active_s          time span of those frames (an IR: about T/2; a sweep: its length)
  crest_db          peak / RMS over the active span (IR with direct sound: > 15 dB; a sine: 3 dB)
  glide_db, glide_oct_s, glide_span_oct  strongest straight time-frequency ridge (see glide_ridge):
                    contrast over its brighter neighbour 1/3 octave away, slope, octaves covered (>= 1.5)
  flag_sweep_like   glide_db >= 8 (sweeps 30-60 dB, chirp residue 9-14 dB; clean IRs: p99 5.3, max 6.1 dB)
  flag_tonal        tonal_frac > 0.5 (hum, sustained tones, music, chirp residue)
  flag_not_decaying active_s > 1 s and env_slope_db_s > -2 dB/s (T60 > 30 s, or not an IR)

Zeros: runs of exact digital zeros inside the onset-cropped IR (see dropout_checks).
  zero_frac, quant_range_db  share of zero samples; peak over the smallest non-zero magnitude (bit-depth range)
  dropout_ms, n_dropouts    zero runs >= 5 ms with signal well above the step on both sides (dropouts, gates)
  flag_dropout              any such run; flag_quantized_tail: the decay sinks below the quantisation step

Noise floor: the band-limited broadband signal from the Lundeby intersection + 50 ms to the
end (>= 0.25 s needed), in 20 ms frames.
  noise_seg_s       length of that segment
  noise_burst_db    loudest frame over the median frame (stationary noise: ~1-3 dB)
  noise_drift_db    median level of the last third minus the first third (fade-outs, gating)
  flag_nonstationary_noise  noise_burst_db > 10 or |noise_drift_db| > 6
"""

from __future__ import annotations

import json
import os
import re
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from rirdb import paths

AUDIT_VERSION = "1.3.0"
THRESH = {"prominence_db": 15.0, "tonal_frac": 0.5, "glide_db": 8.0,
          "not_decaying_active_s": 1.0, "not_decaying_slope": -2.0, "burst_db": 10.0, "drift_db": 6.0, "dropout_ms": 5.0}


def audit_dir(dataset_id: str) -> Path:
    return paths.data_root() / "audit" / "v1" / dataset_id


_SLOPES = np.array([0.25, 0.35, 0.5, 0.7, 1, 1.4, 2, 2.8, 4, 5.6, 8, 11, 16], dtype=float)


def glide_ridge(spec: np.ndarray, f: np.ndarray, t: np.ndarray, per_oct: int = 6) -> tuple[float, float, float]:
    """Strongest straight glide (sweep or chirp) in a spectrogram: (contrast dB, octaves/s, octaves covered).

    The spectrogram (frames x bins, power) is pooled into 1/per_oct-octave bands from 100 Hz; the
    level is normalised per frame (removes the decay) and per band (removes the colouration). Each
    line b(t) = b0 + slope * t is scored by its mean level minus the brighter of the two parallel lines
    1/3 octave above and below: smooth gradients and edges (HF reaching the floor first) score ~0, ridges remain.
    """
    edges = 100 * 2 ** (np.arange(0, np.log2(f[-1] / 100) * per_oct + 1) / per_oct)
    B = len(edges) - 1
    if B < 12 or len(t) < 8:
        return float("nan"), float("nan"), 0.0
    which = np.clip(np.searchsorted(edges, f, side="right") - 1, 0, B - 1)
    cnt = np.bincount(which, minlength=B)
    pw = np.zeros((spec.shape[0], B))
    for b in range(B):
        pw[:, b] = spec[:, which == b].mean(axis=1) if cnt[b] else np.nan
    good = ~np.isnan(pw[0])
    if good.sum() < 12:
        return float("nan"), float("nan"), 0.0
    pw[:, ~good] = np.array([np.interp(np.flatnonzero(~good), np.flatnonzero(good), row[good]) for row in pw])
    R = 10 * np.log10(pw + 1e-30)
    R = np.maximum(R, R.max() - 100)                               # exact zeros (dropouts, windowed corners)
    R = R - np.median(R, axis=1, keepdims=True)
    R = R - np.median(R, axis=0, keepdims=True)
    off = per_oct // 3 + 1                                         # parallel lines 1/3 octave away
    tt = t - t[0]
    best = (-np.inf, float("nan"), 0.0)
    rows = np.arange(len(t))
    for s in np.concatenate([_SLOPES, -_SLOPES]):
        shift = np.round(s * per_oct * tt).astype(int)             # band offset per frame
        b0s = np.arange(-shift.max() if s > 0 else 0, B - (shift.min() if s < 0 else 0))
        bb = b0s[:, None] + shift[None, :]                          # (lines, frames)
        valid = (bb >= off) & (bb < B - off)
        nvalid = valid.sum(axis=1)
        ok = nvalid >= 8
        if not ok.any():
            continue
        bc = np.clip(bb, 0, B - 1)
        on = np.where(valid, R[rows[None, :], bc], 0).sum(axis=1)
        up = np.where(valid, R[rows[None, :], np.clip(bb + off, 0, B - 1)], 0).sum(axis=1)
        dn = np.where(valid, R[rows[None, :], np.clip(bb - off, 0, B - 1)], 0).sum(axis=1)
        span_oct = np.array([(bb[i][valid[i]].max() - bb[i][valid[i]].min()) / per_oct if nvalid[i] else 0.0 for i in range(len(b0s))])
        score = np.where(ok & (span_oct >= 1.5), (on - np.maximum(up, dn)) / np.maximum(nvalid, 1), -np.inf)
        i = int(np.argmax(score))
        if score[i] > best[0]:
            best = (float(score[i]), float(s), float(span_oct[i]))
    return best if np.isfinite(best[0]) else (float("nan"), float("nan"), 0.0)


def dropout_checks(y: np.ndarray, fs: int) -> dict:
    """Runs of exact digital zeros inside the IR (after the onset crop; trailing zeros are trimmed before).

    The smallest non-zero magnitude q approximates the quantisation step. A zero run of >= 5 ms with
    signal well above q on both sides (10 ms RMS > 10 q) is a dropout or a noise gate. Runs inside
    signal of a few q are the decay sinking below the step (16-bit files at a low level): a quantised
    tail, which limits the usable decay range but is not an artefact of its own.
    """
    y = np.asarray(y, dtype=np.float64)
    a = np.abs(y)
    nz = a[a > 0]
    q = float(nz.min()) if nz.size else 0.0
    out = {"zero_frac": float(np.mean(a == 0)), "quant_range_db": float(20 * np.log10(a.max() / q)) if q > 0 else float("nan"),
           "dropout_ms": 0.0, "n_dropouts": 0, "flag_dropout": False, "flag_quantized_tail": False}
    z = a == 0
    if not z.any() or q == 0:
        return out
    d = np.diff(np.concatenate([[0], z.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    long = (ends - starts) >= THRESH["dropout_ms"] * 1e-3 * fs
    w = int(0.01 * fs)
    rms = lambda v: float(np.sqrt(np.mean(v ** 2))) if len(v) else 0.0  # noqa: E731
    drops, quant = [], 0
    for s, e in zip(starts[long], ends[long]):
        pre, post = rms(y[max(s - w, 0):s]), rms(y[e:e + w])
        sides = [v for v, ok in ((pre, s > 0), (post, e < len(y))) if ok]
        if sides and min(sides) > 10 * q:
            drops.append((e - s) / fs * 1e3)
        else:
            quant += 1
    out["n_dropouts"] = len(drops)
    out["dropout_ms"] = float(max(drops)) if drops else 0.0
    out["flag_dropout"] = bool(drops)
    out["flag_quantized_tail"] = bool(quant and out["zero_frac"] > 0.05)
    return out


def content_checks(y: np.ndarray, fs: int, max_s: float = 10.0) -> dict:
    """Sweep / tonal / non-decaying checks on an onset-cropped mono signal."""
    y = np.asarray(y[: int(max_s * fs)], dtype=np.float64)
    n = int(2 ** round(np.log2(0.043 * fs)))
    hop = n // 2
    out = {k: float("nan") for k in ("tonal_frac", "tonal_prom_db", "glide_db", "glide_oct_s", "glide_span_oct", "env_slope_db_s",
                                       "active_s", "crest_db")}
    if len(y) < 2 * n:
        return out | {"flag_sweep_like": False, "flag_tonal": False, "flag_not_decaying": False}
    frames = np.lib.stride_tricks.sliding_window_view(y, n)[::hop] * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1 / fs)
    band = (f >= 100) & (f <= min(16000.0, 0.45 * fs))
    spec, f = spec[:, band], f[band]
    e = spec.sum(axis=1)
    level = 10 * np.log10(e + 1e-30)
    act = level >= level.max() - 30
    idx = np.flatnonzero(act)
    t = idx * hop / fs
    # peak prominence: each bin over the mean of a ring of neighbours (+-1/3 octave, at least +-6 bins),
    # leaving out +-2 bins (the Hann main lobe); stationary noise peaks reach ~8-10 dB, lines >= 15 dB
    nb = len(f)
    k = np.arange(nb)
    half = np.maximum(np.round(f * (2 ** (1 / 3) - 1) / (f[1] - f[0])).astype(int), 6)
    lo_r, hi_r = np.clip(k - half, 0, nb), np.clip(k + half + 1, 0, nb)
    lo_n, hi_n = np.clip(k - 2, 0, nb), np.clip(k + 3, 0, nb)
    S = spec[idx]
    cs = np.concatenate([np.zeros((len(idx), 1)), np.cumsum(S, axis=1)], axis=1)
    ring = (cs[:, hi_r] - cs[:, lo_r]) - (cs[:, hi_n] - cs[:, lo_n])
    ring_n = (hi_r - lo_r) - (hi_n - lo_n)
    prom = 10 * np.log10(S / (ring / np.maximum(ring_n, 1) + 1e-30) + 1e-30)
    # only bins within 40 dB of the frame's strongest bin can be lines (leakage in silent regions cannot)
    prom = np.where(S >= S.max(axis=1, keepdims=True) * 1e-4, prom, -np.inf)
    pk = np.argmax(prom, axis=1)
    pmax = prom[np.arange(len(idx)), pk]
    tonal = pmax >= THRESH["prominence_db"]
    out["tonal_frac"] = float(np.mean(tonal))
    out["tonal_prom_db"] = float(np.median(pmax))
    # glides (sweeps, chirp residue): ridge search over the frames within 40 dB of the loudest
    i40 = np.flatnonzero(level >= level.max() - 40)
    seg = slice(i40[0], i40[-1] + 1)
    out["glide_db"], out["glide_oct_s"], out["glide_span_oct"] = glide_ridge(spec[seg], f, np.arange(seg.start, seg.stop) * hop / fs)
    out["active_s"] = float(t[-1] - t[0] + n / fs) if len(t) else 0.0
    out["env_slope_db_s"] = float(np.polyfit(t, level[idx], 1)[0]) if len(t) >= 3 and np.ptp(t) > 0 else float("nan")
    span = y[: int((t[-1] + n / fs) * fs)] if len(t) else y
    out["crest_db"] = float(20 * np.log10(np.max(np.abs(span)) / (np.sqrt(np.mean(span ** 2)) + 1e-30) + 1e-30))
    out["flag_sweep_like"] = bool(out["glide_db"] >= THRESH["glide_db"])
    out["flag_tonal"] = bool(out["tonal_frac"] > THRESH["tonal_frac"])
    out["flag_not_decaying"] = bool(out["active_s"] > THRESH["not_decaying_active_s"]
                                    and out["env_slope_db_s"] > THRESH["not_decaying_slope"])
    return out


def noise_checks(bb: np.ndarray, fs: int, intersection_s: float, mode: str) -> dict:
    """Stationarity of the noise floor after the broadband Lundeby intersection."""
    out = {"noise_seg_s": 0.0, "noise_burst_db": float("nan"), "noise_drift_db": float("nan"),
           "flag_nonstationary_noise": False}
    if mode != "lundeby" or not np.isfinite(intersection_s):
        return out
    seg = np.asarray(bb[int((intersection_s + 0.05) * fs):], dtype=np.float64)
    out["noise_seg_s"] = len(seg) / fs
    w = int(0.02 * fs)
    if len(seg) < max(int(0.25 * fs), 6 * w):
        return out
    e = np.add.reduceat(seg ** 2, np.arange(0, len(seg) - w + 1, w))[: len(seg) // w] / w
    e = e[e > 0]
    if len(e) < 6:
        return out
    med = np.median(e)
    out["noise_burst_db"] = float(10 * np.log10(e.max() / med))
    k = len(e) // 3
    out["noise_drift_db"] = float(10 * np.log10(np.median(e[-k:]) / np.median(e[:k])))
    out["flag_nonstationary_noise"] = bool(out["noise_burst_db"] > THRESH["burst_db"]
                                           or abs(out["noise_drift_db"]) > THRESH["drift_db"])
    return out


def audit_signal(x: np.ndarray, fs: int, intersection_s: float, mode: str, cfg) -> dict:
    """x: (n_ch, n) selected channels as analysed. Uses the first channel (the analysed one for arrays)."""
    from rirdb.analysis.preprocess import broadband, prepare

    p = prepare(x, fs, cfg)
    y = p.x[0]
    return content_checks(y, fs) | dropout_checks(y, fs) | noise_checks(broadband(y, fs, cfg), fs, intersection_s, mode)


_W: dict = {}


def _init(dataset_id: str):
    from rirdb.adapters import get_adapter
    from rirdb.analysis.config import load_config
    from rirdb.registry import get_dataset

    d = get_dataset(dataset_id)
    _W.update(dataset=d, adapter=get_adapter(d.adapter.name, d.adapter.params), root=paths.files_dir(dataset_id),
              cfg=load_config())


def _audit_row(row: dict) -> dict:
    from rirdb.run import _select_channels

    d, ad, root, cfg = _W["dataset"], _W["adapter"], _W["root"], _W["cfg"]
    t0 = time.perf_counter()
    try:
        x, fs = ad.load(json.loads(row["locator"]), root)
        xs, _ = _select_channels(x, tuple(row["channel_roles"].split(",")),
                                 row.get("reference_role") or d.analysis.reference_role)
        out = audit_signal(xs, fs, row["intersection_s_bb"], row["edc_mode_bb"], cfg)
        out["audit_error"] = ""
    except Exception as e:  # noqa: BLE001 - one bad file must not kill the shard
        out = {"audit_error": f"{type(e).__name__}: {e}", "audit_traceback": traceback.format_exc()[-1500:]}
    out["ir_id"] = row["ir_id"]
    out["audit_seconds"] = time.perf_counter() - t0
    return out


def audit_shard(dataset_id: str, shard: int, n_shards: int, workers: int) -> Path:
    idx = pd.read_parquet(paths.data_root() / "index" / "irs" / f"dataset={dataset_id}" / "part-0.parquet")
    wide = paths.data_root() / "metrics" / "v1" / dataset_id / "wide.parquet"
    import pyarrow.parquet as pq

    have = set(pq.read_schema(wide).names)
    m = pd.read_parquet(wide, columns=[c for c in ("ir_id", "intersection_s_bb", "edc_mode_bb", "error") if c in have])
    # IRs too short for the decay analysis (e.g. MIRACLE's 32 ms) have no broadband intersection
    m = m.reindex(columns=["ir_id", "intersection_s_bb", "edc_mode_bb", "error"])
    m["edc_mode_bb"] = m["edc_mode_bb"].fillna("n/a")
    m = m[m["error"].fillna("") == ""].drop(columns="error")
    rows = idx.merge(m, on="ir_id").sort_values("ir_id").iloc[shard::n_shards].to_dict("records")
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(dataset_id,)) as ex:
        res = list(ex.map(_audit_row, rows, chunksize=4))
    out = pd.DataFrame(res)
    out["audit_version"] = AUDIT_VERSION
    d = audit_dir(dataset_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"shard-{shard:05d}-of-{n_shards:05d}.parquet"
    out.to_parquet(p, index=False)
    return p


_SHARD = re.compile(r"shard-(\d{5})-of-(\d{5})\.parquet$")


def merge_audit(dataset_id: str) -> Path:
    d = audit_dir(dataset_id)
    shards = [p for p in d.glob("shard-*.parquet") if _SHARD.search(p.name)]
    if not shards:
        raise FileNotFoundError(f"no audit shards in {d}")
    n = int(_SHARD.search(max(shards, key=lambda p: p.stat().st_mtime).name).group(2))
    cur = sorted(p for p in shards if int(_SHARD.search(p.name).group(2)) == n)
    missing = sorted(set(range(n)) - {int(_SHARD.search(p.name).group(1)) for p in cur})
    if missing:
        raise RuntimeError(f"{dataset_id}: {len(missing)} of {n} audit shards missing, e.g. {missing[:5]}")
    df = pd.concat([pd.read_parquet(p) for p in cur], ignore_index=True).drop_duplicates("ir_id", keep="last")
    out = d / "audit.parquet"
    df.sort_values("ir_id").to_parquet(out, index=False)
    return out


def workers_default() -> int:
    return int(os.environ.get("SLURM_CPUS_PER_TASK", 4))
