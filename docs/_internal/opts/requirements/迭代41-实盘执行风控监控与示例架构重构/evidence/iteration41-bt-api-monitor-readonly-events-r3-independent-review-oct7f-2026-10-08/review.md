# bt_api_monitor read-only event service R3 independent review

**Decision:** `GO_SOURCE_FAKE_ONLY / LOCAL_COMPONENT_ONLY`.

## Bound public material

Repository `D:\bt_api_py\bt_api\bt_api_monitor`, branch `dev`, base `cdb714b65f811442dfcea0dd0ecb38bda9d9a8d6`.

| File | Bytes | SHA-256 |
|---|---:|---|
| `src/bt_api_monitor/__init__.py` | 5,970 | `f0b816c83f92d0e01ccc92f8f9e20ba67acde7ccb439289c4148ea581574617a` |
| `src/bt_api_monitor/durable.py` | 25,889 | `fec232682272bd1295a12821222a7d687ee59ca9a2c216b080f7eb67b3706f0e` |
| `src/bt_api_monitor/readonly_events.py` | 27,217 | `91e2dd7c9f19b2b09b4b22247506e800135e513448f9aca11a73fb0ed5363631` |
| `tests/test_readonly_events.py` | 26,508 | `e3ed4e4bbf7e28b5d1fc21c4f0267c7b06785b273e2c5366b4269119b3e4ce8a` |

Author packet README: `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-bt-api-monitor-readonly-events-r3-local-component-2026-10-08\README.md`, 3,863 bytes, SHA-256 `ca535baa12fca2c6be2701c93cad86cdbd54217997e92e2d20d277d8bc326f56`.

## Review and QA

A predecessor using one independent SQLite read per event type was held: an append between type reads could expose sequence 2 while missing sequence 1, then advance the cursor past the unseen row. This R3 uses one parameterized `IN` query for the bounded event-type set, ordered by global sequence. The service validates that single page before advancing its cursor. The regression inserts alert sequence 1 and decision sequence 2 in the old inter-read window, asserts one typed read returns both rows, and verifies the page after cursor 2 is empty.

Read-only construction requires an existing regular file, skips schema and directory initialization, opens SQLite with `mode=ro`, verifies `query_only`, and blocks append, acknowledgement, and consumer writes. The service requires this read-only outbox. Durable writes and page validation share normalized secret-key checks; tests reject `apiKey` variants and preserve `order_key`/`orderKeyRef` metadata.

Independent scoped QA used `D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe -I -S -B -X utf8`, with explicit `Lib\site-packages`, `D:\bt_api_py\bt_api\bt_api_base\src`, and `D:\bt_api_py\bt_api\bt_api_monitor\src` paths, `PYTHONPATH` empty, and pytest autoload disabled. Pytest ran only `tests/test_readonly_events.py` with `-p no:asyncio -p no:cacheprovider`, fresh basetemp `D:\bt_api_py\bt_api\bt_api_monitor\.pytest_cache\l04-readonly-events-20261008-r2`. Import origins resolved to the pinned monitor checkout (`__init__.py`, `durable.py`, and `readonly_events.py`). Result: **21 passed**, one existing warning for unknown `asyncio_default_fixture_loop_scope`.

Additional fake-only probes rejected wrong request and page HMAC keys, rejected nested mutation of returned event data, and confirmed event rows and consumer checkpoints remained unchanged. The spawned-child test verifies the authenticated page and close acknowledgement, joins the child with exit code 0, and compares event/checkpoint rows before and after.

This review is local component evidence only. It makes no account, provider, TH01, or certification `PASS` claim. The broad package suite was not independently rerun.
