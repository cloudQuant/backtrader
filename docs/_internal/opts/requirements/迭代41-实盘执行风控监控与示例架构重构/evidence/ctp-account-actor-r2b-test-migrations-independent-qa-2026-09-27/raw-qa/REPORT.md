# Independent QA: r2b test migrations

Date: 2026-09-27 (local Windows fake/offline review)

## Scope and verdict

This review independently replayed two test-only migration patches against isolated copies of the recorded r2b candidate. Neither patch changes production code.

- Credential-safety migration: `SAFE_LOCAL_TEST_MIGRATION`. It preserves repr/str masking and informativeness checks while adapting their fixture to the supported non-CTP Store route; the new CTP negative verifies rejection before credential-mapping traversal or API construction.
- Projection-bridge migration: `SAFE_LOCAL_TEST_MIGRATION_WITH_COVERAGE_LIMIT`. It preserves adapter projection/replay/UNKNOWN semantics and private queue ordering/negative side-effect checks under explicit local fakes. It narrows prior Store-level positive submit/cancel and raw-cancel-path assertions to pure adapter/private-queue tests plus a constructor-rejection test. Treat this as test migration for the now-closed local CTP route, not equivalent public Store integration coverage.

Both results are local test evidence only. They do not establish AccountActor authority, provider trust, SDK/native behavior, a CTP execution route, G6-S/G7-S, or live readiness.

## Credential-safety patch

Frozen input: `D:\temp\credential-safety-r2b-migration-20260927\credential-safety-migration.patch`, SHA-256 `CCE753315DC4B23F1BAF6C644962B5AE479AF6377255E067512C9B6A976A7657`.

Independent isolated replay used base commit `ad2c142b9a8b42cede85886528c681abdfcb8096`, then the exact r2b source overlay, then the test-only patch. Before the r2b overlay, the file passed 7/7. After the overlay but before migration, 4 passed and 3 failed:

- `tests/unit/stores/test_credential_safety.py::test_repr_does_not_leak_password`
- `tests/unit/stores/test_credential_safety.py::test_str_does_not_leak_password`
- `tests/unit/stores/test_credential_safety.py::test_repr_is_informative`

After migration the focused three passed and the complete file passed 8/8. The masked-account/non-leak expectations remain; a trap credential mapping and trap client class verify CTP construction fails before their inspection/use. Independent candidate guarded run passed 8/8 and recorded zero forbidden imports or external network calls. One initial guard attempt ran from the wrong working directory and therefore tested the base checkout; it is retained but excluded. The correctly rooted candidate guard run is the result above.

## Projection-bridge patch

Frozen input: `D:\temp\iteration41-ctp-managed-projection-bridge-store-gate-migration-final-20260927\evidence\projection-bridge-store-gate-migration.patch`, SHA-256 `CED276AFC091ECEDE150EEAC956D3EBD87E0975DB54443FFB2268A34437119B1`.

The patch changes only `tests/unit/stores/test_ctp_managed_projection_bridge.py`. Input test SHA-256 is `08095B558369F1C9674F10F0994E1344FC91A5A2BC6AED8A9ACEEC98872832BB`; migrated test SHA-256 is `885D6B2E2163939057AD4F1BD50F5337885414141ECD14335560EF1B2A28E1CC`. The r2b candidate source identities used for the replay were Store `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`, AccountActorPort `2E4B04D00C45BA9C6524C5AD0364273E6ECC1A1F653F595D21C3891BE2644EE3`, managed execution `1C31F89412E8E1177EB2E27389C62B50E074361EF808098846C06704F18440C5`, and projection bridge `BB1C81335505B8F59EDAEDCED6424A4BDD7671BDEB59BA9F34C16FFC56FEEBD4`.

Independent reverse-patch baseline reproduced **18 failed / 14 passed**; exact nodeids and traces are in `projection-bridge/before-independent.log` and JUnit. Forward migrated focus passed **32/32** in the candidate. A correctly guarded rerun also passed 32/32 with zero forbidden import/network events. The single warning was the existing Quandl deprecation warning. An initial guard configuration rejected Windows asyncio's local loopback socketpair and caused two queue tests to fail; that instrumentation-only run is preserved but superseded by the loopback-limited guard rerun.

Review of the migrated assertions:

- The two former Store positive tests now call `CtpManagedExecutionProjectionAdapter` directly. Projection PENDING/UNKNOWN values, receipt/intent linkage, replay idempotency, ambiguous-handoff no-retry, and freeze behavior remain asserted. This no longer tests the `BtApiStore.submit_order/cancel_order` wiring or the former Store API no-legacy-callback counters.
- Queue tests still assert durable receipt before publication, invisibility/no dispatch on receipt failure, no generic sender fallback, durable local rejection, and fail-closed binding mismatch with unchanged queue/callback counters. They use an OKX NON_CTP Store and private queue methods with a sentinel that is explicitly not an adapter/actor.
- Both raw managed CTP cancel parameter cases now assert constructor rejection before client creation, with recovery armed false and true. They do not execute a positive CTP cancel path or exercise the old raw enqueue-cancel method's worker/heap/native-call counters.
- The typed cancel identity/separation/validation tests remain in the file. No fake AccountActor is treated as authority.

The patch is safe as a migration away from an unavailable CTP Store path and retains local adapter/queue primitive contracts. It does narrow public Store integration coverage; a future route implementation must add separate public Store-to-actor integration tests before claiming that coverage.

## Isolation and limitations

All candidate replays and guards were under `D:\temp\guardianqa-credential-safety-r2b-independent-20260927`. The shared checkout was not changed. No private configuration, credentials, SDK/native import, provider, external network, order, or production route was used. Windows loopback socketpair was allowed only to keep pytest's Proactor loop operational; external socket/DNS use remained guarded.
