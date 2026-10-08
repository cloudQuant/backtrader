# Binance TH01 account-window candidate R2 independent review

Date: 2026-10-09  
Verdict: `GO_SOURCE_FAKE_ONLY`, conditional on the trusted Root-held launcher described below.

## Reviewed source pins

All candidate, launcher, dependency, and round-record bytes matched these pins before and after review. The focused test file had been updated to add a duplicate request/response-reference rejection case; this review used that final 19-test version.

| Role | Repo-relative path | Bytes | SHA-256 |
|---|---|---:|---|
| Account-window candidate | `examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py` | 62,664 | `4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63` |
| Cold launcher | `scripts/iteration41_binance_th01_account_window_candidate_r2.py` | 11,391 | `698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6` |
| Focused source-fake tests | `tests/unit/live_certification/test_binance_th01_account_window_candidate_r2.py` | 30,219 | `d7fad941b1326bd21e37fb5340002c675656e3eb5664ce7b3a93ff43f7751deb` |
| Fixed-GET owner dependency | `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |
| Protected reader dependency | `backtrader_runtime/certification_binance_roundtrip_r3_cli.py` | 33,887 | `62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76` |
| Private artifact helper dependency | `backtrader_runtime/certification_roundtrip_private.py` | 17,537 | `b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd` |
| Candidate round record | `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-binance-th01-account-window-candidate-r2-2026-10-09.md` | 10,686 | `892c3eb895fcceb3b481b73992b6658e92b5321b4fa0f213b0928d5bb76c0ed8` |

At review start the existing `dev` checkout was at `309fafdd0c43bd4b4d61ac3cc1c71ca6c80ea5f6`; at review end it was at `565cb93298a53703c47390a05eb23a1ff4985b09`. Root reported that intervening HEAD movement as its separately accepted SimNow content round. The six candidate/dependency pins and this round record remained unchanged across review. The four candidate artifacts and round record were untracked during review; no staging or commit was performed here.

## Source review

- The launcher exact-loads the pinned owner and candidate source. The candidate checks its own source binding and preflights all three required dependencies before it reads the protected `.env` or creates the private writer. It then re-reads and hash-verifies the protected reader/helper bytes, registers fresh helper module names in `sys.modules` before execution, and removes a failed module load.
- The reader exposes seven fixed GET resource families. The pinned owner validator rejects other paths and query shapes. The candidate contains no order placement, cancellation, original CID/ActionRef lookup, allocation, or retry route.
- Limits are 64 total requests, 5,000 total rows, 2 MiB per response, 64 MiB total response bodies, 120 seconds per capture, and an 8-second request timeout. Root input validation requires a recent cutoff and bounds the window to 71 hours and 89 days.
- `allOrders` uses padded inclusive millisecond queries and disjoint `[lo, mid]` / `[mid + 1, hi]` bisection. A full one-millisecond interval blocks. Rows are checked against the padded interval, deduplicated by exact `(symbol, orderId)`, and conflicting duplicate facts block.
- `userTrades` requires a symbol. Its initial request uses time bounds; every continuation uses `fromId` without time bounds. It validates row identity, symbol, ordering, window, cursor progress, and duplicate consistency.
- The candidate symbol union is explicitly not a complete trade universe. `user_trades_universe_closed` remains false, and `account_full_attestation()` always blocks. Public output is `CANDIDATE_ONLY`; it cannot issue an `account_full` snapshot or formal case pass. The new negative test confirms that repeated request/response references block candidate construction.
- In `finally`, the returned credential dictionary is cleared and entries in the authorization credential box are replaced with empty strings. This drops the retained references; it does not prove zeroization of immutable Python string memory.

The caller/source markers, `sys.modules["__main__"]` identity, `__file__`, and code `co_filename` checks bind the loaded source within the current process. They do not authenticate an external caller: a process that controls Python state can forge such markers. Therefore this verdict relies on Root checking the exact pins and invoking the candidate only through its trusted held launcher. The candidate markers alone are not an external authorization mechanism.

## Independent QA evidence

The latest focused suite passed **19 tests**, with one existing `asyncio_default_fixture_loop_scope` pytest configuration warning. It ran under the designated CPython 3.11.5 QA interpreter with `-I -S -B`, explicit QA `site-packages`, plugin autoload disabled, `PYTHONPATH` removed, and `asyncio`/cache plugins disabled. The test module's socket deny remained active. `ssl` was imported before pytest so the owner import of `http.client` could initialize `ssl` before the test fixture replaced `socket.socket`.

An initial isolated harness attempt without that preload produced 4 setup/import failures and 15 passes because the socket fixture replaced the standard-library socket class before `ssl` initialization. The corrected 19-test run passed; this was an import-order interaction in the test harness.

The cold launcher `--qa-source-only` check returned `SOURCE_ONLY_QA` with hard guards active for `.env`/private-capture path access, socket/network operations, `ctypes.WinDLL`, and ctypes dynamic library loads. It reported the owner, candidate, and protected-source pins checked; `runtime_package_loaded`, `private_helper_loaded`, `protected_credential_read`, `provider_read_started`, `trading_write_started`, `account_full_snapshot_issued`, and `formal_case_pass` were all false.

## Remaining gates

This is source/fake evidence only. Root must still run the credential-free real-Pipe and cold synthetic-spawn/pickle target-resolution gate before any account read. That gate must run under the trusted Root-held launcher after fresh public pin checks. The earlier R8 transport invocation is consumed and remains transport evidence only; it must not be repeated or represented as collector acceptance.

No credentials, `.env`, private capture, provider, native API, WinAPI, real pipe, OS process spawn, or account route was invoked in this review. This review does not read or retry the unresolved UNKNOWN order. Provider-backed trade-universe closure, three complete fresh `account_full` snapshots, actual TradeLogger ingestion, independent monitor output, and formal TH01 acceptance remain unproven; no formal case pass is added.
