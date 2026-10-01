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


def test_ndarray_channel_subset_and_source_records(tmp_path):
    """UPV_RIR_DB layout: MATLAB v5 h_ctrl[time, sources, channels]; keep one ear pair, records = sources."""
    import scipy.io

    rng = np.random.default_rng(1)
    a = rng.standard_normal((50, 8, 4))
    d = tmp_path / "RC1" / "SC2"
    d.mkdir(parents=True)
    scipy.io.savemat(d / "DH_RC1_SC2_Z05_RIR.mat", {"h_ctrl": a})
    params = {"glob": "**/DH_*_RIR.mat", "pattern": r"(?P<cond>RC\d)/(?P<src>SC\d)/DH_RC\d_SC\d_(?P<rcv>Z\d+)_RIR\.mat$",
              "container": "mat", "array": "h_ctrl", "time_axis": 0, "channel_axis": 2, "record_axes": [1],
              "record_is": "src", "channels": [2, 3], "roles": ["L", "R"], "fs": 44100}
    ad = get_adapter("ndarray", params)
    recs = list(ad.iter_records(_dataset(params), tmp_path))
    assert len(recs) == 8
    assert [r.src_key for r in recs[:2]] == ["SC2-0", "SC2-1"]
    assert {r.rcv_key for r in recs} == {"Z05"} and {r.condition_key for r in recs} == {"RC1"}
    assert recs[0].channel_roles == ("L", "R")
    for r in recs:
        x, fs = ad.load(r.locator, tmp_path)
        assert fs == 44100
        np.testing.assert_array_equal(x, a[:, r.locator["idx"][0], 2:4].T)


def test_sofa_first_per_source(tmp_path):
    """Repeated measurements (same SourcePosition) collapse to the first one, whatever the layout."""
    ir = np.random.default_rng(2).standard_normal((6, 2, 20))
    sp = np.array([[1, 0, 1.5], [1, 0, 1.5], [-2, 4, 0], [-2, 4, 0], [1, 0, 0], [1, 0, 0]], dtype=float)
    with h5py.File(tmp_path / "pos_1.0X_0.0Y.sofa", "w") as h:
        h["Data.IR"] = ir
        h["Data.SamplingRate"] = np.array([48000.0])
        h["SourcePosition"] = sp
    params = {"glob": "*.sofa", "pattern": r"_(?P<rcv>-?[\d.]+X_-?[\d.]+Y)\.sofa$", "first_per_source": True,
              "capture_format": "sdm_array", "reference_role": "mic_1"}
    ds = SimpleNamespace(id="toy", ir_kinds=["room"], adapter=SimpleNamespace(name="sofa", params=params),
                         analysis=SimpleNamespace(reference_role=None))
    ad = get_adapter("sofa", params)
    recs = list(ad.iter_records(ds, tmp_path))
    assert [r.locator["m"] for r in recs] == [0, 2, 4]
    assert len({r.src_key for r in recs}) == 3 and {r.rcv_key for r in recs} == {"1.0X_0.0Y"}
    x, fs = ad.load(recs[1].locator, tmp_path)
    assert fs == 48000
    np.testing.assert_array_equal(x, ir[2])


def test_sofa_measurements_as_receivers(tmp_path):
    """MRTD layout: one file per loudspeaker, m = receiver position; all-zero SourcePosition = unknown."""
    ir = np.random.default_rng(3).standard_normal((5, 4, 20))
    with h5py.File(tmp_path / "offices_zoom_ls_2.sofa", "w") as h:
        h["Data.IR"] = ir
        h["Data.SamplingRate"] = np.array([48000.0])
        h["SourcePosition"] = np.zeros((5, 3))
        h["ListenerPosition"] = np.arange(15, dtype=float).reshape(5, 3)
    params = {"glob": "*.sofa", "pattern": r"^(?P<room>[a-z-]+)_zoom_(?P<src>ls_\d)\.sofa$", "m_is": "rcv",
              "roles": ["FLU", "FRD", "BLD", "BRU"], "capture_format": "tetra_raw", "reference_role": "mean"}
    ds = SimpleNamespace(id="toy", ir_kinds=["room"], adapter=SimpleNamespace(name="sofa", params=params),
                         analysis=SimpleNamespace(reference_role=None))
    recs = list(get_adapter("sofa", params).iter_records(ds, tmp_path))
    assert len(recs) == 5 and {r.src_key for r in recs} == {"ls_2"}
    assert [r.rcv_key for r in recs] == [f"m{i}" for i in range(5)]
    assert recs[0].src_pos is None and recs[1].rcv_pos == (3.0, 4.0, 5.0)
    assert recs[0].room_key == "offices" and recs[0].channel_roles == ("FLU", "FRD", "BLD", "BRU")


def test_ndarray_crop(tmp_path):
    a = np.random.default_rng(4).standard_normal((2, 3, 1000)).astype(np.float32)
    np.save(tmp_path / "deconvolved.npy", a)
    params = {"glob": "*.npy", "container": "npy", "time_axis": 2, "record_axes": [0, 1], "fs": 100, "crop_s": 2.5}
    ad = get_adapter("ndarray", params)
    recs = list(ad.iter_records(_dataset(params), tmp_path))
    assert len(recs) == 6 and {r.n_samples for r in recs} == {250}
    x, fs = ad.load(recs[4].locator, tmp_path)
    np.testing.assert_array_equal(x, a[1, 1, :250][None, :])
