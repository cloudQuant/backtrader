# Iteration 41 monitor read service R3

**Scope:** `LOCAL_COMPONENT_ONLY`. This packet records the read-only monitor service slice in the existing `bt_api_monitor` development checkout. It does not establish TH01/account acceptance or any certification `PASS`.

## Source baseline and whitelist

- Repository: `D:\bt_api_py\bt_api\bt_api_monitor`
- Branch: `dev`
- Base commit: `cdb714b65f811442dfcea0dd0ecb38bda9d9a8d6`
- Package version: `0.1.0`
- Monitor source root: `D:\bt_api_py\bt_api\bt_api_monitor\src`
- Explicit sibling dependency source root: `D:\bt_api_py\bt_api\bt_api_base\src`

| File | Bytes | SHA-256 |
|---|---:|---|
| `src/bt_api_monitor/__init__.py` | 5,970 | `f0b816c83f92d0e01ccc92f8f9e20ba67acde7ccb439289c4148ea581574617a` |
| `src/bt_api_monitor/durable.py` | 25,889 | `fec232682272bd1295a12821222a7d687ee59ca9a2c216b080f7eb67b3706f0e` |
| `src/bt_api_monitor/readonly_events.py` | 27,217 | `91e2dd7c9f19b2b09b4b22247506e800135e513448f9aca11a73fb0ed5363631` |
| `tests/test_readonly_events.py` | 26,508 | `e3ed4e4bbf7e28b5d1fc21c4f0267c7b06785b273e2c5366b4269119b3e4ce8a` |

This review round is limited to these four package files. No file is staged or committed, and the Backtrader parent gitlink is unchanged.

## Read-only service behavior

`DurableOutbox(read_only=True)` opens only an existing regular database, skips directory/schema creation, uses SQLite URI `mode=ro`, verifies `query_only`, and rejects append/ack/consumer-write paths. `ReadOnlyEventService` accepts only that read-only outbox instance and returns authenticated, bounded pages with fixed scope/type, replay, nonce, cursor, and row validation.

A review found that querying configured event types one at a time could skip a lower sequence inserted between the queries after the cursor advanced on a later type. `read_page_types` now selects all configured types in one SQLite statement using bound parameters and global sequence order. The regression inserts alert sequence 1 and decision sequence 2 in the former inter-query window, asserts the service makes one typed read and returns both rows, then verifies the page after cursor 2 is empty.

One shared bounded field-name policy is used at durable append and page validation. It rejects case, camel-case, underscore, hyphen, and nested secret-bearing field names such as `apiKey`; `order_key` and `orderKeyRef` remain valid metadata.

The spawned-process contract test seeds only a synthetic event in temporary SQLite storage, checks exact package/source origins and source hashes, authenticates a read request and page, acknowledges close, joins the child with exit code 0, and confirms event and checkpoint rows are unchanged. No account data or provider is used.

## QA

Run from `D:\bt_api_py\bt_api\bt_api_monitor` in PowerShell with the sibling source root explicit:

```powershell
$env:PYTHONPATH='D:\bt_api_py\bt_api\bt_api_base\src'
python -m pytest -q tests/test_readonly_events.py --tb=short
```

Focused read-service result: **21 passed**, exit 0. Pytest emitted one existing configuration warning for unknown `asyncio_default_fixture_loop_scope`.

The full package source suite also passed: **135 passed**, exit 0. It emitted the same existing asyncio configuration warning and five `psutil` Windows `disk_usage` deprecation warnings.

Additional checks passed:

```powershell
ruff check src/bt_api_monitor/durable.py src/bt_api_monitor/readonly_events.py tests/test_readonly_events.py
python -m py_compile src/bt_api_monitor/durable.py src/bt_api_monitor/readonly_events.py tests/test_readonly_events.py
git diff --check
```

Independent review returned **GO_SOURCE_FAKE_ONLY / LOCAL_COMPONENT_ONLY** on the exact four source pins. The reviewer independently reran the isolated focus (21 passed, one existing asyncio configuration warning) and checked the multi-type page, secret-key policy, negative HMAC, immutable page data, unchanged checkpoints, and spawned child close/join/exit 0.

Root's isolated local-component gate also passed **21/21**, exit 0, with no warnings in 1.65 seconds on these exact pins. It used explicit monitor and base source roots, disabled plugin autoload, removed `PYTHONPATH`, and disabled project conftest. The spawned local service flow ran; all four import-origin checks passed and source bytes were unchanged before and after. Public observation: `E/iteration41-bt-api-monitor-readonly-events-r3-root-local-gate-2026-10-08/observation.json`, SHA-256 `5e908664f209b7b3aa747e7f78a602545ac120d44ed95be4a94905f8d08201fc`.

This acceptance remains a local component result. It does not prove an independently produced TH01 monitoring event or provider/account state, and formal certification case count remains zero.
