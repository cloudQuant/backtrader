# Iteration 10 SCN01 service backend and cleanup boundary

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`, source parent `74d136eea17405bc0acbaea5e8b35c84e39d6e55`.

This round adds the normal C01 `ServiceClientRuntime`/`ServiceHost` synthetic path and makes uncertain service-client shutdown visible in the result. If `client.close()` raises after a service case otherwise returns PASS, the runner now emits `UNKNOWN/service_cleanup_unconfirmed`, records `facts.service_cleanup=unconfirmed`, and does not serialize the exception detail. Direct-transport cleanup behavior is unchanged. The new regression uses a fake close failure; it does not contact Binance or use account credentials.

## Acceptance evidence

The earlier author run for this source round ran:

```text
& '.venv/Scripts/python.exe' -m pytest -p no:asyncio -q tests/unit/test_scn01_binance_service_backend.py tests/unit/test_scn01_binance_certlib_fail_closed.py
.......                                                                  [100%]
7 passed, 1 warning in 1.08s
```

Its seven cases were the five retired-optional-backend parameter cases, the existing direct-entry constructor case, and the normal C01 ServiceClientRuntime/ServiceHost synthetic integration. The single warning was the existing pytest configuration warning for `asyncio_default_fixture_loop_scope` with this environment's pytest/pytest-asyncio versions. This original run was not repeated.

After the cleanup-boundary change, only the new regression node was run:

```text
& '.venv/Scripts/python.exe' -m pytest -p no:asyncio -q tests/unit/test_scn01_binance_service_backend.py::test_service_close_failure_downgrades_pass_to_unknown
.                                                                        [100%]
=============================== warnings summary ===============================
C:\anaconda3\Lib\site-packages\_pytest\config\__init__.py:1394
  C:\anaconda3\Lib\site-packages\_pytest\config\__init__.py:1394: PytestConfigWarning: Unknown config option: asyncio_default_fixture_loop_scope

    warnings.warn(PytestConfigWarning(...))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1 passed, 1 warning in 0.70s
```

The test verifies the returned summary and evidence are UNKNOWN with `service_cleanup_unconfirmed`, and the opaque close exception is absent from output. The first focused attempt exposed an incomplete fake `connect()` result (`time_offset_ms` missing); the fixture was corrected and the passing node above is the only accepted cleanup regression result.

`ruff check` passed for `runner.py` and the focused test. `git diff --check` passed. `ruff format --check` still flags pre-existing formatting drift elsewhere in the already modified `runner.py` (configuration error output, argument formatting, context/evidence construction); this round leaves those unrelated formatting hunks untouched.

Evidence level: source/fake and local synthetic ServiceHost only. No real Binance provider call, account read, credential use, formal SCN case PASS, or external venue interaction occurred.

## Exact source scope

The code scope is the C01 config/sample, certlib backend/runner/context exports, README, and focused backend test. Unrelated existing changes and untracked evidence remain outside this round. The adjacent JSON record carries the exact path/hash inventory and verification facts.
