# Iteration 41 main-tree fake/offline integration QA

Verdict: `PASS_FAKE_OFFLINE_SCOPE_ONLY`.

On 2026-09-27, four final pytest blocks ran against the current shared main-tree snapshot in separate processes, with an isolated `sitecustomize.py` guard. The guard blocked actual imports of optional `bt_api_*` products and denied non-loopback DNS/socket access; it permitted three loopback connections used by fake Store command channels. No CTP client/native module import or non-loopback network call was observed. `BT_API_TEST_SOURCE_ROOTS` was removed. Pytest plugin autoload, bytecode writes, and cache provider were disabled; all pytest basetemp/JUnit/log output is under this QA directory.

## Results

- Store R5/Gateway deny plus normalized projection controls: 15 passed.
- G6 local fake Actor package (wire, server core, Store boundary): 65 passed.
- Writer scanner/rebaseline (inventory, indirect dispatch, dispositions): 15 passed.
- Selected upper-framework Iteration 41 integration: 2 passed, 10 skipped at optional source gates / unavailable `bt_api_execution`.
- Aggregate: 97 passed, 10 skipped, 0 failures for the final guarded runs. Each run emitted the same PytestConfigWarning for `asyncio_default_fixture_loop_scope`; this is because plugin autoload was intentionally disabled.

The two executed upper-framework positives cover sell-sign/reverse-position projection and runonce/runnext multi-data partial-fee parity. The eight source-gated modules/cases did not execute; their optional source package was not made available. Of the ten skips, the economic-fact file was collection-skipped and nine cases were skipped by source gates.

## Static screening and exclusions

The inventory records all 13 `tests/integration/test_iteration41*.py` files and the chosen disposition. The `ctp_i9_account_session_candidate` and `ctp_managed_account_runtime_candidate` tests were excluded because they enter CTP account/native-adjacent paths. `deployment_evidence_interop` was excluded because it is an optional external-product composition. No private config was read. `bt_api_ctp` was discoverable in the global interpreter by static module-spec lookup, but no test importing it was selected and no such import occurred under the final guard.

The selected Gateway Store composition, framework-recovery, execution, cancellation, replay, packaged fixture and mechanical replay integration nodes were source-gated and skipped, so their integration behavior was not verified here. Passing local Gateway denial unit tests do not substitute for those composite suites.

## Guard instrumentation note

An earlier deliberately overbroad experimental guard blocked loopback and raised from `find_spec`; it produced three fake Store test failures and nine collection errors. Those were guard-harness artifacts, not product failures. The raw logs are retained as `store-gateway-guarded.log` and `framework-projection-guarded.log`; final verdict uses only the corrected guard runs `*-final.log`/`*-final.xml`. The corrected guard permits loopback solely so the local fake command channel can work, and refuses all non-loopback socket/DNS operations. Its logs show three allowed loopback connections, one blocked lookup/import for the absent optional `bt_api_execution` module, and no blocked non-loopback network operation.

## Limits

This is regression evidence for local fake behavior only. It does not establish G1/G5 acceptance, real CTP connection, SDK/native lifecycle, account authority, broker/gateway service availability, live dispatch, or production readiness. No Store/source code was edited by this QA task; the shared main tree was already dirty from concurrent work, so this report does not attribute unrelated working-tree changes.

See `commands-and-results.txt`, `integration-inventory.json`, `source-hashes.json`, final JUnit/log files, and `payload-manifest.json` for reproducible commands and hash-bound inputs/outputs.
