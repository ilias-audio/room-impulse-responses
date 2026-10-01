# Corpus overview

Generated 2026-10-01 10:44 UTC by `rirdb report overview` (analyzer 1.0.0). The interactive version with all charts and the CLAP map is `index.html` in this folder.

## Subsets

| subset | SQL predicate over `corpus_dedup` | IRs | rooms | datasets |
|---|---|---|---|---|
| All analysed IRs | `TRUE` | 254,174 | 647 | 44 |
| Measured | `measured` | 254,021 | 494 | 42 |
| Measured room IRs | `measured AND ir_kind = 'room'` | 200,281 | 399 | 40 |
| Clean measured rooms | `measured AND ir_kind = 'room' AND preferred AND dup_of IS NULL AND NOT coalesce(flag_sweep_like OR flag_tonal OR flag_not_decaying OR flag_dropout, false)` | 197,474 | 387 | 40 |

## T30 per octave band, clean measured rooms (median per room; p5 / p25 / p50 / p75 / p95, s)

| band | rooms | p5 | p25 | p50 | p75 | p95 | valid share (per IR) |
|---|---|---|---|---|---|---|---|
| 63 | 266 | 0.52 | 0.61 | 0.88 | 1.68 | 3.92 | 12 % |
| 125 | 341 | 0.30 | 0.40 | 0.66 | 1.16 | 2.63 | 27 % |
| 250 | 367 | 0.19 | 0.43 | 0.64 | 1.08 | 2.48 | 38 % |
| 500 | 366 | 0.19 | 0.37 | 0.57 | 1.06 | 2.70 | 32 % |
| 1000 | 365 | 0.19 | 0.37 | 0.59 | 1.05 | 2.61 | 36 % |
| 2000 | 370 | 0.18 | 0.37 | 0.56 | 1.00 | 2.42 | 52 % |
| 4000 | 373 | 0.14 | 0.34 | 0.53 | 0.85 | 1.91 | 72 % |
| 8000 | 349 | 0.07 | 0.26 | 0.40 | 0.63 | 1.13 | 70 % |
| bb | 363 | 0.21 | 0.40 | 0.62 | 1.07 | 2.43 | 38 % |

## Signal integrity (all analysed IRs)

- Audited: 200,686 IRs.
- Pre-delay before the direct sound in the files: 16.4 % over 10 ms, 2.3 % over 100 ms. The analysis crops every IR at its ISO 3382-1 onset (20 dB below the peak); the source files are not modified.
- Broadband noise floor found (Lundeby): 100,276; decaying to the end of the file (no floor): 95,822; failed: 3,974.

- `flag_sweep_like`: 139 IRs (rsoanu 90, aalto_multiroom 21, detmold_srir 11, sriracha 6, arni 5, mit_survey 2, meshrir 2, openair 1, em32_line_arni 1)
- `flag_tonal`: 456 IRs (c4dm 187, dechorate 70, but_reverb 45, flair 34, tau_srir 27, mit_survey 24, rochester 14, aalto_multiroom 12, openair 11, tuil_robot_coupled 8, huddersfield_360_brir 5, openslr28 5, motus 5, mckenzie_rtd 4, echothief 2, aachen_air 1, ok5 1, upv_rir_db 1)
- `flag_not_decaying`: 4 IRs (detmold_srir 3, voxengo 1)
- `flag_dropout`: 180 IRs (rsoanu 174, ace_arrays 4, openair 2)
- `flag_nonstationary_noise`: 1,245 IRs (tuil_robot_coupled 368, brudex 238, motus 91, openair 80, mckenzie_rtd 67, but_reverb 57, arni 51, detmold_srir 36, soundcam 30, em32_line_arni 28, aalto_multiroom 27, trajectorir 26, rsoanu 25, mp_rir 24, c4dm 23, ok5 15, rochester 13, aachen_air 8, mit_survey 8, meshrir 6, churchir 5, bras 4, arni_6dof_srir 3, ace 3, iosr_listening_room_brirs 3, ace_arrays 2, myriad 2, raves 1, huddersfield_360_brir 1)
- `flag_quantized_tail`: 766 IRs (rsoanu 726, openair 16, ace_arrays 11, ace 9, echothief 4)

## CLAP map

25,812 IRs (preferred, de-duplicated, at most 1200 per dataset, every room kept), UMAP of the CLAP `ir` and `reverb_vector` embeddings; 10 nearest neighbours by cosine distance in the full 512-d space. Open `index.html`.

