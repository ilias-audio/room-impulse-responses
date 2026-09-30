"""Analyse one impulse response record: one flat row of scalars + fixed-shape features.

Multichannel policy (docs/decisions/analyzer-v1.md):
  - binaural (roles L, R): every metric on each ear, single numbers are the
    mean of the ears; IACC from the pair; features from the left ear.
  - stereo pairs (roles SL, SR; production libraries): same averaging, no IACC.
  - first-order Ambisonics (roles W, X, Y, Z): metrics on W; JLF from W + Y.
  - anything else: the first channel passed in is the analysed reference.
All channels are cropped at one common onset (the earliest), preserving ITD.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from rirdb.analysis import ANALYZER_VERSION
from rirdb.analysis import decay as dmod
from rirdb.analysis import energy, features, perceptual, quality, spatial, spectral, temporal
from rirdb.analysis.config import Config, load_config
from rirdb.analysis.preprocess import broadband, octave_bands, prepare

NON_OMNI_FORMATS = {"binaural", "em32_raw", "sma_raw", "tetra_raw"}


@dataclass
class IRAnalysis:
    scalars: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)


def _band_key(label) -> str:
    return "bb" if label == "bb" else str(int(label))


def _mid(d: dict, key: str) -> float:
    a, b = d.get(f"{key}_500", np.nan), d.get(f"{key}_1000", np.nan)
    va, vb = d.get(f"valid_{key}_500", False), d.get(f"valid_{key}_1000", False)
    return float((a + b) / 2) if (va and vb) else float("nan")


def _analyze_channel(x: np.ndarray, fs: int, cfg: Config, want_features: bool) -> tuple[dict, dict]:
    s: dict = {}
    f: dict = {}
    centres, yb = octave_bands(x, fs, cfg)
    bb = broadband(x, fs, cfg)
    ys = np.vstack([yb, bb[None, :]]) if yb.size else bb[None, :]
    labels = [*centres.tolist(), "bb"]
    n_tail = max(int(round(cfg.preprocess.noise_tail_fraction * ys.shape[1])), 1)
    noise_init = np.mean(ys[:, -n_tail:] ** 2, axis=-1)

    dec = dmod.analyze_decay(ys, fs, labels, noise_init, cfg)
    er = energy.energy_ratios(dec, cfg)
    for i, lab in enumerate(labels):
        k = _band_key(lab)
        for name in ("EDT", "T20", "T30", "LDT"):
            s[f"{name.lower()}_{k}"] = float(dec.values[name][i])
            s[f"valid_{name.lower()}_{k}"] = bool(dec.valid[name][i])
        s[f"tbest_{k}"] = float(dec.extra["t_best"][i])
        s[f"curvature_{k}"] = float(dec.extra["curvature_pct"][i])
        s[f"xi_{k}"] = float(dec.extra["nonlinearity_permille"][i])
        s[f"decay_range_db_{k}"] = float(dec.decay_range_db[i])
        s[f"intersection_s_{k}"] = float(dec.intersection_s[i])
        s[f"edc_mode_{k}"] = dec.mode[i]
        for name in ("C50", "C80", "D50", "Ts"):
            s[f"{name.lower()}_{k}"] = float(er[name][i])
            s[f"valid_{name.lower()}_{k}"] = bool(er["valid"][i])

    # ISO single numbers (mean of 500 Hz and 1 kHz)
    for key in ("t30", "t20", "edt", "c50", "c80", "d50", "ts"):
        s[f"{key}_mid"] = _mid(s, key)
    tb = {int(c): s[f"tbest_{int(c)}"] for c in centres}
    s.update(energy.tonal_balance(tb))

    ib = len(labels) - 1                                    # broadband index
    s["pnr_db"] = float(10 * np.log10(np.max(bb ** 2) / noise_init[ib])) if noise_init[ib] > 0 else float("inf")
    s["t30_bb_chu"] = dmod.chu_t30(bb, fs, float(noise_init[ib]))
    it_bb = dec.intersection_s[ib]
    s.update(energy.drr(x, fs, it_bb, subtract_noise=(dec.mode[ib] == "lundeby"), cfg=cfg))
    duration = x.shape[-1] / fs
    tail_truncated = bool(dec.mode[ib] == "lundeby" and it_bb >= cfg.quality.tail_truncated_fraction * duration)
    st = energy.sti(x, fs, it_bb, tail_ok=(dec.mode[ib] != "failed" and not tail_truncated
                                           and dec.decay_range_db[ib] >= cfg.decay.min_range_db["EDT"]), cfg=cfg)
    s["sti"], s["valid_sti"] = st["sti"], st["valid"]

    tsc, prof = temporal.temporal(bb, fs, cfg)
    s.update(tsc)
    s.update(spectral.band_levels(centres, yb))
    s.update(spectral.centroids(x, fs, end_s=it_bb))

    # --- per-channel quality flags
    fl: dict = {"tail_truncated": tail_truncated}
    fl["lundeby_failed_any"] = any(m == "failed" for m in dec.mode)
    fl["no_noise_floor"] = dec.mode[ib] == "schroeder_nofloor"
    fl["low_pnr"] = bool(s["pnr_db"] < cfg.decay.min_range_db["T20"])
    ceiling = quality.air_absorption_ceiling(centres, cfg) if centres.size else np.zeros(0)
    fl["implausible_hf_decay"] = bool(any(
        np.isfinite(tb[int(c)]) and np.isfinite(cl) and tb[int(c)] > cl for c, cl in zip(centres, ceiling)))
    # ISO 3382-2 Annex B curvature / non-linearity, flagged on the broadband decay
    # (single-IR octave values fluctuate too much at small B*T: ISO 3382-2 Annex A)
    eval_idx = [i for i, lab in enumerate(labels) if lab == "bb"]
    fl["curved_decay"] = bool(np.nanmax(np.abs(dec.extra["curvature_pct"][eval_idx]), initial=0)
                              > cfg.decay.curvature_flag_percent)
    fl["nonlinear_decay"] = bool(np.nanmax(dec.extra["nonlinearity_permille"][eval_idx], initial=0)
                                 > cfg.decay.nonlinearity_flag_permille)
    bias = [c for c in centres if np.isfinite(tb[int(c)]) and 0.7071 * c * tb[int(c)] < cfg.decay.filter_bias_bt]
    fl["filter_bias_risk"] = bool(bias)
    t30bb, chu = s.get("t30_bb", np.nan), s["t30_bb_chu"]
    fl["edc_method_disagreement"] = bool(s.get("valid_t30_bb") and np.isfinite(chu)
                                         and abs(chu - t30bb) / t30bb > cfg.decay.chu_disagreement_flag)
    s.update({f"flag_{k}": v for k, v in fl.items()})

    if want_features:
        lin, logt = features.edc_grids(dec.edc, fs, cfg)
        f["edc_lin_db"] = lin                                   # (9, 4000) bands..., bb
        f["edc_log_db"] = logt                                  # (9, 256)
        f["mel_db"] = features.log_mel(x, fs, cfg)              # (64, 400)
        _, _, edr_db = spectral.edr(x, fs, cfg)
        f["edr_db"] = edr_db.astype(np.float16)
        f["ned"] = features.fix_length(prof["ned"][1], 1000)
        f["edp"] = features.fix_length(prof["edp"][1], 500)
        _, mag = spectral.magnitude_response(x, fs, cfg.features.magnitude_fractions)
        f["magnitude_db"] = mag.astype(np.float32)
        _, t60c = spectral.t60_curve(x, fs)
        f["t60_curve"] = t60c.astype(np.float32)
        f["mtf"] = st["mtf"] if st["mtf"] is not None else np.full((7, 14), np.nan, dtype=np.float32)
        f["band_centres"] = np.asarray(centres, dtype=np.float32)
    return s, f


def analyze_ir(
    x: np.ndarray,
    fs: int,
    roles: tuple[str, ...] = ("omni",),
    capture_format: str = "mono_omni",
    sh_norm: str | None = None,
    orientation_known: bool = True,
    cfg: Config | None = None,
    want_features: bool = True,
) -> IRAnalysis:
    """Analyse one IR record. `x` is (n_ch, n) with `roles` naming each channel."""
    cfg = cfg or load_config()
    x = np.atleast_2d(np.asarray(x, dtype=np.float64))
    roles = tuple(roles) if roles else tuple(f"ch{i}" for i in range(x.shape[0]))
    if len(roles) != x.shape[0]:
        raise ValueError(f"{len(roles)} roles for {x.shape[0]} channels")

    prep = prepare(x, fs, cfg)
    out = IRAnalysis()
    sc = out.scalars
    sc.update({"analyzer_version": ANALYZER_VERSION, "config_sha256": cfg.sha256[:16],
               "capture_format": capture_format, "roles": ",".join(roles)})
    sc.update({k: v for k, v in prep.stats.items()})
    sc.update({f"flag_{k}": v for k, v in prep.flags.items()})
    if prep.flags.get("all_zero") or prep.x.shape[1] < int(0.05 * fs):
        sc["grade"] = "D"
        sc["analysed_role"] = ""
        return out

    binaural = "L" in roles and "R" in roles
    stereo = "SL" in roles and "SR" in roles     # stereo pair (not a head): averaged, no IACC
    if binaural:
        primary = [roles.index("L"), roles.index("R")]
    elif stereo:
        primary = [roles.index("SL"), roles.index("SR")]
    elif "W" in roles:
        primary = [roles.index("W")]
    else:
        primary = [0]
    sc["analysed_role"] = "+".join(roles[i] for i in primary)

    per = []
    for j, i in enumerate(primary):
        s, f = _analyze_channel(prep.x[i], fs, cfg, want_features and j == 0)
        per.append(s)
        if j == 0:
            out.features.update(f)
    if len(per) == 1:
        sc.update(per[0])
    else:   # binaural: average numeric values, AND validity, OR flags
        for k in per[0]:
            vals = [p.get(k) for p in per]
            if k.startswith("valid_"):
                sc[k] = bool(all(vals))
            elif k.startswith("flag_"):
                sc[k] = bool(any(vals))
            elif isinstance(vals[0], str):
                sc[k] = vals[0] if len(set(vals)) == 1 else "|".join(vals)
            else:
                arr = np.asarray(vals, dtype=float)
                sc[k] = float(np.nanmean(arr)) if np.isfinite(arr).any() else float("nan")
        for key in ("t30", "t20", "edt", "c50", "c80", "d50", "ts"):
            sc[f"{key}_mid"] = _mid(sc, key)

    if binaural:
        sc.update(spatial.iacc(prep.x[primary[0]], prep.x[primary[1]], fs, cfg))
    if "W" in roles and "Y" in roles:
        fuma = (sh_norm or "").lower() == "fuma" or capture_format == "foa_fuma"
        sc.update(spatial.jlf(prep.x[roles.index("W")], prep.x[roles.index("Y")], fs, fuma, cfg))
        sc["flag_orientation_unknown"] = not orientation_known

    sc["flag_mic_not_omni"] = capture_format == "binaural"
    sc["flag_omni_proxy"] = capture_format in NON_OMNI_FORMATS - {"binaural"} and "W" not in roles
    vt30 = {int(k.split("_")[-1]): v for k, v in sc.items() if k.startswith("valid_t30_") and k[-1].isdigit()}
    vt20 = {int(k.split("_")[-1]): v for k, v in sc.items() if k.startswith("valid_t20_") and k[-1].isdigit()}
    vedt = any(v for k, v in sc.items() if k.startswith("valid_edt_"))
    sc["grade"] = quality.grade(vt30, vt20, vedt)
    sc["drr_bb"] = sc.get("drr_bb", float("nan"))
    sc["t30_mid_or_t20"] = sc["t30_mid"] if np.isfinite(sc["t30_mid"]) else sc["t20_mid"]
    sc.update(perceptual.jnd_coordinates({**sc, "jlf_low": sc.get("jlf_low", np.nan),
                                          "one_minus_iacc_e3": sc.get("one_minus_iacc_e3", np.nan)}))
    return out
