# AC41-63 CTP direct-writer fallback — r2 rev2

Status: isolated fail-closed patch candidate; NO_WRITE / LIVE_NO_GO. Nothing was applied to the shared main tree.

## Scope and authority

Raw CTP insert/action fallbacks were reachable from direct Python wrapper methods. The insert sink is prior reviewed candidate i41-writer-fbe05d71d70ed65a9838 at backtrader/stores/btapistore.py:1935; the corresponding raw action is at :1943-1949. The new slice includes i41-writer-5c0e163572ea9a5a8fe4 for CtpClientWrapper.create_order, an alias/reachable route to the same insert helper at :2608. The first two controlled slices cover 22 of 389 inventory candidates; 367 remain unexamined. Every static inventory disposition remains REVIEW_REQUIRED / NOT_AVAILABLE.

New slice candidate IDs: i41-writer-5c76e7bbaaf9eaf8fafb, i41-writer-6df08432c5aec510239a, i41-writer-921a46a1979e1076c023, i41-writer-5c0e163572ea9a5a8fe4, i41-writer-bf56d1ec1d8f9b98d4fd, i41-writer-4817d2f7cc8d1a6f137d, i41-writer-9d6b74c674a29822eabd, i41-writer-9272fb151289cdcd07a9, i41-writer-789fa193cd6ecb32323e, i41-writer-4e6bdd63429f38994dff, i41-writer-4b56f8cf4860c5fec787, i41-writer-e7d7f270d49ed8f4d8aa.
Prior reviewed IDs remain in R1-selected-candidates.json.

The source patch removes raw ReqOrderInsert / ReqOrderAction fallbacks. Missing capability is rejected before typed SDK attribute access; missing/non-callable typed methods reject before .api access. It does not establish write authorization: _execution_gate_capability remains mutable same-process private state, and injected capability plus typed method can produce fake calls. There is no trusted per-action grant or external Actor.

## Frozen source facts

Source patch SHA-256: 2182f12a729afc39dfa6ba4c23bb4accd557f4dcda3138ef238cb039e52de291.
Exact base Store SHA-256: dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826.
Patched Store target SHA-256: 05268b4953a20fa0699639f7e05ee354a4bcafc4b47915dd4ba352b26276e0d9.
The exact mixed-EOL byte replacement has a hash-pinned applicator plus a standard Git patch validated with core.autocrlf=false. The patch preserves mixed line endings and applied to an isolated clone with target SHA equality. The 1025-file before/after manifest shows only backtrader/stores/btapistore.py changed.

## Final test migration

TEST-MIGRATION.diff SHA-256: 43217ec36a412d68e91133ff9c2b640a47dc0ae49c1eac64abc0cb0b3bc39d7b.
It preserves the submit positive test nodeid and changes that fake to require typed submit plus a non-null capability. It adds a raw-only submit rejection test with typed descriptor and .api traps. It also adds a parameterized cancellation negative test with two cases:
- missing capability: typed action descriptor, .api, and raw ReqOrderAction all have zero reads/calls;
- capability present but typed method absent: .api and raw ReqOrderAction remain zero.

The migration patch modifies only tests/unit/stores/test_btapistore.py. Read-only git apply --check passed against the current main test source; no patch was applied. Source patch current-main checks were already passed against the same exact Store base.

## Verification

Eight boundary probes against the exact byte-patched methods passed: for insert and action, absent capability rejects before trap-attribute access; missing and non-callable typed methods reject; typed fake with capability calls only the typed fake. Every case recorded zero .api property access and zero raw Req* calls.

The final focused JUnit has four selectors: baseline source with migration has 1 pass / 3 expected gate failures; patched source with migration has 4 passes. The two full relevant test files with the same migration have baseline 335 pass / 6 failures and patched 338 pass / 3 failures. The only three patched failures are shared harness/fixture limitations:
- tests/unit/stores/test_btapistore.py::test_create_ctp_wrapper_patches_missing_spi_callbacks (inert shim lacks OnRspQryInvestorPositionDetail);
- tests/unit/stores/test_btapistore.py::test_ctp_wrapper_fetch_open_orders_converts_ctp_rows (real optional CTP order-container import is blocked);
- tests/unit/stores/test_btapistore_iteration22.py::test_managed_order_request_carries_strategy_cycle_and_recovery_role (fixture lacks persisted runtime_order_id binding).

Baseline-only failures additionally include the submit raw-only descriptor trap and both cancellation cases. JUnit documents with exact nodeids are in R2-REV2-RESULTS.json. All runs used inert CTP fakes and SDK import guards; no real SDK, network, native code, provider session, or order was used.

## Application order and supersession

Apply PATCH-GIT.diff first, then TEST-MIGRATION.diff, and rerun the two listed files. r2 rev2 supersedes the initial r2 package only for the test migration and related results. The initial r2 ZIP remains preserved unchanged. r1 also remains preserved unchanged with its NEEDS_REVISION QA state; r2 is the superseding source patch artifact. Replay and review after r2b/r2c wiring or any source change. Parent independent QA and broader regression are still required; do not infer merge readiness or live authorization.
