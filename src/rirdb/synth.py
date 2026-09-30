"""Synthetic impulse responses with known ground truth, for validating the analyzer.

h(t) = a * delta(t) + n(t) * exp(-delta t),  delta = 3 ln(10) / T
(amplitude decay; energy falls 60 dB in T seconds), plus optional stationary
noise at a given peak-to-noise ratio, pre-delay and zero padding.

Truth values:
  - T20 = T30 = EDT = T for every band (the decay is white).
  - STI (no noise, no masking): m(F) = 1 / sqrt(1 + (2 pi F T / 13.8)^2) in
    every band, so with the IEC 60268-16:2020 weights STI = MTI.
  - C_te, D50, Ts, DRR: from the realised (noise-free) signal energies, so
    tests check the implementation rather than the noise statistics.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MOD_FREQS = np.array([0.63, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5, 3.15, 4.0, 5.0, 6.3, 8.0, 10.0, 12.5])


@dataclass
class SynthIR:
    x: np.ndarray        # (n,) with pre-delay / noise / padding applied
    clean: np.ndarray    # (n_clean,) noise-free IR starting at the direct sound
    fs: int
    t60: float
    onset: int           # index of the direct sound in x


def exp_decay_ir(fs: int = 48000, t60: float = 1.0, duration: float | None = None,
                 direct_amp: float = 0.0, pnr_db: float | None = None, pre_delay_s: float = 0.0,
                 zero_pad_s: float = 0.0, seed: int = 0) -> SynthIR:
    rng = np.random.default_rng(seed)
    duration = duration or max(1.5 * t60, 0.5)
    n = int(round(duration * fs))
    d = 3 * np.log(10) / t60
    t = np.arange(n) / fs
    clean = rng.standard_normal(n) * np.exp(-d * t) * 0.1
    clean[0] += direct_amp
    x = clean.copy()
    if pnr_db is not None and np.isfinite(pnr_db):
        # extra 1 s of noise-only tail so the noise floor is well defined
        x = np.concatenate([x, np.zeros(fs)])
        peak = np.max(clean ** 2)
        sigma = np.sqrt(peak / 10 ** (pnr_db / 10))
        x = x + rng.standard_normal(x.size) * sigma
    pre = int(round(pre_delay_s * fs))
    if pre:
        lead = rng.standard_normal(pre) * (np.std(x[-fs // 10:]) if pnr_db is not None else 0.0)
        x = np.concatenate([lead, x])
    if zero_pad_s:
        x = np.concatenate([x, np.zeros(int(round(zero_pad_s * fs)))])
    return SynthIR(x=x, clean=clean, fs=fs, t60=t60, onset=pre)


def truth_energy(clean: np.ndarray, fs: int) -> dict[str, float]:
    e = clean ** 2
    t = np.arange(e.size) / fs
    tot = e.sum()
    k50, k80 = int(round(0.05 * fs)), int(round(0.08 * fs))
    return {
        "c50": 10 * np.log10(e[:k50].sum() / e[k50:].sum()),
        "c80": 10 * np.log10(e[:k80].sum() / e[k80:].sum()),
        "d50": e[:k50].sum() / tot,
        "ts": float(np.sum(t * e) / tot),
    }


def truth_drr(clean: np.ndarray, fs: int, half_ms: float = 8.0) -> float:
    e = clean ** 2
    k = int(np.argmax(np.abs(clean[: int(0.01 * fs)])))
    h = int(round(half_ms * 1e-3 * fs))
    return float(10 * np.log10(e[max(k - h, 0): k + h + 1].sum() / e[k + h + 1:].sum()))


def truth_sti(t60: float) -> float:
    m = 1.0 / np.sqrt(1.0 + (2 * np.pi * MOD_FREQS * t60 / 13.8) ** 2)
    snr = np.clip(10 * np.log10(m / (1 - m)), -15, 15)
    return float(np.mean((snr + 15) / 30))
