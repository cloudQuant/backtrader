# BM58 local two-client capacity harness

**Status:** harness implemented; smoke diagnostics only. `AC41-58` remains unaccepted.

Added `scripts/run_iteration41_actor_capacity_benchmark.py` and focused fake-only tests. The harness launches exactly two spawned local client processes that share the script's own SQLite WAL admission/claim tables. Each process submits synthetic intents and consumes claims through a deterministic local fake provider delay. It records planned/input attempts, accepted/completed/duplicate/lost counts, maximum backlog, drain time, and backpressure samples.

The default run is 10 intents/s for 2 seconds. The 50 intents/s × 30 minutes profile requires the explicit `--profile capacity-30m`; it was not run. Every output is marked `FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED`. This is not an integration with the G6-P actor-server candidate, registered runtime, Store, SDK, CTP, account, provider, credentials, or network. The SQLite protocol is benchmark-owned and cannot establish actor or provider capacity.

## Verification

- Focused tests: 4 passed in 9.01s on CPython 3.11.5; one repository pytest config warning (`asyncio_default_fixture_loop_scope`) remains. Plugin autoload was disabled for the known global pytest-plugin incompatibility.
- Ruff check and format check: clean.
- CPython 3.12.10 smoke: 20/20 unique intents completed, 2 duplicate attempts observed, 0 lost/incomplete, backlog drained, peak backlog 1, and zero native API, provider-dispatch, or network calls.
- Both files parsed with Python 3.8 grammar. A CPython 3.8 runtime was unavailable. CPython 3.12 had no pytest installation, so tests were run on 3.11.

The exact copied source and raw smoke data are in [the evidence packet](bm58-two-client-capacity-2026-09-27/INDEX.md). Its machine manifest SHA-256 is `9426567739623296a95b78cd7c288a38f96764d0c7f38e4e1a45d26e88ac5adb`; the raw ZIP SHA-256 is `9363d92ecdda7527a12feb5e7357793458047067f137f336a795c3859a948272`. The implementation SHA-256 is `b1f02883d706c6d5449c5483a9a67fc32dae99f903c16fd2738e5e1b278759b1`; focused test SHA-256 is `20db109b2525bf507d20277c8674f6459b64a1a4da9f3c5383a858ffcb8f2fabb`.
