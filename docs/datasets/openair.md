# OpenAIR

`openair` · measured · 2010 · wave 1 · status **planned**

Ambisonic B-format (and mono/stereo) RIRs recorded in over 46 (still increasing) environments, with per-space data tables. Includes a few non-room entries (scale model, slinky, simulated auralizations) tagged by ir_kind.

## Provenance and terms

- Source: wget_mirror https://webfiles.york.ac.uk/OPENAIR/IRs/
- Homepage: https://www.openairlib.net/
- Paper: [OpenAIR: An interactive auralization web resource and database](https://www.aes.org/e-lib/browse.cfm?elib=15648)
- Licence: CC-BY-4.0 (https://www.openairlib.net/)
- Audio redistribution: **unknown** · ML training use: **allowed**
- Licence note: Per-IR terms vary; confirm from the per-space tables before serving audio.

## Contents

- IRs analysed: **690** (reported by the authors: 690; IR folders only; sweeps, auralizations and examples skipped)
- Rooms/spaces: 58 · sample rates: 44100, 48000, 96000, 192000 Hz
- Capture: array_raw, foa_fuma, hoa_sh, mono_omni, stereo; analysed channel(s): SL+SR, W, ch0, omni, sur_C
- Grades: A 595, B 39, C 56, D 0
- Analysis errors: 0

## Parameters (10th / 50th / 90th percentile, valid values)

| parameter | p10 | p50 | p90 | n |
|---|---|---|---|---|
| T30 mid (s) | 0.58 | 1.57 | 7.95 | 648 |
| EDT mid (s) | 0.20 | 1.33 | 4.40 | 672 |
| C80 mid (dB) | -3.2 | 3.2 | 18.8 | 671 |
| D50 mid | 0.20 | 0.56 | 0.95 | 671 |
| Ts mid (s) | 0.019 | 0.079 | 0.224 | 671 |
| DRR (dB) | -12.8 | -3.5 | 5.6 | 690 |
| STI | 0.48 | 0.63 | 0.88 | 690 |
| Bass ratio | 0.60 | 1.08 | 1.47 | 625 |
| Treble ratio | 0.55 | 0.81 | 1.04 | 655 |
| Mixing time (ms) | 12 | 33 | 82 | 690 |
| JLF | 0.06 | 0.32 | 0.68 | 353 |

## Quality flags (% of IRs)

| flag | % |
|---|---|
| orientation unknown | 51 |
| pre onset energy | 48 |
| curved decay | 40 |
| nonlinear decay | 28 |
| no noise floor | 10 |
| lundeby failed any | 9 |
| tail truncated | 2 |
| implausible hf decay | 1 |

## Rooms (58; first 60)

| room_key | room_label | category | ir_kind | volume_m3 | n_irs |
|---|---|---|---|---|---|
| 1st-baptist-nashville | 1st baptist nashville | worship | room |  | 3 |
| air-museum | air museum | public_interior | room |  | 8 |
| alcuin-college-university-york | alcuin college university york | unknown | room |  | 25 |
| arthur-sykes-rymer-auditorium-university-york | arthur sykes rymer auditorium university york | theatre_auditorium | room |  | 6 |
| central-hall-university-york | central hall university york | theatre_auditorium | room |  | 6 |
| cliffords-tower | Clifford's Tower (roofless keep) | large_structure | room |  | 4 |
| creswell-crags | creswell crags | underground | room |  | 13 |
| dixon-studio-theatre-university-york | dixon studio theatre university york | theatre_auditorium | room |  | 5 |
| elveden-hall-suffolk-england | elveden hall suffolk england | large_structure | room |  | 4 |
| falkland-palace-bottle-dungeon | falkland palace bottle dungeon | underground | room |  | 1 |
| falkland-palace-royal-tennis-court | falkland palace royal tennis court | sports_leisure | room |  | 4 |
| forest-scale-model | Forest (scale model) | scale_model | scale_model |  | 8 |
| genesis-6-studio-live-room-drum-set | genesis 6 studio live room drum set | studio_booth | room |  | 8 |
| gill-heads-mine | gill heads mine | underground | room |  | 8 |
| hamilton-mausoleum | hamilton mausoleum | large_structure | room |  | 3 |
| hendrix-hall | hendrix hall | public_interior | room |  | 16 |
| heslington-church-vaa-group-2 | heslington church vaa group 2 | worship | room |  | 7 |
| hoffmann-lime-kiln-langcliffeuk | hoffmann lime kiln langcliffeuk | industrial | room |  | 6 |
| holy-trinity-church | holy trinity church | worship | room |  | 24 |
| innocent-railway-tunnel | innocent railway tunnel | tunnel_underpass | room |  | 28 |
| jack-lyons-concert-hall-university-york | jack lyons concert hall university york | concert_hall | room |  | 4 |
| koli-national-park-summer | Koli National Park (summer) | outdoor | outdoor |  | 16 |
| koli-national-park-winter | Koli National Park (winter) | outdoor | outdoor |  | 16 |
| lady-chapel-st-albans-cathedral | lady chapel st albans cathedral | worship | room |  | 11 |
| live-room-physics-and-electronic-engineering-buildings | Live Room (Physics and Electronic Engineering Buildings) | studio_booth | room |  | 8 |
| maes-howe | maes howe | underground | room |  | 2 |
| newgrange | newgrange | underground | room |  | 14 |
| pl001 | PL001 | unknown | room |  | 16 |
| r1-nuclear-reactor-hall | r1 nuclear reactor hall | industrial | room |  | 8 |
| ron-cooke-hub-university-york | ron cooke hub university york | public_interior | room |  | 10 |
| saint-lawrence-church-molenbeek-wersbeek-belgium | saint lawrence church molenbeek wersbeek belgium | worship | room |  | 1 |
| shrine-and-parish-church-all-saints-north-street | shrine and parish church all saints north street _ | outdoor | outdoor |  | 12 |
| slinky-ir | Slinky spring | device | device |  | 1 |
| spokane-womans-club | spokane womans club | public_interior | room |  | 1 |
| sports-centre-university-york | sports centre university york | sports_leisure | room |  | 5 |
| spring-lane-building-university-york | spring lane building university york | device | device |  | 20 |
| st-andrews-church | st andrews church | worship | room |  | 2 |
| st-georges-episcopal-church | st georges episcopal church | worship | room |  | 3 |
| st-margarets-church-national-centre-early-music | st margarets church national centre early music | worship | room |  | 78 |
| st-margarets-church-ncem-5-piece-band-spatial-measurements | st margarets church ncem 5 piece band spatial measurements | worship | room |  | 40 |
| st-marys-abbey-reconstruction | St Mary's Abbey (virtual reconstruction) | virtual | virtual |  | 7 |
| st-matthews-church-walsall | st matthews church walsall | worship | room |  | 6 |
| st-patricks-church-patrington | st patricks church patrington | worship | room |  | 6 |
| st-patricks-church-patrington-model | St Patrick's Church Patrington (model) | virtual | virtual |  | 3 |
| st-pauls-cathedral | st pauls cathedral | worship | room |  | 72 |
| stairway-university-york | stairway university york | stairwell | room |  | 1 |
| terrys-factory-warehouse | terrys factory warehouse | domestic | room |  | 4 |
| terrys-typing-room | terrys typing room | office_meeting | room |  | 4 |
| theatre41 | Theatre41 | theatre_auditorium | room |  | 18 |
| trollers-gill | Trollers Gill (limestone gorge) | outdoor | outdoor |  | 12 |
| tvisongur-sound-sculpture-iceland-model | Tvisongur sound sculpture (Iceland) | large_structure | room |  | 40 |
| tyndall-bruce-monument | Tyndall Bruce Monument | outdoor | outdoor |  | 4 |
| usina-del-arte-symphony-hall | usina del arte symphony hall | concert_hall | room |  | 22 |
| virtual-membranes | Virtual membranes | virtual | virtual |  | 3 |
| waveguide-web-example-audio | Waveguide web (example) | virtual | virtual |  | 7 |
| wheldrake-wood | Wheldrake Wood | outdoor | outdoor |  | 12 |
| york-guildhall-council-chamber | york guildhall council chamber | office_meeting | room |  | 12 |
| york-minster | york minster | worship | room |  | 2 |

_Generated by `rirdb report cards`; methods: docs/decisions/analyzer-v1.md._
