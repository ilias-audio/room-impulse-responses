"""Analyzer configuration (configs/analyzer_v1.yaml) and its content hash."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

from rirdb import paths

DEFAULT_CONFIG = paths.REPO_ROOT / "configs" / "analyzer_v1.yaml"


class Config(dict):
    """Nested dict with attribute access; `sha256` identifies the exact settings."""

    sha256: str = ""

    def __getattr__(self, key):
        try:
            v = self[key]
        except KeyError as e:
            raise AttributeError(key) from e
        return Config(v) if isinstance(v, dict) else v


@lru_cache(maxsize=4)
def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    raw = Path(path).read_bytes()
    cfg = Config(yaml.safe_load(raw))
    cfg.sha256 = hashlib.sha256(raw).hexdigest()
    return cfg
