---
title: "Findings about the public datasets (data-quality audit)"
date: 2026-09-30
status: active
---

# What consolidating the public RIR datasets revealed

Problems in the upstream data, their evidence, and how the pipeline handles
them. Methods decisions are in [analyzer-v1.md](analyzer-v1.md).

## Upstream data problems

| Dataset | Finding | Evidence | Handling |
|---|---|---|---|
| Rochester | Room 13: the three `Speak2` files are byte-identical copies of the `Speak1` files | identical sha1 of decoded samples; identical CLAP embeddings | `corpus_dedup` view marks them (`dup_of`); registry note |
| DRR-scaled BRIRs (Zenodo 61072) | Archive truncated upstream: 369 MB present, zip directory references ~1.4 GB | md5 matches the record, yet `unzip`, `7z` and Python `zipfile` all fail | `status: broken`; report to the authors |
| MIRD (Bar-Ilan) | Web firewall answers every URL containing parentheses with an HTML "Request Rejected" page and HTTP 200 | same directory serves files without parentheses | `access: manual`; fetch layer now rejects HTML in place of data |
| GTU-RIR | SharePoint link refuses scripted downloads (HTTP 403) | | `access: manual` |
| MIT IR Survey | 270 IRs in `Audio.zip`; the paper and README state 271 | index count | registry expected = 270 |
| Aachen AIR 1.4 | 214 single-ear `.mat` files = 107 L/R records; the README's "344 binaural RIRs" does not match this release | index | registry expected = 107 |
| ACE (single mic) | Published RIRs are truncated/windowed to 0.5-1 s (tails fall faster than the early decay) | per-band decay rates | plain-Schroeder path (`edc_mode = schroeder_nofloor`) |
| C4DM | Files are 2 s long for a ~2.4 s hall: decays end before the noise floor; the three zips share file names | index; extraction | per-archive extraction folders; broadband T30 invalid (grade B) by design |
| OpenAIR | Mixes measured IRs with auralizations, computer models, a virtual reconstruction, a scale model, a slinky, sweeps and music examples; many positions in several formats | folder names | IR-folder whitelist, `ir_kind` curation (`registry/rooms/openair.csv`), `preferred` format per space |
| OpenSLR 28 | Its AIR copies are 16 kHz duplicates of Aachen AIR; RWCP includes anechoic-chamber IRs | names | AIR copies skipped; RWCP `ane` tagged `anechoic` |
| BUT ReverbDB | "RIR-only" archive also holds 60 s silence recordings; room metadata (type, volume, materials) in `env_meta.txt` | probe | adapter picks `RIR/*.v00.wav`; metadata ingested into `rooms` |
| Surrey BRIRs | Includes an anechoic reference set alongside rooms A-D | file names | tagged `anechoic` |
| MYRiAD | v1 (Zenodo 7322755) is one 31 GB zip (RIRs + hours of recordings) that Info-ZIP rejects as a "zip bomb" (false positive on large ZIP64); v2 (7389996) adds a 200 MB "econ" zip with exactly the 1,214 RIRs + coordinates | md5 OK, unzip heuristic; econ listing | pinned to v2 econ; zip-bomb heuristic disabled for checksum-verified archives |
| Aalto robot coupled rooms | Zenodo 10708306 was superseded by 13987509 (2024-10-24): all four data archives changed | Zenodo versions API; md5 differ | pinned to 13987509 |
| SRIRACHA | The 20 published HDF5 files hold 1,327,360 IRs (16 files x 1,024 sources x 64 mics + 4 dense-grid files x 1,089 x 64), half the 2,654,720 stated; IRs are 1 s at 32 kHz | index of all 20 checksum-verified files | expected count noted; T20 valid, T30 mostly not (1 s files) |
| 3D meshgrid | IRs are 4,800 samples (0.1 s): EDT only | HDF5 probe | grade C by design |
| MeshRIR | "4,410 RIRs" counts measurement points; with the 32-source subset there are 18,081 source-receiver IRs | npy shapes | indexed 18,081 |
| RSoANU | 22 GB em32 zip written without proper ZIP64 records (offsets wrap at 4 GiB): Info-ZIP and 7-Zip fail on a checksum-verified file | unzip, 7z; zip -FF recovers all 810 files | extract.sh repairs with zip -FF automatically; 6 B-format IRs in the authors' `Outlier/` folders are not indexed |
| MIRACLE | IRs are 1,024 samples at 32 kHz (32 ms): direct sound + first reflections in a low-reverberation lab | HDF5 probe | indexed (856,128, exact) as `anechoic`; decay metrics not meaningful |

## Licence findings

| Dataset | Finding | Handling |
|---|---|---|
| EchoThief | `EchoThief License.pdf` inside the archive: artistic derivative use only; "not authorized for training AI" | `training_use: prohibited`, `redistribute_audio: no` |
| Voxengo | Redistribution only complete, unaltered, free of charge, with notice | `redistribute_audio: unaltered_only` |
| MYRiAD, trajectoRIR, MIRACLE, C4DM, DRR-scaled | CC BY-NC(-SA): non-commercial research only | `training_use: allowed` (non-commercial) |
| TAU-SRIR | Zenodo licence "other-nc" | `redistribute_audio: unaltered_only` |
| C4DM | Licence version (3.0 vs 4.0) unverified | noted in registry |

`training_use` is carried into the index, so a training-set query can require
`training_use = 'allowed'`.
