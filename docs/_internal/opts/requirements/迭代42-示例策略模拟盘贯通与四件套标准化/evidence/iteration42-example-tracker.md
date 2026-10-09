# 迭代42 示例 tracker（自动生成）

生成时间（UTC）：`2026-10-09T21:43:08.304677+00:00`

| 示例 | dry | replay | live | tier | trigger | env_scope | commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 012_1_midfreq_cross_exchange | PASS | PASS | BLOCKED | self_check_only | none | OKX+Binance demo (dual-venue) | `7cfad68bc` | demo round trip blocked by the expired qualification window (zero-code flip) |
| 012_2_event_driven_cross_exchange | PASS | PASS | BLOCKED | self_check_only | none | OKX+Binance demo (dual-venue) | `90cf8914a` | structural block: HFT admission (event_path_models) is out of iteration scope |
| 013_1_midfreq_cross_arbitrage | PASS | PASS | PENDING_SESSION | pending | drill | SimNow standard fronts (m/RM legs) | `adb1fb7a9` | per-leg registered-sim arm switching; defect fixes per plan §4; interpreter guard; drill awaiting session |
| 013_2_highfreq_calendar_arbitrage | PASS | PASS | PENDING_SESSION | pending | drill | SimNow standard fronts (rb calendar legs) | `adb1fb7a9` | same-exchange calendar spread; HFT status stays FAIL/NOT_ADMITTED; drill awaiting session |
| 013_3_sa_midfreq_simnow | PASS | PASS | FAIL | lifecycle_only | drill | SimNow standard fronts (1-8 MD/TD pairs) | `adb1fb7a9` | first Store/Broker registered-sim arming; interpreter guard + dev-SDK preload; drill awaiting session |
| 014_1_ctp_options_lowfreq | PASS | PASS | PENDING_SESSION | pending | drill | SimNow options (SA C/P/F, real mapping) | `adb1fb7a9` | strict feed-sealed live adapter integrated (R6): run-scoped ClockMapping, sealed BarEvidence, three-leg arm switching, drill; awaiting session |
| 014_2_ctp_options_midfreq | PASS | PASS | PENDING_SESSION | observation | observation | SimNow options (SA C/P/F, real mapping) | `adb1fb7a9` | decision-only observation tier (zero write); real chain reached sealed bars, 7x24 event clock stale (~47.9h) -> BLOCKED live_event_clock_outside_run_mapping; awaiting session window |
| 015_ctp_options_highfreq | PASS | PASS | PASS | observation | observation | SimNow options tick (FG C/P/F, real mapping) | `c13177459` | tick-arrival observation PASS (real ticks per leg, zero write); cohort admission stays FAIL/NOT_ADMITTED (no ctp.quote.v2 attestation on the direct lane); HFT latency conclusion excluded |

live 详情（若已跑）见各示例 `evidence/live-*/run.json`（SHA-256 记录在 JSON tracker）。
