# Binance TH01 account-window candidate R2

Date: 2026-10-09  
Status: source-fake implementation complete; independent review pending. No live invocation was made by this round.

## Scope and source closure

This round adds a Root-only, bounded Binance USDⓈ-M read candidate and a cold launcher. It collects one current-state observation plus a bounded history window. Its public status is `CANDIDATE_ONLY`; it cannot issue a `StateSnapshot`, `account_full` attestation, or case `PASS`.

The launcher exact-loads the accepted fixed-GET owner source and the candidate source from bounded, hash-pinned bytes. The Root factory takes no owner or transport callback argument; it binds only the current `sys.modules["__main__"]`, requires the exact launcher path, and verifies the owner's fixed source markers and function origins. The candidate then exact-loads only the tracked protected `.env` reader and private artifact helper. It does not import `backtrader_runtime`, execute the old R3 package bootstrap, or require the old 39-file source closure. The reader still uses the unchanged helper's Windows protected `.env` checks and owner-only private directory/writer; neither was exercised against real credentials or Win32 APIs here.

| Role | Repo-relative path | Bytes | SHA-256 |
|---|---|---:|---|
| Accepted fixed GET transport | `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |
| Unchanged protected `.env` reader | `backtrader_runtime/certification_binance_roundtrip_r3_cli.py` | 33,887 | `62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76` |
| Unchanged private artifact helper | `backtrader_runtime/certification_roundtrip_private.py` | 17,537 | `b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd` |
| New account-window candidate | `examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py` | 62,664 | `4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63` |
| New cold launcher | `scripts/iteration41_binance_th01_account_window_candidate_r2.py` | 11,391 | `698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6` |
| Focused source-fake tests | `tests/unit/live_certification/test_binance_th01_account_window_candidate_r2.py` | 30,219 | `d7fad941b1326bd21e37fb5340002c675656e3eb5664ce7b3a93ff43f7751deb` |

The implementation base is Backtrader `dev` at `49a4febb3036f25962b583bb7b315fcb699df021`. The first three source pins above are dependencies only and were not changed by this round. The round is not staged or committed.

## Read contract

The typed reader admits only these fixed signed GET families:

| Resource | Endpoint | Query scope |
|---|---|---|
| `account_configuration` | `/fapi/v1/accountConfig` | No query fields |
| `account_v2` | `/fapi/v2/account` | No query fields |
| `standard_open_orders` | `/fapi/v1/openOrders` | No symbol filter; all open symbols |
| `algo_open_orders` | `/fapi/v1/openAlgoOrders` | No symbol filter; all open symbols |
| `all_orders_in_window` | `/fapi/v1/allOrders` | No symbol filter; bounded `startTime`/`endTime`, recursive millisecond bisection, `limit=1000` |
| `user_trades_in_window` | `/fapi/v1/userTrades` | Candidate symbol; first request uses time bounds, continuations use `fromId` only |
| `income_in_window` | `/fapi/v1/income` | No symbol or income-type filter; bounded window and page number, `limit=1000` |

No order lookup, original ActionRef/CID lookup, allocation mapping, async export, or write route is called. The unresolved original Binance order remains `UNKNOWN`; this round does not resolve or retry it, infer a cancel, allocate an identifier, or associate a new action with it.

The half-open evidence window is `[history_start_ms, phase_cutoff_ms)`, limited to 71 hours; Root input validation also requires a recent cutoff and a window younger than 89 days. The reader caps the invocation at 64 requests, 5,000 rows, 2 MiB per response, 64 MiB total bodies, and 120 seconds. Oversized response bodies are not archived. Source files and every ancestor are shape-checked before reading; path identity and ancestor reparse state are checked again after the bounded read. The helper loader registers a fresh synthetic module before compiling exact verified bytes and removes a failed import without replacing an existing module.

AllOrders time bisection splits a full 1,000-row interval into disjoint integer-millisecond children, pads each request edge by one millisecond, and deduplicates overlaps by `(symbol, orderId)`. Conflicting duplicate facts, a still-full one-millisecond interval, row/query mismatch, or budget exhaustion blocks the candidate. Income and per-candidate-symbol userTrades continue until a short page; userTrades obeys Binance's parameter rule by omitting time bounds from every `fromId` continuation. A continuation row after the requested cutoff blocks. The output labels these as scan/page observations; they are not an account-wide history attestation.

The candidate symbol set is the union of active positions, open standard/algo orders, bounded allOrders rows, and income rows. It then queries userTrades for those symbols. This set does not close the account's trade universe: a fill can occur during the window for an order created before the window, and userTrades requires a symbol. The source does not claim that allOrders creation-time rows or income rows identify every symbol with a fill. `user_trades_universe_closed` remains false, and no caller-supplied list, boolean, UUID, or module-visible token can mint coverage. `account_full_attestation()` is unconditionally fail-closed in this component until a separate provider-bound coverage issuer is reviewed.

Provider watermark/finality remains informational; the candidate sets it false and does not require a watermark to finish collection. This keeps the existing runner contract intact without turning a missing watermark into a new permanent gate.

## Remaining TH01 work

The TH01 case contract in `cases/TH01/TH01_strategy.py` is `READ`, action `inspect_submit_threshold`, event `submit_threshold_observed`, with proof fields `threshold_value` and `config_snapshot_id`; the configured threshold is 5 (`_certification/config.py:274`). The candidate does not read the active strategy's `TradeLogger`, emit that event, or run the independent monitor summary.

The generic runner remains authoritative. `_snapshot()` in `_certification/runner.py:1196-1211` requires each snapshot to bind the same action and phase, use `scope="account_full"`, be complete and pagination-complete, come from an attested remote state channel, and be fresh. `_run_one()` reads `baseline` at lines 1704-1708, `before_cleanup` at 1788-1797, and `after_cleanup` at 1931-1935; `_reconcile_state()` requires three distinct ordered snapshots and reconciles the state at lines 1290 onward. This R2 collector returns one private candidate page set and is not adapted to `StateSnapshot`.

The next evidence path is concrete:

1. Establish a provider-backed, account-wide bounded fill source or a provider-guaranteed symbol universe. Root should first review the source contract and exact request budget; no asynchronous export quota was used here. Keep the R8 seven-route transport result as transport evidence only, not proof of this collector's history scope.
2. Extend the same Root read authorization to retain one invocation and collect fresh `account_full` state for baseline, before-cleanup, and after-cleanup. Reuse the reviewed runner's existing completeness, source, freshness, and reconciliation checks; do not synthesize flags or timestamps.
3. In the actual strategy process, bind the active `TradeLogger` config snapshot and its real event before dispatch. Let Cerebro's normal stop lifecycle finish. Have the separately running monitor service consume that genuine event and produce its own cursor/source-bound summary. Confirm zero trading writes and unchanged account configuration across snapshots.
4. Call the existing generic `run_one` only after those artifacts are collected and independently verified. Any missing field, incomplete page, uncovered symbol, changing account state, or uncertain cleanup remains blocked.

The earlier R8 actual call established seven fixed-route completions for the R8 shape probe and passed the transport lifecycle gate. It did not execute this R2 collector, prove an all-symbol trade history, produce three phase snapshots, or establish TH01 acceptance. No R8 evidence is replayed by this source-fake round.

## Source-only checks

Run from the repository root:

```text
python -m py_compile examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py scripts/iteration41_binance_th01_account_window_candidate_r2.py tests/unit/live_certification/test_binance_th01_account_window_candidate_r2.py
python -m pytest -p no:asyncio tests/unit/live_certification/test_binance_th01_account_window_candidate_r2.py -q --tb=short -ra
python -I -S -B scripts/iteration41_binance_th01_account_window_candidate_r2.py --qa-source-only
```

`py_compile` exited 0. The focused suite passed 19 tests; the only warning is the existing `asyncio_default_fixture_loop_scope` pytest-config warning. The cold launcher returned `SOURCE_ONLY_QA`, verified owner/candidate/protected-source pins, and reported `runtime_package_loaded=false`, `private_helper_loaded=false`, `protected_credential_read=false`, `provider_read_started=false`, `trading_write_started=false`, `account_full_snapshot_issued=false`, and `formal_case_pass=false`.

The source-fake suite exercises the actual tracked private helper compiled from pinned bytes with fake filesystem/OS API leaves, including private directory creation and JSON writing; it never constructs `_Win32` or invokes a native API. It checks the accepted owner's real fixed-query validator while replacing only the HTTPS leaf, loader collision/failure rollback, noninjectable owner binding, post-read file/ancestor mutation detection, cross-invocation and duplicate page-reference rejection, allOrders bisection and saturation, conflicting duplicate rows, income short-page termination, userTrades time-then-`fromId` query shapes, late rows, cursor regression, private credential clearing, and pickle target resolution in a synthetic `__mp_main__` namespace.

No real pipe, OS process spawn, `.env`, private capture, credential, provider, native, or WinAPI operation was performed. Root retains those gates. The suite establishes source behavior only and adds zero formal TH01 passes.
