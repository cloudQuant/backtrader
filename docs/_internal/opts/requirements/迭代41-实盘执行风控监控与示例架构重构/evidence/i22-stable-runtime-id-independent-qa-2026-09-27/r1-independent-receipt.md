# Independent QA: I22 stable runtime-ID migration

Verdict: `PARTIAL / NEEDS_REVISION` (`LOCAL_FAKE` behavior verified by an independent supplement).

## Frozen inputs and replay

- Candidate: `D:\temp\iteration41-r2b-i22-stable-runtime-id-migration-20260927`
- Candidate `evidence/SHA256SUMS.txt` SHA-256: `008D84C4AF60145460B771A1DC76D2FEA795841A71C7CC1163F1438F5CD803BD`. All seven indexed payload paths, byte sizes, and SHA-256 values verified successfully.
- Patch SHA-256: `7CAB249E4943EF867BC683803BDDBF60AC1F2DC8AAE5B9EE34DBAF3E7751DF36`.
- Exact r2b base `btapistore.py` SHA-256: `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`.
- Original main I22 test SHA-256: `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`.
- Applying the patch to the exact r2b base reproduced the candidate Store and test byte-for-byte (`75E6292E...C480F5AC7AD5` and `64337E4F...E63E3D655`). `replay-result.json` records full hashes and successful `git apply --check`/apply.
- Actual imported Store module origin was the independent replay copy at `replay/backtrader/stores/btapistore.py`; the origin guard blocks `bt_api_py` and `_ctp`, and no such modules were loaded.

## Tests and safety boundary

- Candidate focus, Python `C:\anaconda3\python.exe`: 1 passed, 1 existing `asyncio_default_fixture_loop_scope` pytest warning. The guard recorded zero SDK import attempts, zero network attempts, and zero native SDK modules loaded.
- Additional QA-only `_sdk_order_request` probe: 1 passed. With fake command types/API and an uninitialized Store object, a missing managed `runtime_order_id` raised before `get_runtime_order_bindings`, `new_runtime_order_binding`, or mutation of `framework_order.info`.
- Attempting to run the old test body unchanged against the new candidate failed during its `make_store()` setup with `external account actor unavailable`; it did not reach the old assertions. This is retained in `legacy-semantics-probe.log` as a fixture incompatibility, not a production behavior failure.
- No private config, real SDK/native module, provider, network, or order was accessed.

## Semantic review

The patch extracts `_validate_managed_ctp_runtime_order_id` into a pure static helper and calls it in `_sdk_order_request` before identity-scope validation and before the durable binding lookup/reservation block. The new same-nodeid test checks valid/invalid string shapes and that a rejected CTP Store constructor does not read/call an opaque API object.

The original same-nodeid test also exercised the actual `_sdk_order_request` path and asserted `lookups == []`, `reservations == []`, and `framework_order.info == {}` for a missing ID. The candidate replacement removes all three assertions and does not invoke `_sdk_order_request`. The separate `_sdk_order_request` probe in this QA packet confirms those behaviors in the current source, but that coverage is not present in the candidate test itself. Restore an actual-method fake test asserting all three invariants (using a test seam that does not require an unavailable account actor) before treating the migration as equivalent.

The helper is a valid local fake slice. This result is not a broader I22, SDK, account-actor, or AC acceptance.
