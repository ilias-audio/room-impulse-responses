"""Analyzer validation on synthetic IRs with known ground truth.

Run via sbatch (never on the login node):
    sbatch -p computeshort -t 1:0:0 jobs/quick_cpu.sh pixi run pytest -q -n 8 tests/
"""

from __future__ import annotations

import numpy as np
import pyfar as pf
import pytest

from rirdb.analysis import reference as ref
from rirdb.analysis.config import load_config
from rirdb.analysis.pipeline import analyze_ir
from rirdb.analysis.preprocess import broadband, octave_bands, prepare
from rirdb.analysis.quality import air_absorption_ceiling
from rirdb.analysis.reference import iso_relative_sigma
from rirdb.synth import exp_decay_ir, truth_drr, truth_energy, truth_sti

CFG = load_config()


def run(x, fs, **kw):
    return analyze_ir(x, fs, cfg=CFG, want_features=kw.pop("want_features", False), **kw).scalars


def rel(a, b):
    return abs(a - b) / b


def band_width(b, fs):
    if b == "bb":
        return min(8000 * 2 ** 0.5, 0.45 * fs) - 63 / 2 ** 0.5
    return 0.7071 * b


def iso_tol(name, b, fs, t60):
    """3 sigma of the single-realisation spread (ISO 3382-2 Annex A) + 1 % bias allowance."""
    return 3 * iso_relative_sigma(name.upper(), band_width(b, fs), t60) + 0.01


@pytest.mark.parametrize("fs", [16000, 44100, 48000, 96000])
@pytest.mark.parametrize("t60", [0.3, 1.0, 3.0])
@pytest.mark.parametrize("pnr", [None, 85.0])
def test_decay_times(fs, t60, pnr):
    s = exp_decay_ir(fs=fs, t60=t60, pnr_db=pnr, seed=1)
    r = run(s.x, fs)
    bands = [b for b in (250, 500, 1000, 2000, 4000) if b * 2 ** 0.5 <= 0.9 * fs / 2]
    errors = []
    for b in bands + ["bb"]:
        for name in ("t30", "t20", "edt"):
            if not r[f"valid_{name}_{b}"]:
                errors.append((b, name, "invalid", r[f"decay_range_db_{b}"]))
            elif rel(r[f"{name}_{b}"], t60) > iso_tol(name, b, fs, t60):
                errors.append((b, name, r[f"{name}_{b}"], iso_tol(name, b, fs, t60)))
    assert not errors, errors


@pytest.mark.parametrize("fs", [44100, 48000])
@pytest.mark.parametrize("t60", [0.5, 2.0])
def test_decay_times_match_independent_reference(fs, t60):
    """Same band signals, independent numpy Schroeder + ISO fit: must agree to 0.5 %."""
    s = exp_decay_ir(fs=fs, t60=t60, seed=21)           # noise-free: plain Schroeder is exact
    r = run(s.x, fs)
    prep = prepare(s.x, fs, CFG)
    centres, yb = octave_bands(prep.x[0], fs, CFG)
    for c, y in zip(centres, yb):
        if c < 250:
            continue
        for kind in ("T30", "T20", "EDT"):
            assert r[f"{kind.lower()}_{int(c)}"] == pytest.approx(ref.decay_time(y, fs, kind), rel=0.005), (c, kind)
        er = ref.energy_ratios(y, fs)
        assert r[f"c80_{int(c)}"] == pytest.approx(er["c80"], abs=0.05)
        assert r[f"d50_{int(c)}"] == pytest.approx(er["d50"], abs=0.005)
        assert r[f"ts_{int(c)}"] == pytest.approx(er["ts"], abs=0.002)


def test_energy_ratios_and_drr():
    fs = 48000
    for amp, seed in [(0.0, 2), (1.0, 3), (3.0, 4)]:
        s = exp_decay_ir(fs=fs, t60=1.0, direct_amp=amp, seed=seed)
        r = run(s.x, fs)
        # truth on the same band-limited ("broadband") signal the analyzer uses
        bb = broadband(s.clean, fs, CFG)
        tr = truth_energy(bb, fs)
        assert abs(r["c50_bb"] - tr["c50"]) < 0.1
        assert abs(r["c80_bb"] - tr["c80"]) < 0.1
        assert abs(r["d50_bb"] - tr["d50"]) < 0.01
        assert abs(r["ts_bb"] - tr["ts"]) < 0.002
        if amp > 0:
            assert abs(r["drr_bb"] - truth_drr(bb, fs)) < 0.2
            assert abs(r["drr_bb"] - truth_drr(s.clean, fs)) < 1.5   # full-band truth, loosely


@pytest.mark.parametrize("t60", [0.5, 1.0, 2.0])
def test_sti_closed_form(t60):
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=t60, duration=max(2.0, 1.5 * t60), seed=5)
    r = run(s.x, fs)
    assert r["valid_sti"]
    assert abs(r["sti"] - truth_sti(t60)) < 0.02


def test_noise_switches_validity_off():
    fs = 48000
    low = run(exp_decay_ir(fs=fs, t60=1.0, pnr_db=40.0, seed=6).x, fs)
    assert not low["valid_t30_1000"]
    assert not low["valid_t30_bb"]
    high = run(exp_decay_ir(fs=fs, t60=1.0, pnr_db=90.0, seed=6).x, fs)
    assert high["valid_t30_1000"] and rel(high["t30_1000"], 1.0) < 0.05


@pytest.mark.parametrize("pnr", [50.0, 60.0, 70.0, 80.0])
def test_valid_values_stay_accurate_under_noise(pnr):
    """Wherever a value is reported valid, noise must not have biased it."""
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=1.5, pnr_db=pnr, seed=7)
    clean = run(s.clean, fs)                 # same realisation without noise
    r = run(s.x, fs)
    for b in (250, 500, 1000, 2000, 4000, "bb"):
        for name in ("t30", "t20", "edt"):
            if r[f"valid_{name}_{b}"]:
                assert rel(r[f"{name}_{b}"], clean[f"{name}_{b}"]) < 0.05, (pnr, b, name)


def test_zero_padding_invariance():
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=1.0, pnr_db=70.0, seed=8)
    a = run(s.x, fs)
    b = run(np.concatenate([s.x, np.zeros(2 * fs)]), fs)
    for k in ("t30_1000", "t20_500", "edt_bb", "c80_bb", "d50_1000", "sti", "drr_bb"):
        assert a[k] == pytest.approx(b[k], rel=1e-9, nan_ok=True), k
    assert b["trailing_zeros_s"] == pytest.approx(2.0, abs=1e-3)


def test_gain_polarity_predelay_invariance():
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=1.2, direct_amp=1.0, pnr_db=75.0, seed=9)
    ref = run(s.x, fs)
    for x in (0.01 * s.x, -s.x):
        r = run(x, fs)
        for k in ("t30_1000", "c80_bb", "drr_bb"):
            assert r[k] == pytest.approx(ref[k], rel=1e-6, abs=1e-6), k
    d = exp_decay_ir(fs=fs, t60=1.2, direct_amp=1.0, pnr_db=75.0, pre_delay_s=0.1, seed=9)
    r = run(d.x, fs)
    assert rel(r["t30_1000"], ref["t30_1000"]) < 0.02
    assert abs(r["c80_bb"] - ref["c80_bb"]) < 0.3
    assert r["onset_s"] == pytest.approx(0.1, abs=1e-3)


def test_no_noise_floor_uses_plain_schroeder():
    fs = 48000
    r = run(exp_decay_ir(fs=fs, t60=0.8, seed=10).x, fs)
    assert r["edc_mode_bb"] == "schroeder_nofloor"
    assert r["flag_no_noise_floor"]


def test_iacc():
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=1.0, direct_amp=1.0, seed=11)
    other = exp_decay_ir(fs=fs, t60=1.0, direct_amp=0.0, seed=12)
    same = run(np.vstack([s.x, s.x]), fs, roles=("L", "R"), capture_format="binaural")
    assert same["iacc_e3"] == pytest.approx(1.0, abs=1e-6)
    indep = run(np.vstack([other.x, exp_decay_ir(fs=fs, t60=1.0, seed=13).x]), fs,
                roles=("L", "R"), capture_format="binaural")
    assert indep["iacc_l3"] < 0.2
    shift = int(0.0005 * fs)
    delayed = run(np.vstack([s.x, np.concatenate([np.zeros(shift), s.x[:-shift]])]), fs,
                  roles=("L", "R"), capture_format="binaural")
    assert delayed["iacc_e3"] > 0.95
    assert delayed["flag_mic_not_omni"]


@pytest.mark.parametrize("fuma", [True, False])
def test_jlf_plane_waves(fuma):
    fs, n = 48000, 48000
    g = 0.5                               # lateral reflection at 20 ms from 90 deg azimuth
    s = np.zeros(n)
    s[0] = 1.0
    lat = np.zeros(n)
    lat[int(0.02 * fs)] = g
    w_gain = 1 / np.sqrt(2) if fuma else 1.0
    W = w_gain * (s + lat)
    X = s                                  # frontal direct sound
    Y = lat                                # sin(90 deg) = 1
    Z = np.zeros(n)
    tail = exp_decay_ir(fs=fs, t60=0.5, duration=1.0, seed=14).clean[:n] * 1e-3   # tiny diffuse tail
    r = run(np.vstack([W + w_gain * tail, X, Y, Z]), fs, roles=("W", "X", "Y", "Z"),
            capture_format="foa_fuma" if fuma else "foa_ambix")
    expected = g ** 2 / (1 + g ** 2)
    for b in (250, 500, 1000):
        assert r[f"jlf_{b}"] == pytest.approx(expected, abs=0.03), b


@pytest.mark.parametrize("fs", [16000, 44100, 48000, 96000])
def test_octave_filters_meet_iec_61260_class1(fs):
    centres = np.array(CFG.bands.octave_centres_hz, dtype=float)
    centres = centres[centres * 2 ** 0.5 <= CFG.bands.max_upper_edge_fraction_of_nyquist * fs / 2]
    rng = (centres[0] / 2 ** 0.25, centres[-1] * 2 ** 0.25)
    filt = pf.dsp.filter.fractional_octave_bands(None, 1, sampling_rate=fs, frequency_range=rng,
                                                 order=CFG.bands.filter_order)
    assert pf.dsp.filter.check_fractional_octave_band_filter_tolerance(filt, 1, rng, tolerance_class=1)


def test_air_absorption_ceiling_is_plausible():
    c = air_absorption_ceiling([125, 1000, 4000, 8000], CFG)
    assert np.all(np.diff(c) < 0)          # air absorbs more at high frequencies
    assert 1.0 < c[-1] < 30.0              # 8 kHz ceiling of a few seconds
    assert c[0] > 50.0


def test_features_have_fixed_shapes():
    fs = 44100
    a = analyze_ir(exp_decay_ir(fs=fs, t60=1.0, pnr_db=70.0, seed=15).x, fs, cfg=CFG, want_features=True)
    f = a.features
    assert f["edc_lin_db"].shape == (9, 4000)
    assert f["edc_log_db"].shape == (9, 256)
    assert f["mel_db"].shape == (64, 400)
    assert f["ned"].shape == (1000,)
    assert f["mtf"].shape == (7, 14)
    assert a.scalars["grade"] in "AB"


REAL_FIXTURE = "/gpfs/scratch/eey119/FDN2FDN/learn-fdn-iir/IR_subset_final"


@pytest.mark.slow
def test_real_fixture_theatre41():
    import os

    import soundfile as sf

    path = os.path.join(REAL_FIXTURE, "03_theatre_theatre41.wav")
    if not os.path.exists(path):
        pytest.skip("FDN2FDN fixture not available")
    x, fs = sf.read(path, always_2d=True)
    r = run(x.T[:1], fs)
    # naive Schroeder "T60" of this file is 6.2 s; its T30 is ~0.73 s
    assert r["valid_t30_bb"]
    assert rel(r["t30_bb"], 0.73) < 0.08
    assert not r["flag_implausible_hf_decay"]


def _with_floor(clean, fs, pnr_db, shape, seed):
    """Append 2 s of tail and add a non-ideal noise floor of the given shape."""
    rng = np.random.default_rng(seed)
    x = np.concatenate([clean, np.zeros(2 * fs)])
    t = np.arange(x.size) / fs
    sigma = np.sqrt(np.max(clean ** 2) / 10 ** (pnr_db / 10))
    if shape == "modulated":        # +-4 dB slow level fluctuation (environmental noise)
        env = 10 ** (4 * np.sin(2 * np.pi * 0.7 * t) / 20)
    elif shape == "drifting":       # floor falls 8 dB over the file (processed measurements)
        env = 10 ** (-8 * t / t[-1] / 20)
    else:                           # "rising": end-of-file artefact 10 dB above the floor
        env = np.ones_like(t)
        env[-int(0.1 * x.size):] = 10 ** (10 / 20)
    return x + rng.standard_normal(x.size) * sigma * env


@pytest.mark.parametrize("shape", ["modulated", "drifting", "rising"])
def test_real_world_noise_floors_use_lundeby(shape):
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=0.6, duration=1.0, seed=30)
    clean = run(s.clean, fs)
    r = run(_with_floor(s.clean, fs, 75.0, shape, seed=31), fs)
    for b in (250, 500, 1000, 2000, "bb"):
        assert r[f"edc_mode_{b}"] == "lundeby", (shape, b, r[f"edc_mode_{b}"])
        for name in ("t30", "t20"):
            if r[f"valid_{name}_{b}"]:
                assert rel(r[f"{name}_{b}"], clean[f"{name}_{b}"]) < 0.05, (shape, b, name)
    assert r["valid_t20_1000"]


def test_truncated_decay_uses_plain_schroeder():
    """An IR cut before reaching any floor (e.g. C4DM: 2 s files, T = 2.4 s) is still decaying."""
    fs = 48000
    s = exp_decay_ir(fs=fs, t60=2.4, duration=2.0, seed=32)
    r = run(s.x, fs)
    assert r["edc_mode_1000"] == "schroeder_nofloor"
    assert r["valid_edt_1000"]
