"""Dataset adapters, looked up by the registry's `adapter.name`."""

from __future__ import annotations

from rirdb.adapters.base import Adapter, IRRecord, make_ir_id, slug
from rirdb.adapters.custom import AirMatAdapter, MatArrayAdapter, OpenAirAdapter, OpenSLR28Adapter, SofaAdapter
from rirdb.adapters.wav_tree import WavTreeAdapter

ADAPTERS: dict[str, type] = {
    "wav_tree": WavTreeAdapter,
    "sofa": SofaAdapter,
    "openair": OpenAirAdapter,
    "air_mat": AirMatAdapter,
    "openslr28": OpenSLR28Adapter,
    "mat_array": MatArrayAdapter,
}


def get_adapter(name: str | None, params: dict | None = None) -> Adapter:
    if not name:
        raise KeyError("dataset has no adapter configured yet (run `rirdb probe` and set adapter.name)")
    try:
        adapter = ADAPTERS[name]()
    except KeyError as e:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(ADAPTERS)}") from e
    adapter._params = params or {}      # registry adapter.params, for adapters whose load() needs them
    return adapter


__all__ = ["ADAPTERS", "Adapter", "IRRecord", "get_adapter", "make_ir_id", "slug"]
