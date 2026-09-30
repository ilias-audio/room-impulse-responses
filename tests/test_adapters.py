"""Adapters return exactly the right samples, as (channels, time), for any axis layout."""

from __future__ import annotations

from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from rirdb.adapters import get_adapter


def _dataset(params):
    return SimpleNamespace(id="toy", ir_kinds=["room"], adapter=SimpleNamespace(name="ndarray", params=params),
                           analysis=SimpleNamespace(reference_role=None))


@pytest.mark.parametrize("layout", ["src_mic_time", "time_src_mic", "src_time_chan"])
@pytest.mark.parametrize("container", ["h5", "npy"])
def test_ndarray_adapter_axes(tmp_path, layout, container):
    rng = np.random.default_rng(0)
    if layout == "src_mic_time":
        a = rng.standard_normal((3, 4, 50)).astype(np.float32)
        params = {"time_axis": 2, "record_axes": [0, 1]}
        expect = lambda i, j: a[i, j][None, :]  # noqa: E731
    elif layout == "time_src_mic":
        a = rng.standard_normal((50, 3, 4)).astype(np.float32)
        params = {"time_axis": 0, "record_axes": [1, 2]}
        expect = lambda i, j: a[:, i, j][None, :]  # noqa: E731
    else:  # one record per source, 4 simultaneous channels, time before channels
        a = rng.standard_normal((3, 50, 4)).astype(np.float32)
        params = {"time_axis": 1, "channel_axis": 2, "record_axes": [0]}
        expect = lambda i, j=None: a[i].T  # noqa: E731
    if container == "h5":
        with h5py.File(tmp_path / "toy.h5", "w") as h:
            h["ir"] = a
        params.update(glob="*.h5", container="h5", array="ir", fs=16000)
    else:
        np.save(tmp_path / "toy.npy", a)
        params.update(glob="*.npy", container="npy", fs=16000)
    ds = _dataset(params)
    ad = get_adapter("ndarray", params)
    recs = list(ad.iter_records(ds, tmp_path))
    n_expected = 12 if layout != "src_time_chan" else 3
    assert len(recs) == n_expected
    assert len({r.local_key for r in recs}) == n_expected
    for r in recs:
        x, fs = ad.load(r.locator, tmp_path)
        assert fs == 16000
        want = expect(*r.locator["idx"])
        assert x.shape == want.shape
        np.testing.assert_allclose(x, want, rtol=0, atol=0)
