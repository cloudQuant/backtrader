# Binance TH01 spawn/Pipe gate R1 independent review R2

Date: 2026-10-09  
Verdict: `GO_ROOT_LOCAL_SYNTHETIC_GATE_ONLY`

## Reviewed pins

| Role | Repo-relative path | Bytes | SHA-256 |
|---|---|---:|---|
| Gate helper | `scripts/iteration41_binance_th01_spawn_pipe_gate_r1.py` | 43,645 | `2eae250fe2af32315496fd6ad7b9fd1df4e14fd345e79433b12487f944f968e4` |
| Fake source tests | `tests/unit/live_certification/test_binance_th01_spawn_pipe_gate_r1.py` | 17,451 | `0da362ec90b2accc96ffeaa3e7833ef09b671e888d03d2ee77ea74886691f4b1` |
| R2 launcher | `scripts/iteration41_binance_th01_account_window_candidate_r2.py` | 11,391 | `698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6` |
| R2 candidate | `examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py` | 62,664 | `4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63` |
| Accepted fixed-GET owner | `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |

All five pins matched before and after review. Checkout was `dev` at `9de5439cf3daadd42b96915b94e3c9b6e7a0e1cc`; the helper and test were untracked. This review did not stage or commit files.

## Source-fake checks

The isolated CPython 3.11.5 QA interpreter ran the single focused file with `-I -S -B`, explicit QA `site-packages`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH` removed, and asyncio/cache plugins disabled: **12 passed**, with the existing `asyncio_default_fixture_loop_scope` configuration warning.

The cold command `python -I -S -B scripts/iteration41_binance_th01_spawn_pipe_gate_r1.py --qa-source-only` exited 0 and returned `SOURCE_ONLY_QA`; `worker_spawned`, provider read, credential read, account snapshot, trading write, and formal pass were false. No actual spawn/Pipe gate was run.

## Review findings

The helper installs source guards in both `__main__` and `__mp_main__` before loading the pinned launcher. Child bootstrap registers the `__mp_main__` module in `sys.modules` before compiling the launcher, and validates the loaded owner and candidate before worker resolution. The fake child test checks the worker's module/global namespace and pickle resolution.

The one-shot observed context delegates one-way Pipe creation and the fixed worker Process to the real spawn context. The process wrapper delegates lifecycle calls; the patched `BaseProcess.start` allows only the recorded process during the active capability. The call fixes the `allOrders` query, synthetic key/secret, worker name, daemon flag, and finite deadline. The worker receives a fake HTTPS response containing `[]`.

The successor explicitly replaces and restores the top-level `multiprocessing.Pipe` alias. Its guard test calls that alias only while the deny wrapper is installed, expects `PermissionError`, and then checks identity restoration; it does not call the original or create OS handles. The context and connection Pipe APIs, general Process factories, process start, subprocess, OS launch functions, private paths, SQLite, DNS, and common socket connect APIs are also guarded in the inspected source.

Pre-call pins are checked before the owner call. The `finally` path checks launcher, owner, candidate, and candidate dependency pins after both successful return and owner exceptions. If worker or Pipe cleanup is uncertain, the owner namespace and worker/endpoint references remain in module-visible collections, source guards remain installed, and `_gate_exit_permitted()` blocks normal exit. The fake tests cover retention and post-call candidate tamper detection; the success/exception post-call placement was confirmed by source inspection.

## Scope limits

This accepts only the next Root-local synthetic spawn/Pipe gate invocation from the interactive TTY entry. It does not accept TH01 account coverage, real provider behavior, or a certification pass. No credentials, private captures, provider/network calls, native/WinAPI calls, real Pipe, process spawn, or Root actual path were used in this review. The accepted R2 candidate's 19-test result was not repeated.
