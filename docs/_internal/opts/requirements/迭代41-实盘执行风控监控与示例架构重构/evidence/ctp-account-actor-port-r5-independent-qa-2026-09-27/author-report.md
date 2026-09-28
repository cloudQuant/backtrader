# Iteration 41 AccountActorPort r5 local fake contract

Date: 2026-09-27
Result: LOCAL_FAKE_CONTRACT_PASS
Base: frozen r4 candidate-copy, verified against candidate-original manifest before edits.

## Scope

This is an isolated D temp candidate. No Backtrader main-tree files were changed. The source remains unwired to BtApiStore, runtime inventory, or any provider route.

Changed candidate files:
- source/account_actor_port.py
- source/store_boundary_harness.py
- source/store_boundary_harness_testonly.py (new; unit-test-only fake dispatch)
- source/README.md
- source/INTEGRATION_CONTRACT.md
- tests/test_store_boundary_harness.py

## Contract changes

- Captures an immutable, type-tagged canonical route snapshot and SHA-256 digest. Every submit/cancel rechecks the current route and compares both digest and canonical bytes before dispatch.
- Nested route mutation fails before actor or legacy dispatch. An equal-content replacement mapping preserves the same semantic snapshot.
- Route fingerprinting accepts exact built-in values, reads the exact descriptor instance dictionary, and rejects custom mapping/opaque nested values without invoking their methods or properties. API/API-class instances are represented only by presence and are never introspected.
- The ordinary StoreBoundaryHarness has no fake-dispatch option. With no trusted durable remote Actor implementation in this candidate, default typed CTP submit/cancel fails with trusted_durable_remote_actor_unavailable before actor-port invocation.
- Fake actor plumbing and the in-memory replay ledger live in store_boundary_harness_testonly.LocalFakeStoreBoundaryHarness, a separate test-only module. It is not imported by Backtrader, a Store, or a runtime registry. The ledger proves only same-process fake behavior; it cannot establish cross-process uniqueness or account authority.
- Existing typed intents, receipt equality checks, stale context/epoch rejection, and no-local-fallback behavior remain covered.

## Verification

- CPython 3.11.5 unittest focused/adversarial suite: 40 passed.
- Pytest/JUnit run: 40 passed; report at JUnit/r5-results.xml.
- Ruff: all checks passed for four changed Python files.
- In-memory syntax compilation: 4 Python files passed. Patch replay also passed git apply --check and matched all six changed files after newline normalization.
- Adversarial cases include route field/nested mapping mutation, same-content replacement, custom mapping trap methods, stale context/epoch, bad receipts, fake actor no-fallback, two reopen attempts, and a fresh subprocess. The default path blocked each same command before actor or legacy calls.
- A source-tree search found no reference to the test-only module/class in backtrader/ or backtrader_runtime/.

## Limits

LOCAL_FAKE only. There is no trusted remote Actor, transport, service identity, durable server-side ledger, provider/account authority, cross-host fence, callback inbox, or real receipt authentication. This is not G6-S/G6-P, F14 acceptance, a Store integration, a live route, or permission to submit/cancel orders. No SDK, native client, network, private config, or real order was used.

