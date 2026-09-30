"""Energy decay curves and decay times (ISO 3382-1/-2) with explicit validity.

Per band (and broadband):
  1. Lundeby et al. (1995) intersection time and noise level
     (pyrato.edc.intersection_time_lundeby), with the noise level passed in.
  2. Noise-compensated Schroeder EDC (pyrato.edc.energy_decay_curve_lundeby),
     normalised per band (each band starts at 0 dB, which the ISO regression
     in pyrato.parameters.reverberation_time_linear_regression assumes).
  3. EDT / T20 / T30 / LDT by least squares over the ISO ranges, *only* when
     the usable decay range supports it: the bottom of the evaluation range
     must stay >= 10 dB above the noise (EDT 20 dB, T20 35 dB, T30 45 dB) and
     the EDC must actually reach it. pyrato silently fits a shorter range
     otherwise, so this module never calls it without that check.

IRs without a stationary noise floor (digitally faded or zero-padded
production IRs) make Lundeby fail by construction; for those the plain
Schroeder integral is the correct EDC and the decay range is measured
against the energy at the end of the file.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pyfar as pf
import pyrato as ra

from rirdb.analysis.config import Config

DECAY_RANGES = {"EDT": (-0.1, -10.1), "T20": (-5.0, -25.0), "T30": (-5.0, -35.0), "LDT": (-25.0, -35.0)}


@dataclass
class DecayResult:
    labels: list                 # band labels: centre Hz (int) or "bb"
    edc: np.ndarray              # (n_b, n) linear EDC, normalised per band, NaN after truncation
    fs: int
    mode: list                   # per band: lundeby | schroeder_nofloor | failed
    intersection_s: np.ndarray   # (n_b,)
    noise_power: np.ndarray      # (n_b,) final noise estimate (mean square)
    decay_range_db: np.ndarray   # (n_b,) smoothed peak level minus noise level
    values: dict = field(default_factory=dict)   # "T30" -> (n_b,) seconds
    valid: dict = field(default_factory=dict)    # "T30" -> (n_b,) bool
    extra: dict = field(default_factory=dict)    # curvature, xi, ...


def _smoothing_s(label) -> float:
    return 0.030 if label == "bb" else (800.0 / float(label) + 10.0) * 1e-3


def _moving_average(e: np.ndarray, n: int) -> np.ndarray:
    n = max(int(n), 1)
    if n == 1 or e.size < n:
        return e
    c = np.cumsum(np.concatenate(([0.0], e)))
    return (c[n:] - c[:-n]) / n


def _tail_is_stationary(e: np.ndarray, fs: int, win_s: float) -> bool:
    """True if the last 20 % of the energy envelope looks like a noise floor
    (no systematic decay > 3 dB across four consecutive segments)."""
    n = e.size
    seg = n // 20
    if seg < max(int(win_s * fs), 8):
        return False
    levels = [10 * np.log10(np.mean(e[n - (k + 1) * seg: n - k * seg]) + 1e-300) for k in range(4)][::-1]
    return (levels[0] - levels[-1]) < 3.0 and (max(levels) - min(levels)) < 4.5


def _regression_r2(t: np.ndarray, y: np.ndarray) -> float:
    if t.size < 3:
        return float("nan")
    r = np.corrcoef(t, y)[0, 1]
    return float(r * r)


def analyze_decay(y: np.ndarray, fs: int, labels: list, noise_init: np.ndarray, cfg: Config) -> DecayResult:
    """Decay analysis of band signals y (n_b, n), all starting at the onset."""
    y = np.atleast_2d(np.asarray(y, dtype=np.float64))
    n_b, n = y.shape
    e = y ** 2
    smoothing = [("broadband" if lab == "bb" else float(lab)) for lab in labels]

    it = np.full(n_b, np.nan)
    noise = np.full(n_b, np.nan)
    edc = np.full((n_b, n), np.nan)
    mode = ["failed"] * n_b
    dr = np.full(n_b, np.nan)

    for b in range(n_b):
        sig = pf.Signal(y[b], fs)
        win = _smoothing_s(labels[b])
        stationary = _tail_is_stationary(e[b], fs, win)
        ok = False
        if stationary:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    it_b, _, noise_b = ra.edc.intersection_time_lundeby(
                        sig, smoothing_parameter=smoothing[b], initial_noise_power=np.atleast_1d(noise_init[b]),
                        is_energy=False, time_shift=False, channel_independent=False,
                        failure_policy="warning")
                    it_b, noise_b = float(np.ravel(it_b)[0]), float(np.ravel(noise_b)[0])
                    if np.isfinite(it_b) and it_b > 0:
                        edc_b = ra.edc.energy_decay_curve_lundeby(
                            sig, smoothing_parameter=smoothing[b], noise_level=np.atleast_1d(noise_init[b]),
                            is_energy=False, time_shift=False, channel_independent=True, normalize=True)
                        edc[b] = np.ravel(edc_b.time)
                        it[b], noise[b], mode[b], ok = it_b, noise_b, "lundeby", True
                except (ValueError, IndexError, np.linalg.LinAlgError):
                    ok = False
        if not ok and not stationary:
            # no noise floor: plain Schroeder integral is the correct EDC
            s = np.flip(np.cumsum(np.flip(e[b])))
            if s[0] > 0:
                edc[b] = s / s[0]
                tail = max(n // 20, 1)
                noise[b] = float(np.mean(e[b, -tail:]))
                it[b] = n / fs
                mode[b] = "schroeder_nofloor"
        sm = _moving_average(e[b], win * fs)
        if np.isfinite(noise[b]) and noise[b] > 0 and sm.size:
            dr[b] = 10 * np.log10(np.max(sm) / noise[b])
        elif mode[b] != "failed":
            dr[b] = np.inf   # exact digital silence after the decay

    res = DecayResult(labels=list(labels), edc=edc, fs=fs, mode=mode, intersection_s=it,
                      noise_power=noise, decay_range_db=dr)
    t = np.arange(n) / fs
    min_range = cfg.decay.min_range_db
    with np.errstate(divide="ignore", invalid="ignore"):
        edc_db = 10 * np.log10(edc)
    for name, (upper, lower) in DECAY_RANGES.items():
        vals = np.full(n_b, np.nan)
        valid = np.zeros(n_b, dtype=bool)
        need = min_range.get("T30" if name == "LDT" else name, 45)
        for b in range(n_b):
            if mode[b] == "failed" or not np.isfinite(edc_db[b, 0]):
                continue
            reached = np.nanmin(edc_db[b]) <= lower
            # for the no-floor fallback, the fit range must end well before the file end
            if mode[b] == "schroeder_nofloor" and reached:
                idx_lower = int(np.nanargmin(np.abs(edc_db[b] - lower)))
                reached = idx_lower < 0.95 * n
            if not reached:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tv = ra.parameters.reverberation_time_linear_regression(
                    pf.TimeData(edc[b][None, :], t), T=name)
            vals[b] = float(np.ravel(tv)[0])
            valid[b] = bool(np.isfinite(vals[b]) and vals[b] > 0 and dr[b] >= need)
        res.values[name], res.valid[name] = vals, valid

    # curvature (ISO 3382-2 Annex B) and non-linearity xi over the widest valid range
    t20, t30 = res.values["T20"], res.values["T30"]
    both = res.valid["T20"] & res.valid["T30"]
    res.extra["curvature_pct"] = np.where(both, 100.0 * (t30 / t20 - 1.0), np.nan)
    xi = np.full(n_b, np.nan)
    for b in range(n_b):
        rng = "T30" if res.valid["T30"][b] else ("T20" if res.valid["T20"][b] else None)
        if rng is None:
            continue
        upper, lower = DECAY_RANGES[rng]
        sel = (edc_db[b] <= upper) & (edc_db[b] >= lower) & np.isfinite(edc_db[b])
        xi[b] = 1000.0 * (1.0 - _regression_r2(t[sel], edc_db[b][sel]))
    res.extra["nonlinearity_permille"] = xi

    # best available decay time per band (T30 > T20)
    best = np.where(res.valid["T30"], t30, np.where(res.valid["T20"], t20, np.nan))
    res.extra["t_best"] = best
    res.extra["t_best_src"] = np.where(res.valid["T30"], "T30", np.where(res.valid["T20"], "T20", ""))
    return res


def chu_t30(y_bb: np.ndarray, fs: int, noise_init: float) -> float:
    """Broadband T30 from the Chu + Lundeby EDC, as a method cross-check."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            edc = ra.edc.energy_decay_curve_chu_lundeby(
                pf.Signal(y_bb, fs), smoothing_parameter="broadband", noise_level=np.atleast_1d(noise_init),
                is_energy=False, time_shift=False, channel_independent=True, normalize=True)
            e = np.ravel(edc.time)
            if not np.isfinite(e[0]) or np.nanmin(10 * np.log10(e)) > -35:
                return float("nan")
            return float(np.ravel(ra.parameters.reverberation_time_linear_regression(edc, T="T30"))[0])
        except (ValueError, IndexError, TypeError, np.linalg.LinAlgError):
            return float("nan")
