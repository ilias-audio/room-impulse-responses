"""Fixed-shape representations stored per IR (HDF5 feature shards).

All on fixed grids so they stack across datasets with different fs:
EDC (2 ms grid + log-time grid), log-mel spectrogram at 48 kHz, EDR, NED/EDP
profiles, magnitude response, per-bin T60 curve, MTF.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.signal import stft

from rirdb.analysis.config import Config


def edc_grids(edc: np.ndarray, fs: int, cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    """EDC(s) in dB on a linear 2 ms grid up to 8 s and on a 256-point log-time grid (1 ms-8 s)."""
    fc = cfg.features
    edc = np.atleast_2d(edc)
    n = edc.shape[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 10 * np.log10(edc)
    t_lin = np.arange(0, fc.edc_max_s, fc.edc_grid_ms * 1e-3)
    t_log = np.geomspace(1e-3, fc.edc_max_s, fc.edc_logtime_points)
    t = np.arange(n) / fs

    def sample(tt):
        out = np.full((edc.shape[0], tt.size), np.nan)
        inside = tt < t[-1]
        for b in range(edc.shape[0]):
            out[b, inside] = np.interp(tt[inside], t, db[b], left=np.nan, right=np.nan)
        return out

    return sample(t_lin).astype(np.float16), sample(t_log).astype(np.float16)


@lru_cache(maxsize=2)
def _mel_fb(n_fft: int, sr: int, n_mels: int) -> np.ndarray:
    from torchaudio.functional import melscale_fbanks

    return melscale_fbanks(n_fft // 2 + 1, 0.0, sr / 2, n_mels, sr, norm="slaney", mel_scale="slaney").numpy()


def log_mel(x: np.ndarray, fs: int, cfg: Config) -> np.ndarray:
    """Log-mel spectrogram (dB re max) of the onset-aligned IR at 48 kHz, fixed 4 s."""
    import soxr

    fc = cfg.features
    sr = fc.mel_sr
    y = soxr.resample(np.asarray(x, dtype=np.float64), fs, sr) if fs != sr else np.asarray(x, dtype=np.float64)
    n_keep = int(fc.mel_max_s * sr)
    y = np.pad(y[:n_keep], (0, max(0, n_keep - len(y))))
    hop = int(round(fc.mel_hop_ms * 1e-3 * sr))
    _, _, Z = stft(y, fs=sr, nperseg=fc.mel_n_fft, noverlap=fc.mel_n_fft - hop, window="hann",
                   boundary="zeros", padded=True)
    P = np.abs(Z) ** 2                       # (freq, frames)
    mel = _mel_fb(fc.mel_n_fft, sr, fc.mel_n_mels).T @ P
    n_frames = int(round(fc.mel_max_s / (fc.mel_hop_ms * 1e-3)))
    mel = mel[:, :n_frames]
    db = 10 * np.log10(mel / (mel.max() + 1e-30) + 1e-12)
    return db.astype(np.float16)


def fix_length(v: np.ndarray, n: int) -> np.ndarray:
    out = np.full(n, np.nan, dtype=np.float32)
    m = min(n, len(v))
    out[:m] = v[:m]
    return out
