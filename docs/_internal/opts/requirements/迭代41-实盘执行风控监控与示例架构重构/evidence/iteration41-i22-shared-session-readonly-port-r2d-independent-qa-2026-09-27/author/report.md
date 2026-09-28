# r2d: fake read-port contract slice

## Disposition and dependency

`FAKE_READ_PORT_CONTRACT_ONLY`. This isolated candidate is additive to the frozen r2c QA source. `backtrader/stores/ctp_account_actor_port.py` is introduced by the earlier r2c patch and is absent from current main; **the r2d patch is not directly applicable to main**. It changes no files in `D:\source_code\backtrader` and does not bind the read port into `BtApiStore`. The account Actor remains absent, so default CTP Store construction still fails closed before provider resolution or injected-client attribute access. Overall posture remains `NO_WRITE / LIVE_NO_GO`.

## Frozen source and patch

The r2d patch is additive to the frozen r2c reviewed source, following the frozen r2b base Store-wiring patch and r2c additive Store-safety patch. It is deliberately separate from the query-evidence test-seam r2 patch; a sequential replay applied that query seam first, then passed r2d `git apply --check` and application.

Files changed by the r2d patch:

- `backtrader/stores/ctp_account_actor_port.py`
- `tests/unit/stores/test_btapistore_iteration22.py`
- `tests/unit/stores/test_ctp_shared_session_read_port.py` (new)

The actor-port module now defines typed request/reply dataclasses for scoped positions/trades and top-of-book quote reads, a narrow `CtpSharedSessionReadPortV1` Protocol, and local validation helpers. Read requests/replies require exact trimmed correlation text; quote requests/replies also require exact trimmed exchange/instrument IDs. Query replies require the exact kind and correlation ID; trade rows require exact exchange, instrument and trading day. Quote replies require exact requested scope/correlation and valid typed values. Record mappings are frozen. Negative shape tests cover padded request identifiers.

The port has no authenticated account/session identity, no common-snapshot or transaction token, no settlement-confirm authority, no freshness proof, and no Store runtime wiring. It grants no provider binding, production admission or write authority. This candidate does not add a runtime Store integration.

The fake read port exists only in tests. A fake may demonstrate method wiring and shape/scope validation. It is not a real CTP shared session, runtime registration, production feed or admission signal. A negative constructor test supplies both no Actor and a fake read-only port; both attempts fail closed before provider resolution and before reading the injected API object, and the fake port receives no calls.

## Exact test scope and comparison

The frozen r2c JUnit showed 200 I22 nodeids failing at `external account actor unavailable`. The selected three old nodeids now exercise local read-contract helpers rather than asserting that a local Store owns an SDK/session:

1. `test_empty_incomplete_query_is_not_interpreted_as_zero_records`
2. `test_query_request_type_mismatch_fails_closed`
3. `test_preflight_rejects_trade_rows_outside_the_requested_scope`

The candidate focus also runs four new tests for a typed positions+quote read through one fake port object, quote scope/correlation rejection, invalid typed shapes, and the constructor fail-close boundary. Baseline/candidate status and the complete preserved list of 197 untouched nodeids are in `r2d-nodeid-baseline-candidate.json`; the 200-row classification is in the two `r2c-*classification*` artifacts.

Exactly 3/200 original I22 nodeids are migrated in this slice. The other 197 retain their original baseline failure classification in the inventory; they were not migrated or rerun by this focused candidate. Authorization/arm/recovery/lifecycle and order/cancel identity cases remain outside scope. No test was deleted, skipped, xfailed, or weakened into an empty assertion.

## Verification

- Guarded focused pytest: **7 passed**, one existing `PytestConfigWarning` about unknown `asyncio_default_fixture_loop_scope`.
- Guard report: no blocked SDK/native import attempts, no SDK/native modules loaded, and zero network attempts.
- `ruff check` on the three touched source/test files: passed.
- `py_compile` on the two source files and new test file: passed.
- Sequential patch replay: the query-evidence test-seam patch was applied first and r2d second on a fresh copy of the frozen r2c preimage. Both `git apply --check` runs and applications passed; the four resulting files matched the expected composite output after newline normalization. See `patch-replay.log`.
- Captured stdout/stderr and exact verification commands are included as `guarded-focus.log`, `ruff-check.log`, `py-compile.log`, `patch-replay.log` and their runner scripts.

The focused run validates only local typed fake-read contracts and the no-Actor fail-close boundary. It does not establish actor deployment, real shared-session coherence, authenticated account scope, provider correctness, production admission or any permission to write. `NO_WRITE / LIVE_NO_GO` remains in force.

## Evidence files

- Patch: `evidence\r2d-shared-session-readonly-port.patch`
- Baseline/candidate exact nodeids: `evidence\r2d-nodeid-baseline-candidate.json`
- Guarded focused JUnit: `evidence\candidate-focused.junit.xml`
- SDK/native/network guard: `evidence\focused-guard-report.json`
- Input and 200-node classification: `evidence\r2c-input-and-nodeid-classification.json`, `evidence\r2c-i22-nodeid-classification.csv`
- SHA-256 manifest: `evidence\r2d-artifact-hashes.json`
