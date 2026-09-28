# BM58 two-client capacity harness

**Disposition:** implementation and smoke-harness checks complete. The result is `FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED`; it does not pass AC41-58.

The new script is a standard-library-only diagnostic. It creates exactly two spawned local client processes that share the script's own SQLite WAL intent/claim tables. Each process produces work and consumes claims; completion calls a deterministic fake provider that only sleeps and hashes a receipt. It does not call a registered Backtrader runtime, actor-server API, SDK, native API, CTP, account, credentials, or network.

The default profile is 10 intents/s for 2 seconds. `--profile capacity-30m` is required to select 50 intents/s for 30 minutes. The 30-minute profile was not run.

Profile validation rejects non-finite fake latency, non-exact integer rates/counts, and unsupported override combinations before starting worker processes.

## Verification

- Focused tests: 4 passed in 9.01s under CPython 3.11.5 with pytest plugin autoload disabled; one existing unknown-config-option warning remains.
- Ruff check and format check: clean.
- The script ran its default smoke profile under CPython 3.12.10: 20 unique intents accepted/completed, 2 duplicate attempts, 0 lost/incomplete, peak backlog 1, backlog drained, 0 native/provider-dispatch/network calls. This tests only the harness, not actor/runtime capacity.
- Both new Python files parse using Python 3.8 grammar. A Python 3.8 interpreter was not present; the installed Python 3.12 environment had no pytest package.

## Reproduce

From the repository root:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m pytest tests/unit/scripts/test_run_iteration41_actor_capacity_benchmark.py -q -p no:cacheprovider
python -m ruff check scripts/run_iteration41_actor_capacity_benchmark.py tests/unit/scripts/test_run_iteration41_actor_capacity_benchmark.py
python -m ruff format --check scripts/run_iteration41_actor_capacity_benchmark.py tests/unit/scripts/test_run_iteration41_actor_capacity_benchmark.py
```

The full smoke output, raw SQLite/CSV files, source copies, and command logs are in this evidence packet. `evidence-manifest.json` lists per-file sizes and SHA-256 values; the ZIP contains the packet including that manifest.
