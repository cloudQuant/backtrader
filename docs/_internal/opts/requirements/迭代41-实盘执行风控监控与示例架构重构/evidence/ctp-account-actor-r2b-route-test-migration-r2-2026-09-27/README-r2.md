# R2b route-test migration candidate QA — revision 2

Date: 2026-09-27

## Scope

This revision changes only the same two test modules. No Store/runtime production source, registry, account configuration, or provider settings were modified. The tested source is the isolated r2b candidate, with its base patch SHA recorded in `artifact-manifest-r2.json`.

## Test migration

- Five generic feed/broker/cache/callback tests now declare an explicit non-CTP OKX route while retaining the core original assertions: `test_btapistore.py:1689,1711,1735` and `test_btapistore_normalized.py:379,407`.
- The supplied-SDK configuration preservation test now keeps the `store.start()` lifecycle assertion. Its injected `FakeSdk` has `async_make_order`, `async_cancel_order`, and `async_query_order` set to `None` for this test, selecting the synchronous local fake path without optional SDK imports or a command worker. It asserts `_started is True`, feed/position behavior, SDK object identity, `execution_config` object identity, and zero `configure_execution` calls, then calls `stop()` in `finally`: `test_btapistore_normalized.py:1416`.
- The opaque CTP-in-SDK case is split into an explicit CTP-route rejection test. Construction fails before the fake SDK is changed or called: `test_btapistore_normalized.py:1442`.
- The three placeholder provider parameters assert early constructor rejection with `store provider unsupported`: `test_btapistore.py:3675`.
- The selected r2b route and non-authorizing negative test modules remain included; these exercise explicit/ambiguous route fail-close and local queue receipts that are not provider acknowledgements.

## Verification

- Exact replay: `python run_guarded_pytest_r2.py` — **35 passed, 0 failed, 0 skipped**. The test-command JSON, JUnit, stdout/stderr, exit code, and import/network guard summary are retained.
- Guard summary: provider imports 0, real provider modules 0, network attempts 0.
- Ruff with the repository config: `python -m ruff check --config D:\source_code\backtrader\pyproject.toml tests/unit/stores/test_btapistore.py tests/unit/stores/test_btapistore_normalized.py` — **All checks passed**.
- The patch cleanly materializes the captured original test inputs (SHA-256 `E7E7B985…A6B1` and `84C570A2…D397`) into the tested candidate text. `git apply --check` also passes against the current main tree; no patch was applied to main.

## Limits

`start()` is covered only with an injected synchronous fake. The test intentionally disables the fake async command methods, so it does not cover the asynchronous command worker or a provider SDK lifecycle. This candidate neither authorizes CTP nor proves provider behavior or writer closure.
