# Iteration 10 SCN02 014_2 synthetic ServiceHost integration

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`.

This round verifies the existing `014_2` normal `run_live` entry through the explicitly selected read-only service backend, SDK market/account clients, Store/Feed, the unchanged strategy, and Cerebro. It supplements the source round committed at `2a108caa8f28e72695adc66de4245f609539ed58`. The test uses local `ServiceHost`/CURVE endpoints and synthetic CTP Trader/MD leaves; it does not connect to a real account or venue.

## Accepted local result

The exact focused node passed once on CPython 3.11.5 with the restored package source roots and the CTP dependency at `da4f7badc36ca4a8b7b1020048fb0b3598021f32`:

```text
C:/anaconda3/python.exe -m pytest -p no:asyncio -q tests/integration/test_0142_service_backend_ctp_host.py::test_0142_run_live_service_reaches_three_leg_cerebro_through_gateway_hosts
1 passed, 1 warning in 6.28s
```

The warning is the existing `asyncio_default_fixture_loop_scope` pytest configuration warning. The test records the expected `BLOCKED / ctp_source_clock_mapping_unqualified` and `NOT_QUALIFIED` result, zero order writes, all three C/P/F tick legs, matching authenticated market source identity, closed account and market deployments, one account provider close, zero remaining market handles, all three native instruments accounted for across subscribe/unsubscribe, and one typed native stream stop/wait. The first run reached shutdown but failed a fixture assertion because successfully unsubscribed symbols had been removed from the fixture's active list. The assertion was corrected to compare the union of active and unsubscribed symbols; the following run passed. No extra audit assertions added after that pass are included in this test.

The result demonstrates the local service-backed normal consumer path and shutdown using synthetic provider leaves. It does not demonstrate real CTP provider/account behavior, clock calibration, source freshness, exchange event-time mapping, or write eligibility. Source descriptor identity and a common clock-domain label do not establish qualified same-clock timing. There is no formal SCN02 case-count increase in this round.

## Exact test pin

| Path | Bytes | SHA-256 |
|---|---:|---|
| `tests/integration/test_0142_service_backend_ctp_host.py` | 41,175 | `37f85989b3cfde53b2baa8cf579e0a4f189a67f07bdfddfecbc3eacc265c1dd4` |

The test is the sole integration source payload in this commit. The six production/test paths from the source round remain in their accepted parent commit; unrelated Backtrader and SDK working-tree changes are excluded.

## SCN02 coverage still outstanding

The formal plan requires all nine unified directories to have their read/write capability dispositions recorded and their affected normal SDK/Backtrader entries validated, while preserving approvals, research gates and same-clock conditions. This node covers only `014_2`'s local read-only CTP consumer path.

| Directory | Remaining SCN02 disposition/evidence |
|---|---|
| `007_ctp` | Historical/offline boundary remains; no registered live entry is being restored by this round. |
| `012_1_midfreq_cross_exchange` | Cross-venue, two-account execution and recovery path is outside this read-only CTP node. |
| `012_2_event_driven_cross_exchange` | Event-window/IOC execution, timing admission and recovery remain outside this node. |
| `013_1_midfreq_cross_arbitrage` | Same-account multi-contract group, minute bars plus ticks, and strategy attribution require their own normal-entry evidence. |
| `013_2_highfreq_calendar_arbitrage` | Same-account calendar group, contract/expiry identity, timing and group execution evidence remain separate; the name does not qualify HFT. |
| `013_3_sa_midfreq_simnow` | The single-contract CTP read path and its separately admitted write drill are not covered here. |
| `014_1_ctp_options_lowfreq` | Its three-leg closed-bar and separately authorized write-drill path remains separate. |
| `014_2_ctp_options_midfreq` | Local synthetic service path is verified; real provider/account evidence and qualified run-owned clock mapping/freshness remain absent, so the normal result stays blocked and zero-write. |
| `015_ctp_options_highfreq` | Tick-only cohort, freshness/latency and qualified same-clock evidence remain absent; no HFT eligibility is inferred. |

The exact formal acceptance gate is `SCN02` in `docs/迭代计划/迭代10-可选组件与可配置通信/正式迭代计划.md`; its nine-directory inventory is in `场景覆盖与旧转发迁移清单.md`. This record reports the narrow local result and does not replace the formal tracker or claim full SCN02 completion.
