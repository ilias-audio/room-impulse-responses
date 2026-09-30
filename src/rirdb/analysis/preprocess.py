"""Preprocessing: raw statistics, digital-silence trimming, noise estimate, onset, crop.

Order matters. pyfar's onset detection and pyrato's 'auto' noise estimates read
the last 10 % of the signal; on zero-padded files that is digital silence and
yields hundreds of dB of fictitious dynamic range (see
FDN2FDN/docs/decisions/rir-measurement-validity-2026-08-19.md). So trailing
digital silence is trimmed first and the noise level is always passed
explicitly downstream.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pyfar as pf

from rirdb.analysis.config import Config


@dataclass
class Prepared:
    x: np.ndarray                 # (n_ch, n) onset-cropped, float64
    fs: int
    onset: int                    # onset index in the trimmed signal (earliest channel)
    noise_power: np.ndarray       # (n_ch,) mean-square of the trimmed tail (explicit noise)
    pre_onset: np.ndarray         # (n_ch, m) samples before the onset (minus a guard)
    stats: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)


def _clip_runs(x: np.ndarray, run: int) -> bool:
    """True if any channel has >= `run` consecutive samples at its peak magnitude."""
    for ch in x:
        peak = np.max(np.abs(ch))
        if peak == 0:
            continue
        at_peak = np.abs(ch) >= peak * (1 - 1e-4)
        if run <= 1:
            return bool(at_peak.any())
        # length of the longest run of True values
        padded = np.concatenate(([0], at_peak.astype(np.int8), [0]))
        edges = np.flatnonzero(np.diff(padded))
        if edges.size and np.max(edges[1::2] - edges[::2]) >= run:
            return True
    return False


def prepare(x: np.ndarray, fs: int, cfg: Config) -> Prepared:
    """Trim, estimate noise, detect the ISO 3382 onset and crop a multichannel IR."""
    x = np.atleast_2d(np.asarray(x, dtype=np.float64))
    pc = cfg.preprocess
    stats: dict = {"fs": fs, "n_channels": x.shape[0], "n_samples_raw": x.shape[1],
                   "duration_raw_s": x.shape[1] / fs}
    flags: dict = {}

    flags["nonfinite"] = bool(not np.all(np.isfinite(x)))
    if flags["nonfinite"]:
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(x)))
    flags["all_zero"] = peak == 0.0
    stats["peak_abs"] = peak
    flags["clipped"] = _clip_runs(x, cfg.quality.clip_run_samples) and peak > 0
    dc = np.mean(x, axis=-1)
    stats["dc_offset_db"] = float(20 * np.log10(np.max(np.abs(dc)) / peak + 1e-30)) if peak > 0 else float("nan")
    flags["dc_offset"] = bool(stats["dc_offset_db"] > cfg.quality.dc_offset_db)

    # --- trim leading/trailing digital silence (any channel above threshold)
    active = np.any(np.abs(x) > pc.digital_silence_abs, axis=0)
    if not active.any():
        stats.update(leading_silence_s=0.0, trailing_zeros_s=0.0, duration_s=0.0)
        return Prepared(x[:, :0], fs, 0, np.zeros(x.shape[0]), x[:, :0], stats, flags)
    first, last = int(np.argmax(active)), int(len(active) - np.argmax(active[::-1]))
    stats["leading_silence_s"] = first / fs
    stats["trailing_zeros_s"] = (x.shape[1] - last) / fs
    xt = x[:, first:last]

    # --- explicit noise estimate from the tail of the trimmed signal
    n_tail = max(int(round(pc.noise_tail_fraction * xt.shape[1])), 1)
    noise_power = np.mean(xt[:, -n_tail:] ** 2, axis=-1)

    # --- onset (ISO 3382-1 A.3.4): first sample within 20 dB of the peak
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        starts = np.atleast_1d(pf.dsp.find_impulse_response_start(
            pf.Signal(xt, fs), threshold=pc.onset_threshold_db))
    flags["onset_low_psnr_warning"] = any("SNR" in str(m.message) or "PSNR" in str(m.message) for m in w)
    # pyfar returns the last sample *below* the threshold (-1 if the peak is sample 0)
    starts = np.maximum(starts, 0)
    onset = int(np.min(starts))
    stats["onset_s"] = (first + onset) / fs
    stats["onset_spread_ms"] = float((np.max(starts) - np.min(starts)) / fs * 1e3)

    guard = int(round(pc.pre_onset_guard_ms * 1e-3 * fs))
    pre = xt[:, : max(onset - guard, 0)]
    xc = xt[:, onset:]
    n_max = int(pc.max_duration_s * fs)
    stats["cropped_to_max_duration"] = bool(xc.shape[1] > n_max)
    xc = xc[:, :n_max]
    stats["duration_s"] = xc.shape[1] / fs
    flags["short"] = bool(stats["duration_s"] < pc.min_duration_s)
    flags["low_fs"] = bool(fs < cfg.quality.low_fs_hz)

    # pre-onset content well above the tail noise: sweep distortion products,
    # time aliasing or a non-causal processing artefact
    if pre.shape[1] >= int(0.005 * fs):
        pre_power = np.mean(pre ** 2, axis=-1)
        excess = 10 * np.log10(np.max(pre_power / (noise_power + 1e-30)) + 1e-30)
        stats["pre_onset_excess_db"] = float(excess)
        stats["pre_onset_energy_db"] = float(10 * np.log10(np.sum(pre ** 2) / (np.sum(xc ** 2) + 1e-30) + 1e-30))
        stats["pre_onset_level_db"] = float(10 * np.log10(np.max(pre_power) / (peak ** 2) + 1e-30)) if peak > 0 else float("nan")
        # artefact = well above the tail noise AND not negligible relative to the IR itself
        # (processed tails can sit at -90 dB, making harmless -60 dB pre-ringing look "30 dB above noise")
        flags["pre_onset_energy"] = bool(stats["pre_onset_excess_db"] > cfg.quality.pre_onset_excess_db
                                         and stats["pre_onset_level_db"] > cfg.quality.pre_onset_min_level_db)
    else:
        stats["pre_onset_excess_db"] = float("nan")
        stats["pre_onset_level_db"] = float("nan")
        stats["pre_onset_energy_db"] = float("nan")
        flags["pre_onset_energy"] = False

    return Prepared(xc, fs, onset, noise_power, pre, stats, flags)


def octave_bands(x: np.ndarray, fs: int, cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    """IEC 61260-1 octave-band filtering of one channel.

    Returns (centres_hz, band_signals[n_bands, n]) for the configured centres
    whose upper -3 dB edge lies below `max_upper_edge_fraction_of_nyquist`.
    """
    bc = cfg.bands
    centres = np.asarray(bc.octave_centres_hz, dtype=float)
    upper = centres * 2 ** 0.5
    keep = upper <= bc.max_upper_edge_fraction_of_nyquist * fs / 2
    centres = centres[keep]
    if centres.size == 0:
        return centres, np.zeros((0, x.shape[-1]))
    lo, hi = centres[0] / 2 ** 0.25, centres[-1] * 2 ** 0.25
    sig = pf.dsp.filter.fractional_octave_bands(
        pf.Signal(np.asarray(x, dtype=np.float64), fs), num_fractions=1,
        frequency_range=(lo, hi), order=bc.filter_order)
    y = np.squeeze(sig.time, axis=tuple(range(1, sig.time.ndim - 1))) if sig.time.ndim > 2 else sig.time
    # same band selection as the filter bank itself (exact IEC centres)
    exact = np.asarray(pf.constants.fractional_octave_frequencies_exact(1, (lo, hi))[0], dtype=float)
    if len(exact) != y.shape[0]:
        raise RuntimeError(f"band count mismatch: {len(exact)} vs {y.shape[0]}")
    idx = [int(np.argmin(np.abs(np.log2(exact / c)))) for c in centres]
    return centres, y[idx]


def broadband(x: np.ndarray, fs: int, cfg: Config) -> np.ndarray:
    """Band-limit to the octave span (lower edge of the lowest band to the upper
    edge of the highest band allowed at this fs): the 'broadband' signal."""
    from scipy.signal import butter, sosfilt

    lo_c, hi_c = cfg.bands.broadband_range_hz
    lo = lo_c / 2 ** 0.5
    hi = min(hi_c * 2 ** 0.5, cfg.bands.max_upper_edge_fraction_of_nyquist * fs / 2)
    sos = butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    # causal, like the octave filters: a zero-phase filter would smear the
    # direct sound back across the onset crop
    return sosfilt(sos, np.asarray(x, dtype=np.float64), axis=-1)
