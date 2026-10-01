"""Audit checks: sweeps and tonal content are caught, decaying noise IRs pass; noise-floor bursts and drift are caught."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import fftconvolve

from rirdb.audit import content_checks, noise_checks
from rirdb.synth import exp_decay_ir

FS = 48000


def _sweep(dur=5.0, f0=20.0, f1=20000.0):
    t = np.arange(int(dur * FS)) / FS
    k = np.log(f1 / f0)
    return np.sin(2 * np.pi * f0 * dur / k * (np.exp(t * k / dur) - 1))


@pytest.mark.parametrize("t60", [0.3, 1.0, 3.0, 8.0])
def test_ir_passes(t60):
    s = exp_decay_ir(fs=FS, t60=t60, direct_amp=1.0, pnr_db=70, seed=1)
    r = content_checks(s.x, FS)
    assert not r["flag_sweep_like"] and not r["flag_tonal"] and not r["flag_not_decaying"]


def test_dry_and_recorded_sweeps_flagged():
    sw = _sweep()
    assert content_checks(sw, FS)["flag_sweep_like"]
    room = exp_decay_ir(fs=FS, t60=1.5, direct_amp=1.0, seed=2).clean
    rec = fftconvolve(sw, room)[: len(sw) + FS] + 1e-4 * np.random.default_rng(0).standard_normal(len(sw) + FS)
    r = content_checks(rec, FS)
    assert r["flag_sweep_like"] and r["flag_not_decaying"]


def test_stationary_noise_floor_passes():
    rng = np.random.default_rng(3)
    floor = rng.standard_normal(2 * FS) * 1e-3
    r = noise_checks(np.concatenate([np.zeros(FS), floor]), FS, intersection_s=1.0, mode="lundeby")
    assert r["noise_burst_db"] < 3 and abs(r["noise_drift_db"]) < 1 and not r["flag_nonstationary_noise"]


def test_noise_burst_and_drift_flagged():
    rng = np.random.default_rng(4)
    floor = rng.standard_normal(2 * FS) * 1e-3
    burst = floor.copy()
    burst[FS: FS + 480] *= 30                                 # 10 ms, +30 dB
    assert noise_checks(burst, FS, 0.0, "lundeby")["flag_nonstationary_noise"]
    fade = floor * np.linspace(1, 0.05, floor.size)          # fade-out window on the tail
    r = noise_checks(fade, FS, 0.0, "lundeby")
    assert r["noise_drift_db"] < -6 and r["flag_nonstationary_noise"]


def test_no_floor_segment_is_not_judged():
    r = noise_checks(np.ones(FS), FS, float("nan"), "schroeder_nofloor")
    assert np.isnan(r["noise_burst_db"]) and not r["flag_nonstationary_noise"]


def test_hum_is_tonal_not_sweep():
    s = exp_decay_ir(fs=FS, t60=1.0, direct_amp=1.0, seed=7)
    t = np.arange(s.clean.size) / FS
    r = content_checks(s.clean + 0.05 * np.sin(2 * np.pi * 110 * t), FS)
    assert r["flag_tonal"] and not r["flag_sweep_like"]


@pytest.mark.parametrize("cut", [300.0, 1000.0])
def test_bass_heavy_decay_is_not_tonal(cut):
    from scipy.signal import butter, sosfilt
    s = exp_decay_ir(fs=FS, t60=1.5, direct_amp=1.0, seed=8)
    y = sosfilt(butter(4, cut, fs=FS, output="sos"), s.clean)
    assert not content_checks(y, FS)["flag_tonal"]


def test_dropouts():
    from rirdb.audit import dropout_checks
    y = exp_decay_ir(fs=FS, t60=1.0, direct_amp=1.0, pnr_db=60, seed=9).x
    assert not dropout_checks(y, FS)["flag_dropout"]
    y = y.copy()
    y[FS // 2: FS // 2 + 480] = 0.0                            # 10 ms gap
    r = dropout_checks(y, FS)
    assert r["flag_dropout"] and r["n_dropouts"] == 1 and abs(r["dropout_ms"] - 10) < 0.1 and not r["flag_quantized_tail"]


def test_quantized_tail_is_not_a_dropout():
    from rirdb.audit import dropout_checks
    y = exp_decay_ir(fs=FS, t60=1.0, direct_amp=1.0, seed=10).clean
    y = np.round(y / np.max(np.abs(y)) * 30) / 32768            # 16-bit at a low level: the tail rounds to zero
    r = dropout_checks(y, FS)
    assert not r["flag_dropout"] and r["flag_quantized_tail"] and 20 < r["quant_range_db"] < 40
