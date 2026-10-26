# 50-A → 51 固定交接清单

2026-10-27：Root 将下列既有接受证据与本目录 baseline.json/profile.json 绑定。AC50-01、AC51-01a/01b按 SOURCE 基线及交接范围通过；50-A 已交接，不代表真实行情或账户通过。

## Required 50-A members and accepted evidence

| Member | Existing accepted evidence (path / commit) | Boundary |
|---|---|---|
| 01 | `tests/integration/test_live_factor_r0_preflight.py`; `.codex-tmp/iteration50_r0_preflight_20261024.xml`; `27a2512d`; profile gate `.codex-tmp/r0_profile_gate_postfix_20261025.xml`; new R2 output above | SOURCE baseline accepted; exact profile, software, hardware and evidence are fixed in baseline.json. |
| 02 | `tests/unit/research/test_live_factor_binding.py`; `tests/unit/research/test_factor_strategy_clock_rejection.py` (`09e3cc843`); `tests/integration/test_alpha003_registered_sim_order_chain.py` (`a4d594e4`) | Ordinary Strategy/FactorSpec and local Broker/Store route. |
| 03 | `factor_indicator.py` / strict-input tests, commits `d4b8937e`, `1425e340`; 100-case focus | History/tick/direct-bar validation and scoped callback errors. |
| 04a | `tests/unit/research/test_live_factor_binding.py` (Alpha003 `open`/`volume`, membership vs present, unknown-field reject) | Alpha003 base-field contract only; 04b is outside 50-A. |
| 05 | `.codex-tmp/iteration50_snapshot_diagnostics_20261024.xml`; `80071eddc` import-boundary focus | Snapshot/readiness/diagnostic boundedness and import boundary. |
| 06 | 67-case composition (`58f0938d8`); `tests/integration/test_iteration50_handoff_contract_gaps.py::test_later_fresh_execution_quote_does_not_rewrite_the_sealed_prior_bar` | Atomic publication and sealed-bar immutability. |
| 07a | `tests/integration/test_ac50_07a_raw_cold_start_alpha003.py` (SHA `8FBFD14C…6B370A`) | Raw-tick cold start; no buy before minperiod/LIVE_READY. |
| 07b | `tests/integration/test_live_alpha003_history_catchup_execution.py` (SHA `A4D0B6BA…477805`); `52283c711` | Native/build history overlap, common cutover/catch-up; first OPEN only after LIVE_READY. |
| 08 | `.codex-tmp/iteration50_atomic_wake_final_composition_20261024.xml`; `b64fc5804204929dcf773d61662a37127257ed6b` | 1/2/6/20-member arrival order, delayed last leg, complete-batch wake. |
| 09a | `tests/integration/test_live_factor_invalid_source_rebuild.py`; `66920f4ff` | Missing/invalid source freezes and rebuilds same planned grid. |
| 09b (Alpha003) | `be21b8899`, `bb43f287d`; Alpha003 gap/WARMUP zero-target and Broker invalid-price regressions | Alpha003 profile only; 09b full-101 is 50-B. |
| 10 | `tests/integration/test_live_factor_cohort_bounded_reorder.py` (`41478317914d48f280cd65368601406229f94529`); journal test (`7b4fefb268e57f0f36ad89a5bdddcf7420812ecd`); rebuild test (`66920f4ff`) | Bounded reorder, deduplication, stale generation, high-water and gap rebuild. |
| 11 | Feed/Cerebro revision-notification focus, `a87a1d338` | Declared generation/disconnect/rules/calendar/overflow events; no implicit upstream discovery claim. |
| 12 | `tests/integration/test_live_cohort_prepare_budget.py` (`06bc77bd`); `test_live_factor_cohort_pending_wait.py` (`ac31ca500d609c0f81239dcdb8b29ce8a0bc28f3`); lost-wakeup regression `bf5d5b5942435e46b6844751897d368959be5683` | Bounded prepare/wait and Broker/idle opportunity; synthetic API leaves. |
| 13 | `backtrader/brokers/factor_replay.py`, `tests/unit/test_factor_replay_broker.py` (`73501a850c5de6f9db40652d3beef823062c0559`); sealed-quote regression | available_at causal fills; later execution quotes do not rewrite bars. |
| 14 | Core/feed 727 + strategy 1,286 regressions; `evidence/core-feed-strategies-20261024/acceptance.md`; `7f58ca31f` | Existing non-cohort compatibility and engine regressions. |
| 15a | Alpha003 matrix `65c83a4e`; future/order perturbation `7d7425226` | Native/build × runonce/runnext/stream, 320/640/1280, per-node oracle. |
| 16a | `tests/integration/test_alpha003_live_buffer_notifications.py`; `.codex-tmp/alpha003_live_buffer_notifications_20261025.xml` and `_rerun_20261025.xml`; commits `637cfedf`, `df9ac9f2c` | Alpha003 QBuffer and early-LIVE-notification cases; preserve split-pass history (native long case plus affected rerun), not a single all-green final run. |
| 17a / 18a | `evidence/alpha003-stream-20261024/acceptance.md` | Alpha003 future perturbation/oracle plus 400-history/240-live suffix rebuild. |
| 19 | Six-asset Alpha003 decision focus, `0daad91f24ef3f40e68f7df685ec7151eba91553`; test SHA `85189A52…F7CC6D13` | Fixed facts/target and causal replay; local source/composition. |
| 20 | `tests/integration/test_alpha003_registered_sim_order_chain.py` (`a4d594e4f572858e0f748d3b88b31ed449d27691`); cross-route `0e25f3385`; `.codex-tmp/ac50_20_alpha003_registered_sim_order_chain_r12_20261025.xml` | Actual framework OPEN/CLOSE/CANCEL notifications and receipts with fake provider leaves. |
| 21 | `tests/integration/test_factor_execution_unknown_recovery.py` (`513d57b673ccc1654e3d3b050d25598af5dbbd83`); `test_ac50_21_registered_sim_cancel_unknown_reconcile.py` (`b4dec75da148d536d2fd970f6f83aab953b2b4a4`) | Same-ID submit/cancel UNKNOWN reconciliation; local synthetic provider. |
| 22 | `tests/integration/test_ac50_22_registered_sim_cancel_dispatching_reconcile.py`; final no-fill and partial-close two-process focus in `提交记录-20261024.md` (2026-10-25 AC50-22 entry) | Durable CANCEL recovery and later authorized risk close; do not collapse earlier failed fixture runs into a single final run. |
| 23 | `tests/integration/test_registered_sim_factor_risk_rejections.py`; `82c1b662d` | Broker risk limits/fill races; the risk-only Alpha003 case uses a manual target and is not factor-computation evidence. |
| 24 | `tests/integration/test_live_alpha003_history_catchup_execution.py`; `tests/integration/test_live_factor_missing_gap_execution_rebuild.py`; `tests/unit/test_registered_sim_store.py`; warmup risk tests in `tests/unit/test_alpha003_simnow_strategy.py` | No warmup/gap/stale/foreign-owner OPEN, writes hard-rejected; authorized owned-order risk cancel remains available. |
| 25 | Journal/Book budget `fc82ea957`; DecisionTape overflow `d5ae1fcf2`; Broker/Store cleanup `a4d594e4f`, recovery cleanup `17c642e4a` | Bounded logical capacity and fail-closed; physical SQLite/WAL/RSS belongs to 27. |
| 26a | `evidence/installed-20261025/manifest.json`; source `a025256e`; wheel `b662f16f…e395b63` | Installed public fixture/RECORD/origin and ordinary Strategy + fake-component chain. |
| 27a | `evidence/ac50-27-combined-20261027/adjudication.json`; raw `formal-27a-native-r3-20261025/result.json` / `formal-27a-build-r6-20261025/result.json` | 20 assets, 100k grids, Alpha003 native/build, oracle/data/RSS/close-readback; latency waiver only, raw FAIL records unchanged. |


基线01对应本目录 baseline.json 和 evidence.zip；旧8项安装检查属于 c4c7240a，新增3项属于 bc80fb2a，分开记录，不称最终wheel重跑了11项。全池87品种是2026-10-27盘前发现快照；实际启动须同一Store重新发现并核验本次代次/交易日/完整覆盖，不能直接重用旧session身份。纯耗时豁免沿用用户要求，数据正确性/有界内存/完整资源清理仍保留。
