"""Adapter interface: turn a dataset's files into canonical IR records.

An adapter enumerates `IRRecord`s (metadata only; cheap) and loads the audio
of a record on demand. Generic adapters cover most datasets through registry
parameters (`adapter.params` in registry/datasets.yaml), so adding a dataset,
including a simulated one later, is usually only a registry entry.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

import numpy as np


def slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in str(text)).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "unknown"


def make_ir_id(dataset_id: str, local_key: str) -> str:
    return f"{dataset_id}:{hashlib.blake2b(local_key.encode(), digest_size=8).hexdigest()}"


@dataclass
class IRRecord:
    dataset_id: str
    local_key: str                         # stable natural key inside the dataset
    room_key: str                          # slug; room_id = <dataset>/<room_key>
    capture_format: str
    channel_roles: tuple[str, ...]
    fs: int
    n_samples: int
    locator: dict                          # {relpath, container, ...} relative to files/
    condition_key: str | None = None       # e.g. panel configuration, absorption scenario
    src_key: str | None = None
    rcv_key: str | None = None
    src_pos: tuple | None = None
    rcv_pos: tuple | None = None
    sh_norm: str | None = None
    orientation_known: bool = True
    room_label: str | None = None          # human-readable room / space name
    category_hint: str | None = None       # e.g. folder name, used by rooms/<id>.csv curation
    ir_kind: str = "room"
    extra: dict = field(default_factory=dict)

    @property
    def ir_id(self) -> str:
        return make_ir_id(self.dataset_id, self.local_key)

    @property
    def room_id(self) -> str:
        return f"{self.dataset_id}/{self.room_key}"

    def to_row(self) -> dict:
        d = asdict(self)
        d["ir_id"] = self.ir_id
        d["room_id"] = self.room_id
        d["channel_roles"] = ",".join(self.channel_roles)
        d["n_channels"] = len(self.channel_roles)
        d["duration_s"] = self.n_samples / self.fs if self.fs else float("nan")
        for k in ("src_pos", "rcv_pos"):
            v = d.pop(k)
            for axis, val in zip("xyz", v or (None, None, None)):
                d[f"{k[:3]}_{axis}"] = None if val is None else float(val)
        import json

        d["locator"] = json.dumps(self.locator, sort_keys=True)
        d["extra"] = json.dumps(self.extra, sort_keys=True, default=str)
        return d


class Adapter(Protocol):
    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]: ...

    def load(self, locator: dict, root: Path) -> tuple[np.ndarray, int]: ...
