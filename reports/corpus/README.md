# Corpus report

Generated 2026-09-30 16:04 UTC by `rirdb report corpus` from `metrics/v1` (analyzer 1.0.0, config 4a9f28a351a9744c).

**4,392 IRs** analysed from **12 datasets**, **573 rooms/spaces**; 4,128 are room IRs (the rest: outdoor, scale models, anechoic, devices). Grades: A 2,295, B 1,639, C 454, D 4 (A: T30 valid 125 Hz-4 kHz; B: T20/T30 valid 250 Hz-2 kHz; C: partial; D: none).

Single numbers follow ISO 3382-1 (mean of 500 Hz and 1 kHz; only where both are valid). Figures use one preferred representation per measured position (e.g. OpenAIR B-format over its mono copy) and room IRs only.

## Per dataset (medians unless noted)

| dataset | IRs | rooms | A/B/C/D | T30 mid (p10-p50-p90) | EDT mid | C80 mid | D50 mid | DRR | STI | BR / TR | t_mix ms | errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aachen_air | 107 | 12 | 99/8/0/0 | 0.33 / 1.03 / 2.62 | 0.51 | 10.0 | 0.79 | 3.4 | 0.81 | 1.00 / 0.88 | 40 | 0 |
| ace | 14 | 7 | 14/0/0/0 | 0.40 / 0.48 / 1.40 | 0.41 | 12.0 | 0.84 | 1.5 | 0.81 | 1.30 / 1.01 | 39 | 0 |
| but_reverb | 1674 | 9 | 834/517/323/0 | 0.46 / 0.71 / 1.13 | 0.92 | 4.4 | 0.54 | -9.1 |  | 1.05 / 0.93 | 20 | 0 |
| c4dm | 468 | 3 | 0/468/0/0 | 1.95 / 2.42 / 3.14 | 2.36 | 0.2 | 0.40 | -2.1 | 0.53 |  / 0.86 | 26 | 0 |
| detmold_srir | 657 | 3 | 224/416/17/0 | 1.57 / 1.61 / 1.64 | 1.50 | 1.2 | 0.43 | -5.4 | 0.58 | 1.10 / 0.86 | 39 | 0 |
| echothief | 115 | 115 | 93/22/0/0 | 0.43 / 1.09 / 2.40 | 0.73 | 7.5 | 0.73 | -4.2 | 0.75 | 1.18 / 0.87 | 34 | 0 |
| mit_survey | 270 | 270 | 180/84/6/0 | 0.07 / 0.38 / 1.01 | 0.11 | 20.1 | 0.97 | 8.5 | 0.96 | 1.10 / 0.83 | 24 | 0 |
| ok5 | 70 | 25 | 69/0/1/0 | 0.35 / 0.49 / 1.53 | 0.41 | 11.3 | 0.83 | 1.5 | 0.81 | 1.61 / 1.01 | 32 | 0 |
| openair | 690 | 58 | 595/39/56/0 | 0.58 / 1.57 / 7.95 | 1.33 | 3.2 | 0.56 | -3.5 | 0.63 | 1.08 / 0.81 | 33 | 0 |
| openslr28 | 199 | 19 | 73/78/48/0 | 0.06 / 0.44 / 0.75 | 0.36 | 11.4 | 0.81 | 3.0 |  | 1.22 / 0.81 | 30 | 0 |
| rochester | 90 | 14 | 82/7/1/0 | 0.17 / 0.45 / 1.88 | 0.41 | 10.4 | 0.83 | -5.6 | 0.81 | 1.47 / 0.98 | 14 | 0 |
| voxengo | 38 | 38 | 32/0/2/4 | 0.59 / 1.05 / 4.07 | 1.03 | 2.6 | 0.44 | -9.3 | 0.62 | 1.03 / 0.86 | 54 | 0 |

## Quality-flag rates (% of IRs; flags seen in >= 1 % of some dataset)

| dataset | clipped | dc offset | short | low fs | pre onset energy | tail truncated | lundeby failed any | no noise floor | low pnr | implausible hf decay | curved decay | nonlinear decay | filter bias risk | edc method disagreement | mic not omni | orientation unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aachen_air | 0 | 0 | 4 | 0 | 4 | 19 | 3 | 12 | 0 | 0 | 80 | 27 | 1 | 0 | 63 | <NA> |
| ace | 0 | 0 | 0 | 0 | 0 | 21 | 0 | 43 | 0 | 0 | 57 | 36 | 0 | 0 | 0 | <NA> |
| but_reverb | 0 | 0 | 0 | 100 | 0 | 1 | 1 | 42 | 8 | 0 | 14 | 12 | 1 | 2 | 0 | <NA> |
| c4dm | 0 | 0 | 0 | 0 | 0 | 0 | 46 | 16 | 0 | 0 | 0 | 11 | 0 | 0 | 0 | <NA> |
| detmold_srir | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 57 | 0 | 0 | 2 | 1 | 0 | 3 | 44 | <NA> |
| echothief | 0 | 0 | 3 | 0 | 2 | 25 | 4 | 75 | 0 | 10 | 53 | 47 | 2 | 1 | 0 | <NA> |
| mit_survey | 0 | 0 | 28 | 0 | 1 | 24 | 3 | 9 | 0 | 0 | 63 | 59 | 1 | 1 | 0 | <NA> |
| ok5 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 66 | 53 | 0 | 0 | 0 | <NA> |
| openair | 1 | 0 | 0 | 0 | 48 | 2 | 9 | 10 | 0 | 1 | 40 | 28 | 0 | 1 | 0 | 51 |
| openslr28 | 1 | 8 | 21 | 100 | 0 | 0 | 28 | 14 | 0 | 0 | 24 | 24 | 4 | 0 | 0 | <NA> |
| rochester | 0 | 0 | 0 | 0 | 16 | 2 | 1 | 13 | 0 | 0 | 34 | 41 | 2 | 0 | 0 | <NA> |
| voxengo | 5 | 3 | 13 | 0 | 0 | 0 | 8 | 50 | 5 | 3 | 5 | 5 | 0 | 0 | 0 | <NA> |

## Figures

![T30 vs C80](t30_c80.png)

![Coverage T30 x DRR](coverage_t30_drr.png)

![Decay frequency shape](t30_bands.png)

Methods and validity rules: [docs/decisions/analyzer-v1.md](../../docs/decisions/analyzer-v1.md).
