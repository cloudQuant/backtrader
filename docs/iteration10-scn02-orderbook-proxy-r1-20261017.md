# Iteration 10 SCN02 typed orderbook proxy source round

- Repository/branch: `D:/source_code/backtrader`, `dev`.
- Source base: `7cda685945e74369f4df8077e77deab7b57f517b` (shared observation helper commit).
- Scope: `backtrader/events.py` recovery-snapshot field; selected orderbook-only additions in `backtrader/stores/service_read_proxy.py`; focused orderbook tests; orderbook-only integration fixture/Host path and cleanup-leaf tests. No shared observation helper changes.
- Static review: `review_bt_store_feed` returned GO_STATIC on the exact four-path snapshot. Review also found and bounded one remaining test-fixture edge: `process.start()` failure still uses sequential closes, so a close error could mask the start error. This round does not claim that branch is hardened.
- Fresh direct failure-leaf QA: `C:/anaconda3/python.exe -m pytest -q -p no:asyncio tests/test_service_read_proxy_integration.py::test_start_process_closes_both_pipes_when_process_construction_fails tests/test_service_read_proxy_integration.py::test_publisher_cleanup_records_a_bounded_join_timeout` returned exit 0, 2 passed, 1 existing pytest configuration warning. Result: `.codex-tmp/scn02-orderbook-proxy-cleanup-nodes-r2-20261017/result.json` (2,880 bytes, SHA-256 `C52A8BCBF42BBFBC615F4E594847D0D1DA693F54A17A2781BB39F799CE4B33D6`). The two nodes create no Host and make no network/account calls. All four selected source pins matched before/after.
- The first direct invocation stopped before collection completed because the installed `pytest_asyncio` collection hook expected `Package.obj` (exit 2, zero candidate tests). It is preserved at `.codex-tmp/scn02-orderbook-proxy-cleanup-nodes-r1-20261017/result.json` (3,481 bytes, SHA-256 `53E1630C46AD7F90FF609405595FE68EDF5C73E6CC223848929C835FC11D2A94`). The rerun disables this irrelevant async plugin because both nodes are synchronous; the existing unknown-config warning remains visible.
- Earlier messages reported 9 focused orderbook unit cases, 52 legacy checks, and a local synthetic ServiceHost/SDK/Store/Feed/Cerebro orderbook integration as passed. No original stdout/JUnit/result path was found, so these remain message-level historical reports rather than archived raw QA. The Host report is associated with the pre-cleanup integration test pin (56,493 bytes, SHA-256 `8660A127358473C314D34B3451D2BF280A1A04DF8753E881F59158967FAE3AF9`); no Host rerun is claimed for this round's updated test bytes.

## Final source pins

| Path | Bytes | SHA-256 |
|---|---:|---|
| `backtrader/events.py` | 33,799 | `AAF503F5EF9670F8CFB474F516812188E676740A93B7A5ECCD9A4E70BDB0BE76` |
| `backtrader/stores/service_read_proxy.py` | 67,682 | `809F01EB3CCF5E653247E255145170A6AB4B4360E0B060CC6BDD461DF18DDB41` |
| `tests/test_service_read_proxy_integration.py` | 58,601 | `7EE8A328958070AC4D05797B766521AD79091BC8C5A9E1B431A7700D155FDFDB` |
| `tests/test_service_read_proxy_orderbook.py` | 12,530 | `804BA28E3E0704DCBEC52AA24D8D62E419393F50A22FE0546BC489D7490B60B5` |

`max_event_age_seconds` is only an uncalibrated local age-screening heuristic comparing local UTC to `WireHeader.sent_at_utc` (which forwards provider-observed time). The source descriptor does not certify clock calibration or freshness. `stale=False` therefore does not establish trusted freshness or execution eligibility. The synthetic Host path is local integration evidence only; no live venue or real account was contacted. The earlier Host run had no preserved raw output, and this round makes no clean-checkout QA claim.

The selected patch applied cleanly against the recorded base and no files were staged while preparing this record. The commit hash is the Git commit containing this record and is reported with the round delivery.
