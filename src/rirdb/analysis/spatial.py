"""Spatial parameters: early lateral energy fraction (JLF) and IACC (ISO 3382-1).

JLF needs an omnidirectional and a lateral figure-of-eight response: the W and
Y channels of first-order Ambisonics. FuMa W carries a -3 dB (1/sqrt 2) gain,
so it is scaled by sqrt 2 to represent omni pressure; ambiX (SN3D) W is
already unity gain. The result is only meaningful if the array's x axis
pointed at the source (flagged `orientation_unknown` otherwise).

IACC follows ISO 3382-1 Annex B: normalised interaural cross-correlation over
lags of +-1 ms, for the early (0-80 ms), late (80 ms-1 s) and all (0-1 s)
windows, in the 500 Hz, 1 kHz and 2 kHz octave bands (IACC_E3 = mean of the
three) and broadband.
"""

from __future__ import annotations

import numpy as np
import pyfar as pf
import pyrato as ra
from scipy.signal import correlate

from rirdb.analysis.config import Config
from rirdb.analysis.preprocess import octave_bands


def jlf(w: np.ndarray, y: np.ndarray, fs: int, fuma: bool, cfg: Config) -> dict[str, float]:
    """JLF per octave band 125-1000 Hz and JLF_low = their mean (ISO 3382-1 Table A.1)."""
    w = np.asarray(w, dtype=np.float64) * (np.sqrt(2.0) if fuma else 1.0)
    centres, wb = octave_bands(w, fs, cfg)
    _, yb = octave_bands(np.asarray(y, dtype=np.float64), fs, cfg)
    out: dict[str, float] = {}
    vals = []
    edc_w = ra.edc.schroeder_integration(pf.Signal(wb, fs))
    edc_y = ra.edc.schroeder_integration(pf.Signal(yb, fs))
    ratio = np.ravel(ra.parameters.early_lateral_energy_fraction(edc_w, edc_y))
    for c, r in zip(centres, ratio):
        out[f"jlf_{int(c)}"] = float(r)
        if 125 <= c <= 1000:
            vals.append(float(r))
    out["jlf_low"] = float(np.mean(vals)) if len(vals) == 4 else float("nan")
    return out


def _iacc(l: np.ndarray, r: np.ndarray, a: int, b: int, max_lag: int) -> float:
    ls, rs = l[a:b], r[a:b]
    den = np.sqrt(np.sum(ls ** 2) * np.sum(rs ** 2))
    if den == 0:
        return float("nan")
    cc = correlate(ls, rs, mode="full", method="fft")
    mid = len(rs) - 1
    lo, hi = max(mid - max_lag, 0), min(mid + max_lag + 1, len(cc))
    return float(np.max(np.abs(cc[lo:hi])) / den)


def iacc(left: np.ndarray, right: np.ndarray, fs: int, cfg: Config) -> dict[str, float]:
    """IACC_E/L/A per octave band (500, 1k, 2k Hz), their means (…3) and broadband."""
    bc = cfg.binaural
    max_lag = int(round(bc.iacc_max_lag_ms * 1e-3 * fs))
    e_end = int(round(bc.early_ms * 1e-3 * fs))
    n = min(len(left), len(right))
    l_end = min(n, int(fs * 1.0))
    windows = {"e": (0, min(e_end, n)), "l": (min(e_end, n), l_end), "a": (0, l_end)}
    out: dict[str, float] = {}
    for key, (a, b) in windows.items():
        out[f"iacc_{key}_bb"] = _iacc(left[:n], right[:n], a, b, max_lag) if b - a > max_lag else float("nan")
    centres, lb = octave_bands(left[:n], fs, cfg)
    _, rb = octave_bands(right[:n], fs, cfg)
    for key, (a, b) in windows.items():
        vals = []
        for c, lx, rx in zip(centres, lb, rb):
            if int(c) in bc.iacc_bands_hz:
                v = _iacc(lx, rx, a, b, max_lag) if b - a > max_lag else float("nan")
                out[f"iacc_{key}_{int(c)}"] = v
                vals.append(v)
        out[f"iacc_{key}3"] = float(np.mean(vals)) if len(vals) == len(bc.iacc_bands_hz) else float("nan")
    out["one_minus_iacc_e3"] = 1.0 - out["iacc_e3"] if np.isfinite(out["iacc_e3"]) else float("nan")
    return out
