"""Dataset adapters, looked up by the registry's `adapter.name`."""

from __future__ import annotations

from rirdb.adapters.base import Adapter, IRRecord, make_ir_id, slug
from rirdb.adapters.wav_tree import WavTreeAdapter

ADAPTERS: dict[str, type] = {
    "wav_tree": WavTreeAdapter,
}


def get_adapter(name: str | None) -> Adapter:
    if not name:
        raise KeyError("dataset has no adapter configured yet (run `rirdb probe` and set adapter.name)")
    try:
        return ADAPTERS[name]()
    except KeyError as e:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(ADAPTERS)}") from e


__all__ = ["ADAPTERS", "Adapter", "IRRecord", "get_adapter", "make_ir_id", "slug"]
