# Iteration 41 — three-venue 99-case acceptance tracker (r21)

- as_of_utc: `2026-10-09T12:34:58Z`
- commits: backtrader dev `fadcfb8199d4f6192f9f31d38d8b0d5d136758ce`, bt_api_ctp dev `a497bab6bb1b904891461aead1857093078226f0`
- totals: **96 PASS / 3 BLOCKED / 0 FAIL / 0 NOT_RUN** (99 cases)
- optional16: `PRESENT`

Methodology: three-file cases (config.yaml + <ID>_strategy.py + run.py); per-run evidence JSON under cases/<ID>/evidence/ (git-ignored, SHA-256 recorded here); newest PASS preferred, otherwise the newest run; blocked entries carry the reason from the run

## binance — 32 PASS / 1 BLOCKED / 0 NOT_RUN

| case | status | reason | evidence | sha256 |
| --- | --- | --- | --- | --- |
| B01 | PASS |  | `20261009T120720_B01_PASS.json` | `d79006d518b3` |
| B02 | PASS |  | `20261009T115904_B02_PASS.json` | `218f9b5e2b11` |
| C01 | PASS |  | `20261009T123415_C01_PASS.json` | `0ecf6dd5e003` |
| E01 | PASS |  | `20261009T120120_E01_PASS.json` | `31e579f9a798` |
| E02 | PASS |  | `20261009T120126_E02_PASS.json` | `df7b06192767` |
| E03 | PASS |  | `20261009T120132_E03_PASS.json` | `d3b8950bac3b` |
| EM01 | BLOCKED | permission_restriction_not_producible_on_demo_key | `20261009T120721_EM01_BLOCKED.json` | `ca2b4ed2f684` |
| EM02 | PASS |  | `20261009T120139_EM02_PASS.json` | `350de71e7a30` |
| EM03 | PASS |  | `20261009T120143_EM03_PASS.json` | `98e10b66ba1a` |
| L01 | PASS |  | `20261009T120031_L01_PASS.json` | `68ac81ad0d40` |
| L02 | PASS |  | `20261009T115834_L02_PASS.json` | `5cdf1398b31e` |
| L03 | PASS |  | `20261009T115835_L03_PASS.json` | `c868b83527f3` |
| L04 | PASS |  | `20261009T115836_L04_PASS.json` | `81910634fc7e` |
| M01 | PASS |  | `20261009T115842_M01_PASS.json` | `3c4703d4cd2d` |
| M02 | PASS |  | `20261009T115846_M02_PASS.json` | `177d0bdacd71` |
| M03 | PASS |  | `20261009T115843_M03_PASS.json` | `ad6013ff250b` |
| M04 | PASS |  | `20261009T115910_M04_PASS.json` | `f29323b96353` |
| M05 | PASS |  | `20261009T115917_M05_PASS.json` | `e8c9aaf0c63a` |
| O01 | PASS |  | `20261009T115927_O01_PASS.json` | `0a5dfdad6585` |
| O02 | PASS |  | `20261009T120114_O02_PASS.json` | `363abe547c29` |
| O03 | PASS | repeat_cancel_rejected | `20261009T115936_O03_PASS.json` | `38b14e91fa57` |
| T01 | PASS |  | `20261009T112511_T01_PASS.json` | `d88ed3d95673` |
| T02 | PASS |  | `20261009T120023_T02_PASS.json` | `c2d1fd93c2c9` |
| T03 | PASS |  | `20261009T123420_T03_PASS.json` | `66891e34cbb0` |
| TH01 | PASS |  | `20261009T115843_TH01_PASS.json` | `8400f3445919` |
| TH02 | PASS |  | `20261009T115950_TH02_PASS.json` | `0c9acf251f19` |
| TH03 | PASS |  | `20261009T115844_TH03_PASS.json` | `3f325f159dba` |
| TH04 | PASS |  | `20261009T120005_TH04_PASS.json` | `65d8022105da` |
| TH05 | PASS |  | `20261009T115844_TH05_PASS.json` | `2a89e3c1b5f2` |
| TH06 | PASS |  | `20261009T120015_TH06_PASS.json` | `6a47d214efad` |
| V01 | PASS |  | `20261009T115837_V01_PASS.json` | `95d71e889a89` |
| V02 | PASS |  | `20261009T115839_V02_PASS.json` | `eae6af751323` |
| V03 | PASS |  | `20261009T115841_V03_PASS.json` | `02b2acc71b9c` |

## okx — 33 PASS / 0 BLOCKED / 0 NOT_RUN

| case | status | reason | evidence | sha256 |
| --- | --- | --- | --- | --- |
| B01 | PASS |  | `20261009T121951_B01_PASS.json` | `c5191b833891` |
| B02 | PASS |  | `20261009T121737_B02_PASS.json` | `42feab083325` |
| C01 | PASS |  | `20261009T120740_C01_PASS.json` | `9919dd123c13` |
| E01 | PASS |  | `20261009T121849_E01_PASS.json` | `200d739f890b` |
| E02 | PASS |  | `20261009T121853_E02_PASS.json` | `6f9037d030de` |
| E03 | PASS |  | `20261009T121856_E03_PASS.json` | `a2ba4fa3dd96` |
| EM01 | PASS |  | `20261009T121901_EM01_PASS.json` | `4ba37b82dcaf` |
| EM02 | PASS |  | `20261009T121905_EM02_PASS.json` | `bd8fa3b1b96d` |
| EM03 | PASS |  | `20261009T121909_EM03_PASS.json` | `f77bc41cdab9` |
| L01 | PASS |  | `20261009T121836_L01_PASS.json` | `4f1f2559536b` |
| L02 | PASS |  | `20261009T120741_L02_PASS.json` | `5d7da9fac670` |
| L03 | PASS |  | `20261009T120742_L03_PASS.json` | `a542e4d24d7f` |
| L04 | PASS |  | `20261009T120743_L04_PASS.json` | `d353bffedc9a` |
| M01 | PASS |  | `20261009T120746_M01_PASS.json` | `556221e84e35` |
| M02 | PASS |  | `20261009T120751_M02_PASS.json` | `796b236123c7` |
| M03 | PASS |  | `20261009T120748_M03_PASS.json` | `a23e831956ce` |
| M04 | PASS |  | `20261009T121741_M04_PASS.json` | `384fc88e40f1` |
| M05 | PASS |  | `20261009T121745_M05_PASS.json` | `0977bb820f98` |
| O01 | PASS |  | `20261009T121752_O01_PASS.json` | `d4ec9285a094` |
| O02 | PASS |  | `20261009T121845_O02_PASS.json` | `8042764c2530` |
| O03 | PASS | repeat_cancel_rejected | `20261009T121758_O03_PASS.json` | `9ed389db8363` |
| T01 | PASS |  | `20261009T112617_T01_PASS.json` | `8557cc82e4b5` |
| T02 | PASS |  | `20261009T121830_T02_PASS.json` | `a5485623fd50` |
| T03 | PASS |  | `20261009T121731_T03_PASS.json` | `c33df03801ae` |
| TH01 | PASS |  | `20261009T120748_TH01_PASS.json` | `bb61795be95c` |
| TH02 | PASS |  | `20261009T121808_TH02_PASS.json` | `b1ad1c2bd9f1` |
| TH03 | PASS |  | `20261009T120749_TH03_PASS.json` | `d959d4380cb2` |
| TH04 | PASS |  | `20261009T121818_TH04_PASS.json` | `84b564284f41` |
| TH05 | PASS |  | `20261009T120750_TH05_PASS.json` | `d32b57b2d43c` |
| TH06 | PASS |  | `20261009T121826_TH06_PASS.json` | `ebb08c56d910` |
| V01 | PASS |  | `20261009T120744_V01_PASS.json` | `bcdd49895d6a` |
| V02 | PASS |  | `20261009T120745_V02_PASS.json` | `d754ceb9268e` |
| V03 | PASS |  | `20261009T120745_V03_PASS.json` | `5cdf5697f441` |

## simnow — 31 PASS / 2 BLOCKED / 0 NOT_RUN

| case | status | reason | evidence | sha256 |
| --- | --- | --- | --- | --- |
| B01 | PASS |  | `20261009T115628_B01_PASS.json` | `ba56c9064e2b` |
| B02 | PASS |  | `20261009T110524_B02_PASS.json` | `4e750a611211` |
| C01 | PASS |  | `20261009T103922_C01_PASS.json` | `b4b7c639b29e` |
| E01 | BLOCKED | insufficient_funds_rejection_not_reachable | `20261009T123336_E01_BLOCKED.json` | `c245b395f2b8` |
| E02 | PASS |  | `20261009T115710_E02_PASS.json` | `31b8a91c1954` |
| E03 | PASS |  | `20261009T114511_E03_PASS.json` | `34db880e826e` |
| EM01 | PASS |  | `20261009T112313_EM01_PASS.json` | `219b3a1655af` |
| EM02 | PASS |  | `20261009T112424_EM02_PASS.json` | `f5f81a6786a0` |
| EM03 | BLOCKED | forced_logout_not_observed | `20261009T111541_EM03_BLOCKED.json` | `117e1f3dd19e` |
| L01 | PASS |  | `20261009T113858_L01_PASS.json` | `d4a1b275c35c` |
| L02 | PASS |  | `20261009T105902_L02_PASS.json` | `b8782bc2d8ca` |
| L03 | PASS |  | `20261009T105933_L03_PASS.json` | `9274c47240f5` |
| L04 | PASS |  | `20261009T110004_L04_PASS.json` | `301f64e8ccfb` |
| M01 | PASS |  | `20261009T110213_M01_PASS.json` | `2bb0d03db403` |
| M02 | PASS |  | `20261009T112219_M02_PASS.json` | `a1248051dbe3` |
| M03 | PASS |  | `20261009T110245_M03_PASS.json` | `95a29c06704e` |
| M04 | PASS |  | `20261009T110624_M04_PASS.json` | `a7f380be09e7` |
| M05 | PASS |  | `20261009T110707_M05_PASS.json` | `ad55109a66b9` |
| O01 | PASS |  | `20261009T110818_O01_PASS.json` | `069d093b49b4` |
| O02 | PASS |  | `20261009T115501_O02_PASS.json` | `aaaa928af198` |
| O03 | PASS |  | `20261009T110926_O03_PASS.json` | `edc622c6ba57` |
| T01 | PASS |  | `20261009T104611_T01_PASS.json` | `8cbf2b8f11e1` |
| T02 | PASS |  | `20261009T113957_T02_PASS.json` | `22954d1f701f` |
| T03 | PASS |  | `20261009T111909_T03_PASS.json` | `a2e9bb7b5bf8` |
| TH01 | PASS |  | `20261009T110314_TH01_PASS.json` | `cc95bf4da289` |
| TH02 | PASS |  | `20261009T112056_TH02_PASS.json` | `3cc001d75cac` |
| TH03 | PASS |  | `20261009T110342_TH03_PASS.json` | `5d2443303287` |
| TH04 | PASS |  | `20261009T111141_TH04_PASS.json` | `13648eb24a50` |
| TH05 | PASS |  | `20261009T110414_TH05_PASS.json` | `67759e99e302` |
| TH06 | PASS |  | `20261009T111252_TH06_PASS.json` | `001161dd8758` |
| V01 | PASS |  | `20261009T110034_V01_PASS.json` | `6a6e92fb71b0` |
| V02 | PASS |  | `20261009T110104_V02_PASS.json` | `51d32cf8d92d` |
| V03 | PASS |  | `20261009T110143_V03_PASS.json` | `ab70068801d7` |

## Blocked cases (evidence-backed)

- binance/EM01: permission_restriction_not_producible_on_demo_key
- simnow/E01: insufficient_funds_rejection_not_reachable
- simnow/EM03: forced_logout_not_observed
