"""Quality flags and the overall analysis grade."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pyfar as pf

from rirdb.analysis.config import Config

C_SOUND = 343.0


@lru_cache(maxsize=8)
def _air_ceiling(centres: tuple, rh: tuple, temp: tuple) -> np.ndarray:
    """Largest physically possible T (s) per band when air is the only absorber:
    Sabine with zero wall absorption, T = 55.3 / (4 m c), m from ISO 9613-1
    minimised over the humidity/temperature ranges (most lenient ceiling)."""
    freqs = np.asarray(centres, dtype=float)
    ok = freqs > 50
    m_min = np.full(freqs.size, np.nan)
    rhs = np.linspace(rh[0] / 100, rh[1] / 100, 9)
    temps = np.linspace(temp[0], temp[1], 5)
    ms = []
    for t in temps:
        for h in rhs:
            _, m, _ = pf.constants.air_attenuation(float(t), freqs[ok], float(h))
            ms.append(np.ravel(m.freq))
    m_min[ok] = np.min(np.vstack(ms), axis=0)
    return 55.3 / (4 * m_min * C_SOUND)


def air_absorption_ceiling(centres, cfg: Config) -> np.ndarray:
    q = cfg.quality
    return _air_ceiling(tuple(float(c) for c in centres), tuple(q.air_ceiling_humidity_percent),
                        tuple(q.air_ceiling_temperature_c))


def grade(valid_t30: dict, valid_t20: dict, valid_edt_any: bool) -> str:
    """A: T30 valid 125 Hz-4 kHz; B: T20/T30 valid 250 Hz-2 kHz; C: only EDT or partial; D: nothing."""
    need_a = [125, 250, 500, 1000, 2000, 4000]
    need_b = [250, 500, 1000, 2000]
    if all(valid_t30.get(f, False) for f in need_a):
        return "A"
    if all(valid_t30.get(f, False) or valid_t20.get(f, False) for f in need_b):
        return "B"
    if valid_edt_any or any(valid_t20.values()) or any(valid_t30.values()):
        return "C"
    return "D"
