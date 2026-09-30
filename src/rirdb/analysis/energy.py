"""Energy ratios (ISO 3382-1), tonal balance, DRR and STI (IEC 60268-16).

C50/C80/D50/Ts are computed from the noise-compensated EDCs of `decay.py`
through pyrato (clarity, definition, center_time). DRR follows the ACE
challenge convention (full band, +-8 ms direct window); STI uses pyrato's
IEC 60268-16:2020 indirect method.
"""

from __future__ import annotations

import warnings

import numpy as np
import pyfar as pf
import pyrato as ra

from rirdb.analysis.config import Config
from rirdb.analysis.decay import DecayResult


def energy_ratios(dec: DecayResult, cfg: Config) -> dict[str, np.ndarray]:
    """C50, C80, D50, Ts per band (NaN where the EDC is unusable)."""
    n_b, n = dec.edc.shape
    t = np.arange(n) / dec.fs
    out = {k: np.full(n_b, np.nan) for k in ("C50", "C80", "D50", "Ts")}
    valid = np.zeros(n_b, dtype=bool)
    need = cfg.decay.min_range_db["EDT"]
    for b in range(n_b):
        if dec.mode[b] == "failed" or not np.isfinite(dec.edc[b, 0]):
            continue
        td = pf.TimeData(dec.edc[b][None, :], t)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                out["C50"][b] = float(np.ravel(ra.parameters.clarity(td, 50))[0])
                out["C80"][b] = float(np.ravel(ra.parameters.clarity(td, 80))[0])
                out["D50"][b] = float(np.ravel(ra.parameters.definition(td, 50))[0])
                out["Ts"][b] = float(np.ravel(ra.parameters.center_time(td))[0])
            except ValueError:
                continue
        valid[b] = bool(dec.decay_range_db[b] >= need and dec.intersection_s[b] > 0.08)
    out["valid"] = valid
    return out


def tonal_balance(t_best: dict) -> dict[str, float]:
    """Beranek's bass ratio (warmth) and treble ratio (brilliance) from band decay times."""
    g = lambda f: t_best.get(f, np.nan)  # noqa: E731
    mid = g(500) + g(1000)
    return {
        "br": float((g(125) + g(250)) / mid) if np.isfinite(mid) and mid > 0 else float("nan"),
        "tr": float((g(2000) + g(4000)) / mid) if np.isfinite(mid) and mid > 0 else float("nan"),
    }


def drr(x: np.ndarray, fs: int, intersection_s: float, subtract_noise: bool, cfg: Config) -> dict[str, float]:
    """Full-band direct-to-reverberant ratio, ACE challenge convention (Eaton et al. 2016).

    Direct: energy within +-direct_half_window_ms of the direct peak (searched
    within 10 ms of the onset); ACE's ground-truth CSVs give the window as
    "DRR direct +/-: 0.008" s. Reverberant: the energy after the direct window.
    Both are integrated on the unfiltered signal up to the broadband Lundeby
    intersection time with the mean tail power subtracted (`subtract_noise`),
    so measurement noise is not counted as reverberation; the tail below the
    noise floor is neglected. Without a floor (`subtract_noise=False`) the whole
    signal is used as is.
    """
    out = {"drr_bb": float("nan"), "direct_peak_ms": float("nan")}
    if not np.isfinite(intersection_s):
        return out
    e = np.asarray(x, dtype=np.float64) ** 2
    n_tail = max(int(round(cfg.preprocess.noise_tail_fraction * e.size)), 1)
    noise = float(np.mean(e[-n_tail:])) if subtract_noise else 0.0
    half = int(round(cfg.drr.direct_half_window_ms * 1e-3 * fs))
    search = min(e.size, int(0.010 * fs))                # direct sound within 10 ms of the onset
    k = int(np.argmax(e[:max(search, 1)]))
    out["direct_peak_ms"] = k / fs * 1e3
    a, b = max(k - half, 0), min(k + half + 1, e.size)
    end = min(max(int(round(intersection_s * fs)), b), e.size)
    direct = e[a:b].sum() - noise * (b - a)
    rev = e[b:end].sum() - noise * (end - b)
    if direct > 0 and rev > 0:
        out["drr_bb"] = float(10 * np.log10(direct / rev))
    return out


def sti(x: np.ndarray, fs: int, intersection_s: float, tail_ok: bool, cfg: Config) -> dict:
    """Room-only STI (no ambient noise, no auditory masking; uncalibrated IR).

    The IR is truncated at the broadband Lundeby intersection time so that the
    measurement noise floor is not mistaken for reverberation, then zero-padded
    to the 1.6 s minimum of IEC 60268-16:2020 (6.2).
    """
    out = {"sti": float("nan"), "mtf": None, "valid": False}
    if fs < 2 * 8000 * 2 ** 0.5 * 1.0 or not np.isfinite(intersection_s):
        return out   # 8 kHz octave must lie below Nyquist
    n_keep = min(len(x), int(round(intersection_s * fs)))
    n_min = int(np.ceil(cfg.sti.min_length_s * fs))
    y = np.zeros(max(n_keep, n_min))
    y[:n_keep] = x[:n_keep]
    sig = pf.Signal(y, fs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            mtf = ra.parameters.modulation_transfer_function(sig, "acoustical", None, np.inf)
            val = ra.parameters.speech_transmission_index_indirect(sig, "acoustical", None, np.inf)
        except ValueError:
            return out
    out.update(sti=float(np.ravel(val)[0]), mtf=np.asarray(mtf, dtype=np.float32), valid=bool(tail_ok))
    return out
