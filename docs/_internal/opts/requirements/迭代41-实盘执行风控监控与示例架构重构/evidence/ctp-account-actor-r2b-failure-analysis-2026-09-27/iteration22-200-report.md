# R2b main Store runtime XML / Iteration22 failure analysis

**Disposition:** the 200 failures in `tests/unit/stores/test_btapistore_iteration22.py` are one intentional CTP admission-gate outcome, not 200 separate functional defects. I found **zero ordinary non-CTP compatibility failures within those 200**. This does not classify the XML's other 58 failures. Analysis was read-only: parsed the supplied JUnit XML and the complete test file with Python XML/AST inspection; tests were not rerun and repository source/tests were not edited.

## Frozen inputs and scope

- JUnit: `D:\temp\iteration41-r2b-main-unit-store-runtime.xml`, SHA-256 `6500223FE55136907A178996E3F0D5BE6DA71DD758B501BFEB9E232949B0EFFE`.
- Complete test file: `D:\source_code\backtrader\tests\unit\stores\test_btapistore_iteration22.py` (4,534 lines), SHA-256 `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`.
- XML suite result: 2,706 tests, 258 failures, 0 errors, 45 skipped; target class `tests.unit.stores.test_btapistore_iteration22` accounts for 200 failures across 132 test functions.
- R2b constructor source inspected for cause: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b\backtrader\stores\btapistore.py`, SHA-256 `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`. The XML itself does not record the imported source root/hash; this source comparison explains the matching failure message but does not prove the test process loaded this exact copy.

## Root cause and clusters

All 200 target cases have exactly the same JUnit failure message:

`backtrader.stores.btapistore.BtApiStoreError: external account actor unavailable`

The exception is raised while creating `BtApiStore`, before the test body can query, assert, arm, recover, or call an API. The R2b candidate has two relevant pre-client gates: explicit `provider in {"ctp", "ctp_gateway"}` raises at `btapistore.py:3688-3690`; a CTP route discovered from a frozen nested route snapshot raises at `:3692-3705`. The route classifier treats direct CTP evidence as dominant and recognizes CTP in configured venue keys (`ctp_account_actor_port.py:339-365`, `:390-425`, `:512-514`).

AST traversal of each failed test and its in-file helper constructors classifies all 200 routes as CTP:

- **65/200** explicitly select `provider="ctp_gateway"` (including paths through `_frozen_quote_reference_store`).
- **135/200** use `provider="btapi"` with the CTP exchange selector `CTP___FUTURE`, supplied via fixture/helper `exchange_kwargs` or an equivalent local SDK fixture. `ManagedBtApiClient.exchange_kwargs` is set to `{"CTP___FUTURE": ...}` at test line 217; `_authorized_store` (lines 733-759), `_dce_bundle_store` (969-980), and `_bundle_authorized_store` (4013-4027) pass it into `make_store`.

Failure intent clusters (counts are failed parameterized cases; these are not separate exception causes):

| Cases | Intent represented by the tests |
|---:|---|
| 158 | Query/preflight, scope, quote, settlement and evidence validation |
| 38 | Authorization, SDK arm, recovery and lifecycle behavior |
| 4 | Managed/legacy order-reference and cancel-request identity |

The target module has no failed case whose resolved `make_store` path is a non-CTP provider/selector. Thus the 200 are expected consequences of closing Store-local CTP dispatch while an accepted external account actor is unavailable. They do **not** establish that the 158 evidence rules or 38 lifecycle rules are correct or still exercised; construction stops first.

The XML contains **58 additional failures outside the target module** (projection bridge 18; basic Store 14; normalized Store 10; execution evidence 7; arm 5; credential safety 3; runtime 1). They are outside this file-specific classification. In particular, generic `store route ambiguous` cases require their own fixture and exact-base comparison before calling them ordinary non-CTP compatibility regressions; they must not be folded into the 200 CTP result.

## Test migration without skip/xfail or restoring direct writes

1. **Keep the Store boundary red/green contract.** Retain explicit CTP, nested CTP, CTP gateway, environment/forwarding mutation and ambiguous `btapi` cases that assert rejection before reading caller API attributes, credentials, importing the SDK, or invoking a client. Add/assert zero fake-client calls and preserve the default route as closed. Do not change these tests to let a fake local CTP SDK authorize construction.
2. **Move the 158 data-contract cases below the Store admission boundary.** Extract pure normalization, typed query-completion checks, alias/scope matching, quote freshness, settlement evidence and request-ID validation into pure functions or a query-evidence service that accepts typed snapshots plus an inert read-only query-port protocol. Keep the parameterized good/bad matrices intact there. Do not instantiate `BtApiStore` with `provider="ctp_gateway"` or `btapi + CTP___FUTURE` to reach them.
3. **Test the 38 authorization/recovery/lifecycle cases at the Actor contract.** Exercise a separately isolated fake actor/worker protocol for receipt, arm/revoke, recovery and pending-command semantics. The Store must still reject local CTP construction and prove the fake SDK was untouched. Pure proof-shape checks can remain separate and explicitly non-authorizing. A caller-provided test port, receipt, ledger or fake SDK must never become runtime authority.
4. **Move the four request-identity cases to typed Actor command tests.** Assert scope/OrderRef/ActionRef binding and fail-closed receipts at the typed handoff seam, with no Store-local native write fallback. Keep the Store boundary rejection test independently.
5. **Protect ordinary non-CTP compatibility separately.** Use exact supported non-CTP provider/backend selectors and non-CTP route maps in positive compatibility tests. A generic provider with a CTP exchange key is CTP and must not be relabeled to make tests pass. Compare the unrelated ambiguous-route cases against an exact-base control before categorizing them.

No tests should be skipped or xfailed: preserve their value by moving pure evidence assertions and actor protocol assertions to the seams they actually specify, while the Store constructor remains fail-closed.

## Reproducibility artifacts

`analysis-summary.json` binds the XML/test/candidate hashes and contains all 200 target case names, constructor paths, route classifications, semantic groups and suite counters. `summary.txt` preserves the failure names/messages, and the analysis scripts are retained in this directory. No tests were executed by this analysis.
