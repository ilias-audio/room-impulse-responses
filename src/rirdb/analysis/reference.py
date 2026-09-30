"""Independent plain-numpy reference implementation (for validation only).

Written from the standards, not from pyrato, so the two can be compared:
Schroeder backward integration (Schroeder 1965) and the ISO 3382 least-squares
fit between the -5/-25/-35 dB (or 0/-10 dB for EDT) crossings, plus ISO 3382
energy ratios. No noise handling: use on noise-free signals, or compare only
where the analyzer reports valid values.
"""

from __future__ import annotations

import numpy as np

RANGES = {"EDT": (-0.1, -10.1), "T20": (-5.0, -25.0), "T30": (-5.0, -35.0)}


def schroeder_db(x: np.ndarray) -> np.ndarray:
    e = np.asarray(x, dtype=np.float64) ** 2
    s = np.flip(np.cumsum(np.flip(e)))
    with np.errstate(divide="ignore"):
        return 10 * np.log10(s / s[0])


def decay_time(x: np.ndarray, fs: int, kind: str = "T30") -> float:
    edc = schroeder_db(x)
    upper, lower = RANGES[kind]
    i0 = int(np.argmin(np.abs(edc - upper)))
    i1 = int(np.argmin(np.abs(edc - lower)))
    if i1 - i0 < 3:
        return float("nan")
    t = np.arange(i0, i1) / fs
    slope = np.polyfit(t, edc[i0:i1], 1)[0]
    return float(-60.0 / slope)


def energy_ratios(x: np.ndarray, fs: int) -> dict[str, float]:
    e = np.asarray(x, dtype=np.float64) ** 2
    t = np.arange(e.size) / fs
    k50, k80 = int(round(0.05 * fs)), int(round(0.08 * fs))
    return {
        "c50": float(10 * np.log10(e[:k50].sum() / e[k50:].sum())),
        "c80": float(10 * np.log10(e[:k80].sum() / e[k80:].sum())),
        "d50": float(e[:k50].sum() / e.sum()),
        "ts": float(np.sum(t * e) / e.sum()),
    }


def iso_relative_sigma(kind: str, bandwidth_hz: float, t60: float) -> float:
    """Relative standard deviation of a decay time from one integrated IR
    (ISO 3382-2:2008 Annex A; the integrated-IR method counts as ~10 averaged
    interrupted-noise decays). EDT is not covered by the standard: 1.5 x T20."""
    bt = bandwidth_hz * t60
    if kind == "T30":
        return 0.55 * np.sqrt((1 + 1.52 / 10) / bt)
    s20 = 0.88 * np.sqrt((1 + 1.90 / 10) / bt)
    return s20 if kind == "T20" else 1.5 * s20
