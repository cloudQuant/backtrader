# Iteration 22 stable runtime identity seam migration

**Disposition:** one selected I22 failure is migrated as a pure validation contract while the r2b CTP Store boundary remains closed. The scope is exactly one of the 200 original failing I22 nodeids, from the four-case typed order/cancel identity group. This is local offline evidence and does not change `NO_WRITE / LIVE_NO_GO`.

## Frozen inputs

- r2b main-base patch: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b\r2b-main-base-apply.patch`, SHA-256 `1A16AADB94EDB99924553D6472BF72DCB02BD04C7F994276816D91991A729F37`.
- The isolated test source used r2b's Store output with SHA-256 `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518` and the frozen original I22 test input with SHA-256 `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`.
- Migration patch SHA-256: `7CAB249E4943EF867BC683803BDDBF60AC1F2DC8AAE5B9EE34DBAF3E7751DF36`. It is an overlay to apply after the r2b main-base patch.
- The separate query pure-seam r2 patch (`6AAB9A66A328A545A5E724BADCC03C31C606F84E985F4EF5F8A8E754151F88A7`) is not included here. A sequential application check passed; its I22 hunk is around the nested query test, distinct from this identity test hunk.

## Exact migration scope

Original and candidate nodeid:

`tests.unit.stores.test_btapistore_iteration22.test_managed_ctp_request_requires_stable_runtime_identity`

The frozen failure analysis classifies it as `typed order/cancel identity and legacy request`; its route is `provider="btapi"` with the explicit `CTP___FUTURE` selector. It was one of 200 test cases failing at Store construction with `external account actor unavailable` before `_sdk_order_request` ran.

The migration extracts the existing managed CTP `runtime_order_id` format check into the pure static helper `BtApiStore._validate_managed_ctp_runtime_order_id`. `_sdk_order_request` calls that helper at the same point as the previous inline validation. The retained nodeid checks one accepted canonical id and four rejected forms (missing, uppercase hex, short, wrong prefix).

The same nodeid also asserts the exact CTP selector still fails during Store construction. A trap API records attribute reads and calls; both remain zero. The helper receives only the id value and cannot consult a Store, actor, SDK, network, or account state.

This migration preserves the runtime-id format contract and the pre-client CTP fail-close assertion. It does not exercise the managed execution adapter, runtime scope, SDK OrderRef lookup/reservation, or a positive CTP request. Those require a separately accepted Actor contract. No test was deleted, skipped, or xfailed; the original nodeid remains collected.

## Verification

- Baseline command (from the isolated r2b root): `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 C:\anaconda3\python.exe -m pytest tests/unit/stores/test_btapistore_iteration22.py::test_managed_ctp_request_requires_stable_runtime_identity -p no:asyncio -q --tb=short --junitxml=evidence/baseline-i22-stable-runtime-id.junit.xml`.
- Candidate command: `C:\anaconda3\python.exe evidence/run_candidate_guarded.py`.
- Baseline focused run: **1 failed, 0 skipped** at the r2b constructor gate. The JUnit records the same original nodeid.
- Candidate guarded focused run: **1 passed, 0 failed, 0 skipped**, same nodeid. The runner blocks `bt_api_py` and `_ctp` imports and socket connection calls; observed SDK import attempts `0`, SDK modules loaded `0`, network attempts `0`.
- `git apply --check` and application reproduced the candidate files byte-for-byte from the stated r2b Store and original I22 inputs.
- Applying this patch followed by the separate query pure-seam r2 patch also passed, confirming the two hunks do not overlap.
- Pytest emitted the existing Quandl deprecation and unknown `performance` marker warnings.

## Artifacts

- Patch: `i22-stable-runtime-id-migration.patch`
- Baseline JUnit: `evidence/baseline-i22-stable-runtime-id.junit.xml`
- Candidate JUnit: `evidence/candidate-i22-stable-runtime-id.junit.xml`
- Guarded runner: `evidence/run_candidate_guarded.py`
- Checksums: `evidence/SHA256SUMS.txt`
