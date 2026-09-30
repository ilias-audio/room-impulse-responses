"""Temporal structure: echo density profiles and mixing time.

- Normalised echo density (NED), Abel & Huang (2006), AES 121st Conv. #6985:
  eta(t) = (1 / erfc(1/sqrt 2)) * sum_tau w(tau) 1{|h(t+tau)| > sigma(t)},
  sigma(t) = sqrt(sum_tau w(tau) h^2(t+tau)), w a unit-sum Hann window of
  20 ms. eta is ~0 for sparse early reflections and ~1 for Gaussian noise.
  Mixing time: first time eta reaches 1 (the signal-based predictor evaluated
  by Lindau et al. 2012, JAES 60(11)).
- Kurtosis echo-density profile (EDP): copied byte-identical from
  FDN2FDN/scripts/talk/edp.py (itself from learn-fdn-iir/fdn_iir/analysis.py),
  so values stay comparable with the DAFx26 paper's EDP numbers.
"""

from __future__ import annotations

import numpy as np
from scipy.special import erfc
from scipy.stats import kurtosis as scipy_kurtosis

from rirdb.analysis.config import Config

_ERFC = erfc(1.0 / np.sqrt(2.0))


def normalized_echo_density(x: np.ndarray, fs: int, win_ms: float, hop_ms: float, max_s: float = 1.0):
    """NED profile (Abel & Huang 2006). Returns (times_s, eta)."""
    x = np.asarray(x, dtype=np.float64)
    n_win = int(round(win_ms * 1e-3 * fs)) | 1          # odd, centred
    hop = max(int(round(hop_ms * 1e-3 * fs)), 1)
    n = min(len(x), int(max_s * fs) + n_win)
    if n < n_win:
        return np.zeros(0), np.zeros(0)
    w = np.hanning(n_win + 2)[1:-1]
    w /= w.sum()
    frames = np.lib.stride_tricks.sliding_window_view(x[:n], n_win)[::hop]
    sigma = np.sqrt(frames ** 2 @ w)
    eta = ((np.abs(frames) > sigma[:, None]).astype(np.float64) @ w) / _ERFC
    times = (np.arange(len(eta)) * hop + n_win // 2) / fs
    return times, eta


def mixing_time_ned(times: np.ndarray, eta: np.ndarray, threshold: float) -> float:
    idx = np.flatnonzero(eta >= threshold)
    return float(times[idx[0]] * 1e3) if idx.size else float("nan")


# --- verbatim from FDN2FDN/scripts/talk/edp.py (keep byte-identical) --------
def compute_echo_density_profile(rir_signal, fs, window_ms=10.0, hop_ms=2.0):
    if hasattr(rir_signal, 'time'):
        rir = np.squeeze(rir_signal.time)
    else:
        rir = np.asarray(rir_signal).squeeze()
    win_samples = int(window_ms * fs / 1000)
    hop_samples = max(1, int(hop_ms * fs / 1000))
    n_frames = (len(rir) - win_samples) // hop_samples
    if n_frames < 1:
        return np.array([0.0]), np.array([0.0])
    time_axis = np.zeros(n_frames)
    ned_profile = np.zeros(n_frames)
    for i in range(n_frames):
        start = i * hop_samples
        segment = rir[start:start + win_samples]
        time_axis[i] = (start + win_samples / 2) / fs
        kurt = scipy_kurtosis(segment, fisher=False)
        if kurt > 0:
            ned_profile[i] = min(1.0, 3.0 / kurt)
        else:
            ned_profile[i] = 0.0
    return time_axis, ned_profile


def mixing_time_ms(time_axis, ned_profile, threshold=0.85):
    """First time EDP stays at/above ``threshold`` for 3 consecutive frames, in ms.

    Same rule as ``fdn_iir/analysis.py:estimate_mixing_time``; returns ``nan``
    instead of a 30 ms fallback so a curve that never mixes is visibly absent
    rather than silently plotted at a made-up value.
    """
    count = 0
    for i in range(len(ned_profile)):
        if ned_profile[i] >= threshold:
            count += 1
            if count >= 3:
                return float(time_axis[i - 2] * 1000.0)
        else:
            count = 0
    return float('nan')
# ---------------------------------------------------------------------------


def temporal(x: np.ndarray, fs: int, cfg: Config) -> tuple[dict, dict]:
    """Scalars and profiles for one broadband channel starting at the onset."""
    ec = cfg.echo_density
    t_ned, eta = normalized_echo_density(x, fs, ec.ned_window_ms, ec.ned_hop_ms, max_s=1.0)
    t_k, edp = compute_echo_density_profile(x[: int(1.05 * fs)], fs, ec.kurtosis_window_ms, ec.kurtosis_hop_ms)
    scalars = {
        "t_mix_ned_ms": mixing_time_ned(t_ned, eta, ec.mixing_threshold),
        "t_mix_edp_ms": mixing_time_ms(t_k, edp, ec.kurtosis_mixing_threshold),
        "ned_mean_0_50ms": float(np.mean(eta[t_ned <= 0.05])) if np.any(t_ned <= 0.05) else float("nan"),
    }
    profiles = {"ned": (t_ned, eta), "edp": (t_k, edp)}
    return scalars, profiles
