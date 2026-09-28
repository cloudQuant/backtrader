# Independent QA receipt — I22 stable runtime identity migration r2

**Disposition: PASS**

## Frozen inputs and patch replay

- Patch: `D:\temp\iteration41-r2b-i22-stable-runtime-id-migration-r2-20260927\r2-i22-stable-runtime-id-migration.patch`
  - SHA-256: `7EDCA0B7B9DED35CD20DCBA3E7792D9E6B43C8C6A3728B56BAA90B717232C88B`
- r2b base Store input: SHA-256 `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`
- Original I22 test input: SHA-256 `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`
- `git -c core.autocrlf=false apply --check` and `git -c core.autocrlf=false apply` both succeeded in the fresh replay at `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\replay-autocrlf-false`.
- Patched Store SHA-256: `75E6292E53F5FB8F70194114BDD5544D8FEB00FAAC9AA543A620C480F5AC7AD5`; patched test SHA-256: `505E8F414D3FFD97355C5A4E81504B9286786581DCF86B21D4571B3135390904`. Both match the frozen r2 outputs.
- A preliminary application with the host's default `core.autocrlf` changed mixed line endings. The authoritative replay disabled autocrlf and reproduced both expected output hashes exactly.

## Focused guarded run

- Nodeid: `tests.unit.stores.test_btapistore_iteration22.test_managed_ctp_request_requires_stable_runtime_identity`
- Interpreter: CPython 3.11.5
- Result: **1 passed, 0 failed, 0 errors, 0 skipped**; exit code 0.
- JUnit: `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\independent-i22-stable-runtime-id.junit.xml`
  - SHA-256: `E8400BEF10BF3B766841FADADEEB6AE72F9D63B33739F661CDA504DB9BFD4DC3`
- SDK/native import attempts: 0; blocked SDK/native modules loaded: 0; network attempts: 0.
- Two existing warnings appeared: Quandl deprecation and the unregistered `performance` marker.

## Semantic review

The same nodeid retains all three requested checks:

1. Pure `_validate_managed_ctp_runtime_order_id` validation accepts the canonical lowercase 64-hex runtime ID and rejects missing, uppercase, short, and wrong-prefix values.
2. The explicit `CTP___FUTURE` constructor probe fails with `external account actor unavailable`; the `TrapApi` records zero attribute reads and zero calls.
3. The actual `_sdk_order_request` method runs against an instance created only with `object.__new__(BtApiStore)`, local fake API/command types, and a local order object. Missing runtime ID raises before binding lookup or reservation; `api.lookups == []`, `api.reservations == []`, and `order.info == {}`.

No Store instance was successfully initialized for the actual method check. The CTP fail-close assertion intentionally invokes the constructor, which aborts at its admission gate before accessing the trap API. No SDK/native module, private config, external provider, network connection, or order was accessed or submitted.

## Limits

This verifies the missing-ID rejection path and the pure format helper only. It does not verify a positive CTP request, runtime-scope acceptance, account actor behavior, or a real SDK/provider path. This is focused local evidence, not release or live-execution acceptance.

## Reproducibility files

- Guarded runner: `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\run_independent_guarded.py`
- Console log: `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\independent-run.log`
- Machine-readable receipt: `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\verification.json`
- Checksums: `D:\temp\iteration41-r2b-i22-independent-qa-r2-20260927\SHA256SUMS.txt`