---
title: "Analyzer v1: methods, validity rules and the choices behind them"
date: 2026-09-30
status: active
---

# Analyzer v1

`src/rirdb/analysis/` computes, for every IR record, ISO 3382-1/-2 room-acoustic
parameters, IEC 60268-16 STI, spatial parameters, temporal structure, spectral
descriptors, quality flags and fixed-shape representations. Settings live in
`configs/analyzer_v1.yaml`; its sha256 (first 16 hex) is stored in every row
(`config_sha256`), together with `analyzer_version`, the pyrato/pyfar versions
and the git sha.

## Libraries

| What | Library / function | Standard |
|---|---|---|
| Octave filter bank | `pyfar.dsp.filter.fractional_octave_bands`, order 14 | IEC 61260-1:2014 class 1 (checked in tests at 16/44.1/48/96 kHz) |
| Onset | `pyfar.dsp.find_impulse_response_start(threshold=20)` | ISO 3382-1 A.3.4 |
| Noise / intersection time | `pyrato.edc.intersection_time_lundeby` | Lundeby et al. 1995 |
| EDC | `pyrato.edc.energy_decay_curve_lundeby` (normalised per band) | Schroeder 1965 + truncation correction |
| EDT, T20, T30, LDT | `pyrato.parameters.reverberation_time_linear_regression` | ISO 3382-1/-2 |
| C50, C80, D50, Ts | `pyrato.parameters.clarity / definition / center_time` | ISO 3382-1 |
| STI + MTF | `pyrato.parameters.speech_transmission_index_indirect / modulation_transfer_function` | IEC 60268-16:2020 indirect method |
| JLF | `pyrato.parameters.early_lateral_energy_fraction` | ISO 3382-1 |
| Air absorption | `pyfar.constants.air_attenuation` | ISO 9613-1 |

pyrato 1.1.0, pyfar 0.8.1 (pinned `<1.2`, `<0.9`).

## Decisions

1. **Trim digital silence first, pass noise explicitly.** pyfar's onset and
   pyrato's `'auto'` noise read the last 10 % of the file. Zero-padded files
   make that digital silence (FDN2FDN `rir-measurement-validity-2026-08-19`).
   Leading/trailing samples below 1e-9 are trimmed; the noise level of each
   band is the mean square of the last 10 % of the *trimmed* signal and is
   passed to Lundeby. Test: appending 2 s of zeros changes no metric.
2. **Per-band EDC normalisation.** `reverberation_time_linear_regression`
   assumes an EDC starting at 0 dB. With `channel_independent=False` pyrato
   normalises all bands by the global maximum, which would shift the -5/-35 dB
   points of weaker bands. The analyzer uses `channel_independent=True`.
3. **Validity is enforced by the analyzer, not trusted to pyrato.** pyrato's
   regression uses `nanargmin(|EDC - level|)`, so an EDC that never reaches
   -35 dB silently yields a "T30" from a shorter range. A value is computed only
   if the EDC reaches the lower limit, and flagged valid only if the decay range
   (smoothed peak level minus noise level, same smoothing window as Lundeby:
   800/f + 10 ms, or 30 ms broadband) is at least 20 dB (EDT), 35 dB (T20) or
   45 dB (T30): the bottom of the evaluation range stays >= 10 dB above noise.
4. **IRs without a noise floor.** Production IRs are often faded or truncated
   before any noise floor, which makes Lundeby fail by construction. If the last
   20 % of the band energy is still decaying (> 3 dB over four segments), the
   plain Schroeder integral is used (`edc_mode = schroeder_nofloor`), the decay
   range is measured against the energy at the end of the file, and the fit
   range must end before the last 5 % of the file.
5. **"Broadband"** is the IR band-limited to the octave span (4th-order causal
   Butterworth, 44.5 Hz to min(11.3 kHz, 0.9 fs/2)), so DC offsets and sub-audio
   noise cannot distort Lundeby. Causal, like the octave filters: a zero-phase
   filter smears the direct sound back across the onset crop.
6. **Octave bands are dropped** when their upper -3 dB edge exceeds 0.9 fs/2
   (pyfar would otherwise substitute a high-pass).
7. **Single numbers** (`*_mid`) are the mean of the 500 Hz and 1 kHz octave
   values when both are valid (ISO 3382-1 Table A.1).
8. **DRR** follows the ACE challenge convention (direct window +-2.5 ms around the
   direct peak, searched within 10 ms of the onset), with energies read from
   the noise-compensated broadband EDC.
9. **STI** is room-only: no ambient noise, no auditory masking (the IRs are
   uncalibrated). The IR is truncated at the broadband Lundeby intersection time
   (so measurement noise is not read as reverberation) and zero-padded to
   1.6 s (IEC 60268-16:2020, 6.2). Requires fs > 22.6 kHz (8 kHz octave below
   Nyquist). Test: matches the closed form m(F) = 1/sqrt(1+(2 pi F T/13.8)^2)
   within 0.02.
10. **G and LJ are not computed**: they need calibration or a free-field
    reference that no public dataset provides consistently.
11. **Echo density.** Abel & Huang (2006) NED with a 20 ms Hann window; mixing
    time = first time NED reaches 1 (Lindau et al. 2012 signal-based
    predictor). The kurtosis EDP of FDN2FDN is kept byte-identical for
    continuity with the DAFx26 paper (`t_mix_edp_ms`).
12. **Multichannel.** One row per IR record. Binaural and stereo pairs: every
    metric per channel, averaged (validity = all channels valid); IACC only for
    binaural (ISO 3382-1 Annex B, +-1 ms, E 0-80 ms, L 80 ms-1 s, bands
    500/1k/2k). B-format: metrics on W; JLF from W and Y (FuMa W scaled by
    sqrt 2). Arrays: one reference channel (`analysis.reference_role`).
13. **Quality flags** (`flag_*`). `curved_decay` (|C| > 10 %) and
    `nonlinear_decay` (xi > 10 permille, ISO 3382-2 Annex B) are flagged on the
    broadband decay only. Evidence (wave 0): over all octave bands they fired on
    97 % of the MIT survey, and still on 78 % using 500 Hz/1 kHz: at T = 0.4 s
    the single-IR spread of T30/T20 in the 500 Hz octave is already about +-9 %
    (ISO 3382-2 Annex A), so the threshold measured noise, not curvature.
    Per-band `curvature_*` / `xi_*` stay in the table.
    `pre_onset_energy` fires when the pre-onset power, excluding the 5 ms just
    before the onset, exceeds the tail noise by 20 dB. Evidence: in MIT and
    Rochester the energy in the last 5 ms before the onset is direct-sound
    pre-ringing (benign); some Rochester IRs carry a slowly decaying pre-onset
    tail 30-40 dB above the noise, i.e. circular time aliasing (a real artefact).
    An energy fraction (the first design) grows with pre-delay length and was
    not usable.
    `implausible_hf_decay`: a valid decay time above the air-absorption bound
    T = 55.3 / (4 m c), m minimised over 10-90 % RH and 10-30 degC.
14. **Grade.** A: T30 valid 125 Hz-4 kHz. B: T20 or T30 valid 250 Hz-2 kHz.
    C: something valid. D: nothing (or unreadable).

## Validation (tests/test_analysis_synthetic.py)

- Synthetic exponential decays (fs 16/44.1/48/96 kHz, T 0.3/1/3 s, with and
  without noise): every band within 3 sigma of the single-realisation spread
  of ISO 3382-2 Annex A plus 1 %.
- Same band signals through an independent numpy Schroeder + ISO fit
  (`analysis/reference.py`): T within 0.5 %, C80 0.05 dB, D50 0.005, Ts 2 ms.
- Energy ratios and DRR against the realised band-limited energies
  (C 0.1 dB, D50 0.01, Ts 2 ms, DRR 0.2 dB).
- Noise sweep 40-90 dB PNR: T30 invalid at 40 dB; wherever valid, within 5 %
  of the same realisation without noise.
- Invariance to gain, polarity, pre-delay, zero padding.
- IACC = 1 for identical ears, < 0.2 for independent tails, > 0.95 for a 0.5 ms
  ITD; JLF of a synthetic B-format lateral reflection within 0.03.
- Real fixture: theatre41 from FDN2FDN's subset, broadband T30 = 0.73 s +-8 %
  (a naive Schroeder "T60" of the same file is 6.2 s).

## Known limitations

- Octave filters bias T when B*T < 16 (Rasmussen et al. 1991); flagged
  (`filter_bias_risk`), not corrected (time-reversed filtering is future work).
- Model-based perceptual mixing time (Lindau 2012) needs room volume and
  surface; only the signal-based predictor is reported.
- Raw spherical-array capsules are analysed on one capsule (`omni_proxy`);
  proper SH encoding is future work.
