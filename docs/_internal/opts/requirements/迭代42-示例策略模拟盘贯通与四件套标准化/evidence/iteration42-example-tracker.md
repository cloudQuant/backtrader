# 迭代42 示例 tracker（自动生成）

生成时间（UTC）：`2026-10-09T20:08:59.512548+00:00`

| 示例 | dry | replay | live | tier | trigger | env_scope | commit | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 012_1_midfreq_cross_exchange | PASS | PASS | BLOCKED | self_check_only | none | OKX+Binance demo (dual-venue) | `7cfad68bc` | demo round trip blocked by the expired qualification window (zero-code flip) |
| 012_2_event_driven_cross_exchange | PASS | PASS | BLOCKED | self_check_only | none | OKX+Binance demo (dual-venue) | `90cf8914a` | structural block: HFT admission (event_path_models) is out of iteration scope |
| 013_1_midfreq_cross_arbitrage | PASS | PASS | PENDING_SESSION | pending | drill | SimNow standard fronts (m/RM legs) | `0150641a3` | per-leg registered-sim arm switching; defect fixes per plan §4 |
| 013_2_highfreq_calendar_arbitrage | PASS | PASS | PENDING_SESSION | pending | drill | SimNow standard fronts (rb calendar legs) | `e91e3638b` | same-exchange calendar spread; HFT status stays FAIL/NOT_ADMITTED |
| 013_3_sa_midfreq_simnow | PASS | PASS | FAIL | lifecycle_only | drill | SimNow standard fronts (1-8 MD/TD pairs) | `eb3da84f3` | first-ever Store/Broker registered-sim arming recorded; drill awaiting session |
| 014_1_ctp_options_lowfreq | PASS | PASS | BLOCKED | self_check_only | none | SimNow options (SA C/P/F) - adapter not integrated | `e7dc0e4a6` | strict feed-sealed evidence adapter round required (plan R6-R8 scope revision) |
| 014_2_ctp_options_midfreq | PASS | PASS | BLOCKED | self_check_only | none | SimNow options (F_LOCAL fixture) - adapter not integrated | `e7dc0e4a6` | needs real contract mapping plus the strict evidence adapter round |
| 015_ctp_options_highfreq | PASS | PASS | BLOCKED | self_check_only | none | SimNow options tick (cohort fixture) - adapter not integrated | `e7dc0e4a6` | HFT latency conclusion excluded (FAIL/NOT_ADMITTED) |

live 详情（若已跑）见各示例 `evidence/live-*/run.json`（SHA-256 记录在 JSON tracker）。
