# Iteration 22 stable runtime identity seam migration — r2

**Disposition:** the r1 QA finding is addressed in this isolated revision. The same I22 nodeid now retains both the pure runtime-ID format contract and the actual `_sdk_order_request` zero-side-effect assertions. The r2b Store admission boundary remains closed. This is local offline evidence and does not change `NO_WRITE / LIVE_NO_GO`.

## Frozen inputs

- r2b main-base patch: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b\r2b-main-base-apply.patch`, SHA-256 `1A16AADB94EDB99924553D6472BF72DCB02BD04C7F994276816D91991A729F37`.
- Base r2b Store output SHA-256 `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`; original I22 test SHA-256 `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`.
- r2 migration patch SHA-256: `7EDCA0B7B9DED35CD20DCBA3E7792D9E6B43C8C6A3728B56BAA90B717232C88B`. Apply it after the r2b main-base patch.
- The independent review of r1 identified that its candidate test did not retain the old no-lookup/no-reservation/no-mutation assertions. This revision adds those checks directly to the candidate test.
- The separate query pure-seam r2 patch (`6AAB9A66A328A545A5E724BADCC03C31C606F84E985F4EF5F8A8E754151F88A7`) is not included. Applying this patch followed by the query patch passed; the test hunks are in different I22 functions.

## Exact scope

Original and candidate nodeid:

`tests.unit.stores.test_btapistore_iteration22.test_managed_ctp_request_requires_stable_runtime_identity`

The frozen failure analysis classifies this as `typed order/cancel identity and legacy request`. Its original path was `provider="btapi"` with the explicit `CTP___FUTURE` selector, which now fails closed in the Store constructor before `_sdk_order_request`.

The candidate test exercises three related contracts under the same nodeid:

1. The pure static `BtApiStore._validate_managed_ctp_runtime_order_id` accepts one canonical identity and rejects missing, uppercase-hex, short, and wrong-prefix values. `_sdk_order_request` delegates to this helper at its previous validation point.
2. The original explicit CTP selector remains fail-closed. A trap API observes zero attribute reads and zero calls.
3. The actual `_sdk_order_request` method is invoked on an uninitialized object made with `object.__new__(BtApiStore)`. It is never passed through `BtApiStore.__init__` or Store lifecycle. A local fake API counts durable binding lookups and reservations; a missing runtime identity raises before either method runs, and `framework_order.info` remains empty.

The third check restores the exact regression coverage called out by r1 QA while avoiding Store construction or SDK import on that method path. The test does not exercise runtime-scope acceptance, a positive CTP request, or a real SDK/account actor. No tests were deleted, skipped, or xfailed.

## Verification

- Baseline focused run: **1 failed, 0 skipped** at the r2b Store constructor gate; the JUnit contains the same nodeid.
- Candidate guarded focused run: **1 passed, 0 failed, 0 skipped**, same nodeid. The runner blocks `bt_api_py` and `_ctp` imports and socket connection calls; observed SDK import attempts `0`, SDK modules loaded `0`, network attempts `0`.
- Candidate assertions confirm `api.lookups == []`, `api.reservations == []`, and `order.info == {}` after `_sdk_order_request` rejects the missing runtime ID.
- Independent r2 QA: **PASS** after fresh replay from the exact frozen inputs. The patched source and test hashes match; focused JUnit is 1 passed with all SDK/native and network counters zero. Receipt: `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\receipt.md`; independent JUnit SHA-256 `E8400BEF10BF3B766841FADADEEB6AE72F9D63B33739F661CDA504DB9BFD4DC3`.
- Patch application reproduced the candidate Store and test byte-for-byte from the stated r2b source and original I22 inputs. Sequential application with the separate query pure-seam patch also passed.
- Pytest emitted the existing Quandl deprecation and unknown `performance` marker warnings.
- Shared main repository was not modified. No private config, SDK, native module, provider, network, or order was accessed.

## Artifacts

- Patch: `r2-i22-stable-runtime-id-migration.patch`
- Baseline JUnit: `evidence/baseline-i22-stable-runtime-id.junit.xml`
- Candidate JUnit: `evidence/candidate-i22-stable-runtime-id.junit.xml`
- Guarded runner: `evidence/run_candidate_guarded.py`
- Verification manifest: `evidence/verification.json`
- Checksums: `evidence/SHA256SUMS.txt`
