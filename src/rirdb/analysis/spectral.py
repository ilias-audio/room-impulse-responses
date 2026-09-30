"""Spectral descriptors, energy decay relief and per-bin decay times.

Levels are relative (the IRs are uncalibrated): band levels are referenced to
the 1 kHz octave band, the magnitude response to its 1 kHz value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import stft

from rirdb.analysis.config import Config


def frac_octave_grid(fractions: int, f_lo: float = 20.0, f_hi: float = 20000.0) -> np.ndarray:
    """Base-2 fractional-octave centre frequencies from f_lo to f_hi, anchored at 1 kHz."""
    k_lo = int(np.ceil(fractions * np.log2(f_lo / 1000.0)))
    k_hi = int(np.floor(fractions * np.log2(f_hi / 1000.0)))
    return 1000.0 * 2.0 ** (np.arange(k_lo, k_hi + 1) / fractions)


def _band_edges(centres: np.ndarray, fractions: int) -> tuple[np.ndarray, np.ndarray]:
    half = 2.0 ** (1.0 / (2 * fractions))
    return centres / half, centres * half


def magnitude_response(x: np.ndarray, fs: int, fractions: int) -> tuple[np.ndarray, np.ndarray]:
    """Fractional-octave smoothed power response in dB re its 1 kHz band (NaN above Nyquist)."""
    grid = frac_octave_grid(fractions)
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / fs)
    lo, hi = _band_edges(grid, fractions)
    p = np.full(grid.size, np.nan)
    cs = np.concatenate(([0.0], np.cumsum(spec)))
    i_lo, i_hi = np.searchsorted(f, lo), np.searchsorted(f, hi)
    ok = (hi < fs / 2) & (i_hi > i_lo)
    p[ok] = (cs[i_hi[ok]] - cs[i_lo[ok]]) / (i_hi[ok] - i_lo[ok])
    ref = p[np.argmin(np.abs(grid - 1000.0))]
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 10 * np.log10(p / ref)
    return grid, db


def band_levels(centres: np.ndarray, bands: np.ndarray) -> dict[str, float]:
    """Octave-band energy in dB re the 1 kHz band, and the spectral tilt (dB/octave)."""
    energy = np.sum(bands ** 2, axis=-1)
    out: dict[str, float] = {}
    if 1000 not in centres.astype(int):
        return out
    ref = energy[list(centres.astype(int)).index(1000)]
    lv = 10 * np.log10(energy / ref + 1e-300)
    for c, v in zip(centres.astype(int), lv):
        out[f"level_{c}"] = float(v)
    sel = centres >= 125
    if sel.sum() >= 3:
        out["spectral_tilt_db_per_oct"] = float(np.polyfit(np.log2(centres[sel]), lv[sel], 1)[0])
    return out


def centroids(x: np.ndarray, fs: int, split_s: float = 0.05, end_s: float | None = None) -> dict[str, float]:
    """Spectral centroid of the early (0-50 ms) and late (50 ms - end) parts."""
    k = int(split_s * fs)
    end = len(x) if end_s is None or not np.isfinite(end_s) else min(len(x), int(end_s * fs))

    def c(seg):
        if seg.size < 64:
            return float("nan")
        s = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(seg.size, 1 / fs)
        return float(np.sum(f * s) / np.sum(s)) if np.sum(s) > 0 else float("nan")

    return {"centroid_early_hz": c(x[:k]), "centroid_late_hz": c(x[k:end])}


def edr(x: np.ndarray, fs: int, cfg: Config) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Energy decay relief (Jot 1992) on a fractional-octave x fixed-time grid.

    Backward-integrated STFT power per bin, summed into bands, in dB re the
    global maximum. Returns (band_centres_hz, frame_times_s, edr_db[band, frame]).
    """
    fc = cfg.features
    hop = max(int(round(fc.edr_hop_ms * 1e-3 * fs)), 1)
    n_fft = 1 << int(np.ceil(np.log2(0.04 * fs)))           # ~40 ms window
    n_frames = int(round(fc.edr_max_s / (fc.edr_hop_ms * 1e-3)))
    f, _, Z = stft(x, fs=fs, nperseg=n_fft, noverlap=n_fft - hop, window="hann", boundary=None, padded=True)
    P = np.abs(Z) ** 2
    R = np.flip(np.cumsum(np.flip(P, axis=-1), axis=-1), axis=-1)
    grid = frac_octave_grid(fc.edr_fractions, 50.0, 20000.0)
    lo, hi = _band_edges(grid, fc.edr_fractions)
    out = np.full((grid.size, n_frames), np.nan)
    m = min(R.shape[1], n_frames)
    for i, (a, b) in enumerate(zip(lo, hi)):
        sel = (f >= a) & (f < b)
        if b >= fs / 2 or not sel.any():
            continue
        out[i, :m] = R[sel, :m].sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 10 * np.log10(out / np.nanmax(out))
    return grid, np.arange(n_frames) * fc.edr_hop_ms * 1e-3, db


# --- ported from FDN2FDN/src/data/edr_rt60.py (per_bin_rt60 + helpers) ----
@dataclass
class EDRRt60Result:
    freqs_hz: np.ndarray
    t60: np.ndarray
    valid: np.ndarray
    dr_db: np.ndarray
    noise_floor_db: np.ndarray


def _lundeby_crossing(env_db: np.ndarray, margin_db: float, iters: int = 2) -> int:
    n = env_db.shape[0]
    if n < 8:
        return n
    tail = max(n // 10, 3)
    floor = float(np.mean(env_db[-tail:]))
    cross = n
    for _ in range(iters):
        above = np.where(env_db > floor + margin_db)[0]
        if above.size == 0:
            return n
        cross = int(above[-1])
        if cross < n - 2:
            floor = float(np.mean(env_db[cross:]))
        else:
            break
    return max(cross, 8)


def _median_smooth_masked(y: np.ndarray, mask: np.ndarray, w: int) -> np.ndarray:
    out = y.copy()
    half = w // 2
    n = y.shape[0]
    for i in range(n):
        if not mask[i]:
            continue
        lo, hi = max(0, i - half), min(n, i + half + 1)
        vals = y[lo:hi][mask[lo:hi]]
        if vals.size:
            out[i] = float(np.median(vals))
    return out


def per_bin_rt60(ir: np.ndarray, fs: int, n_fft: int = 4096, hop: int = 512,
                 fit_db: tuple[float, float] = (-5.0, -25.0), noise_margin_db: float = 10.0,
                 f_lo: float = 50.0, f_hi: float = 16000.0, smooth_frames: int = 5,
                 smooth_bins: int = 5) -> EDRRt60Result:
    """Per-STFT-bin RT60 via truncated backward integration (FDN2FDN estimator)."""
    x = np.asarray(ir, dtype=np.float64)
    freqs, _times, Z = stft(x, fs=fs, nperseg=n_fft, noverlap=n_fft - hop,
                            window="hann", boundary=None, padded=False)
    P = np.abs(Z) ** 2
    F, T = P.shape
    lo, hi = fit_db
    t60 = np.full(F, np.nan)
    valid = np.zeros(F, dtype=bool)
    dr_db = np.zeros(F)
    floor_db = np.full(F, -np.inf)
    frame_dt = hop / fs
    band = (freqs >= f_lo) & (freqs <= f_hi)
    for k in range(F):
        if not band[k]:
            continue
        p = P[k]
        if p.max() <= 0:
            continue
        env = p.copy()
        if smooth_frames > 1 and T >= smooth_frames:
            env = np.convolve(env, np.ones(smooth_frames) / smooth_frames, mode="same")
        env_db = 10.0 * np.log10(env / (env.max() + 1e-30) + 1e-30)
        cross = _lundeby_crossing(env_db, noise_margin_db)
        floor_db[k] = float(np.mean(env_db[max(cross - 1, 0):])) if cross < T else -120.0
        seg = p[:cross]
        if seg.size < 8:
            continue
        edc = np.flip(np.cumsum(np.flip(seg)))
        edc_db = 10.0 * np.log10(edc / (edc[0] + 1e-30) + 1e-30)
        dr = float(edc_db[0] - edc_db[-1])
        dr_db[k] = dr
        if dr < (abs(hi) + noise_margin_db):
            continue
        idx = np.where((edc_db <= lo) & (edc_db >= hi))[0]
        if idx.size < 8:
            continue
        slope = np.polyfit(idx * frame_dt, edc_db[idx], 1)[0]
        if slope >= -1e-9:
            continue
        t60[k] = -60.0 / slope
        valid[k] = True
    if smooth_bins > 1:
        t60 = _median_smooth_masked(t60, valid, smooth_bins)
    return EDRRt60Result(freqs_hz=freqs, t60=t60, valid=valid, dr_db=dr_db, noise_floor_db=floor_db)
# ---------------------------------------------------------------------------


def t60_curve(x: np.ndarray, fs: int, fractions: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """Per-bin T60 (FDN2FDN estimator) resampled onto a fractional-octave grid (NaN where invalid)."""
    n_fft = 4096 if fs >= 32000 else 2048
    grid = frac_octave_grid(fractions, 50.0, 16000.0)
    out = np.full(grid.size, np.nan)
    if len(x) < 4 * n_fft:          # too short for a per-bin decay fit
        return grid, out
    r = per_bin_rt60(x, fs, n_fft=n_fft, hop=n_fft // 8, f_hi=min(16000.0, 0.45 * fs))
    ok = r.valid & np.isfinite(r.t60) & (r.t60 > 0)
    if ok.sum() >= 4:
        lo, hi = _band_edges(grid, fractions)
        for i, (a, b) in enumerate(zip(lo, hi)):
            sel = ok & (r.freqs_hz >= a) & (r.freqs_hz < b)
            if sel.any():
                out[i] = float(np.exp(np.median(np.log(r.t60[sel]))))
    return grid, out
