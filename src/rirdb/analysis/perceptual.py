"""Perceptual layer: parameters expressed in just-noticeable differences.

z = x / JND for additive JNDs, z = ln(x) / ln(1 + JND) for relative ones
(registry/jnd.yaml). Euclidean distance between two IRs in z space then reads
as "how many JNDs apart" along each perceptual dimension.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import yaml

from rirdb import paths


@lru_cache(maxsize=1)
def jnd_table() -> dict:
    return yaml.safe_load((paths.REGISTRY_DIR / "jnd.yaml").read_text())["parameters"]


def jnd_coordinates(scalars: dict) -> dict[str, float]:
    out = {}
    for name, spec in jnd_table().items():
        x = scalars.get(name, np.nan)
        if x is None or not np.isfinite(x):
            out[f"z_{name}"] = float("nan")
            continue
        if spec["kind"] == "relative":
            out[f"z_{name}"] = float(np.log(x) / np.log1p(spec["jnd"])) if x > 0 else float("nan")
        else:
            out[f"z_{name}"] = float(x / spec["jnd"])
    return out
