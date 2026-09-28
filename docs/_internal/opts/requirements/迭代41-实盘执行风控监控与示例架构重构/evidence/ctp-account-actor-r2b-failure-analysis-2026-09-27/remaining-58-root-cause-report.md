# R2b integrated JUnit: independent remaining-58 root-cause analysis

**Scope:** read-only analysis of `D:\temp\iteration41-r2b-main-unit-store-runtime.xml` against the r2b AccountActorPort candidate source. No pytest rerun, production edit, test edit, provider import, network, private config, or account activity was performed. This report is intentionally separate from the repository.

## Frozen inputs and counts

- JUnit SHA-256: `6500223FE55136907A178996E3F0D5BE6DA71DD758B501BFEB9E232949B0EFFE`.
- JUnit actual counts: 2,706 cases, 258 failures, 0 errors, 45 skipped.
- 200 failures are concentrated in `tests.unit.stores.test_btapistore_iteration22`; the requested residual slice is the other 58 cases.
- Those 58 comprise: 49 `external account actor unavailable`, 6 `store route ambiguous`, and 3 `store provider unsupported`. All are constructor-time failures; no downstream test assertion was reached.
- Candidate Store SHA-256: `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`.
- Candidate ActorPort SHA-256: `2E4B04D00C45BA9C6524C5AD0364273E6ECC1A1F653F595D21C3891BE2644EE3`.
- Local I22 test SHA-256: `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D`.
- The candidate itself describes status as `AUTHOR_CANDIDATE / NO_WRITE`; source evidence is under `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b\evidence\`.

## Root-cause clusters

| Residual cases | Classification | Evidence and interpretation |
|---:|---|---|
| 49 | Expected CTP fail-close; tests need migration or a real future Actor contract | Candidate `backtrader/stores/btapistore.py:3689-3705` rejects explicit CTP selectors and explicit CTP route maps before Store initialization. `ctp_account_actor_port.py:442-460` returns only for classified NON_CTP, rejects unsupported/ambiguous selectors, and unconditionally raises `external_account_actor_unavailable` for CTP; injected fake ports/contexts/ledgers are explicitly not authority. Affected tests: projection bridge 18; `test_btapistore` 8 CTP/auth/env-switch tests; normalized 7; execution evidence 7; entry-approval arm 5; credential safety 3; SA replay runtime 1. Positive Store/SDK/arm/normalization behavior is not currently reachable without a code-owned external Actor. Do not fix by accepting the local test doubles. |
| 5 | Incomplete generic route facts; test-fixture migration now, possible compatibility tightening for opaque/custom callers | Three `test_btapistore` feed/broker-construction checks and two normalized cache/callback checks use `provider="btapi"` (or the arbitrary test alias `outer`) with no explicit route map. The candidate classifier intentionally treats generic `btapi` without an explicit known venue as AMBIGUOUS (`ctp_account_actor_port.py:397-418`) and will not infer routing from an injected API object's attributes. If the test is for feed/broker binding or cache behavior, give it a known non-CTP provider or an explicit exact `config.exchange_kwargs`/`symbol_routes` route. Do not relax opaque-client classification. These failures alone do not establish a production bug for a complete declared route; callers relying on hidden API-object routing do face a compatibility break that needs an explicit registration design. |
| 1 | Must remain fail-closed; test had hidden CTP route | `test_supplied_sdk_configuration_is_preserved_when_store_does_not_override_it` creates a fake SDK with `exchange_kwargs={CTP: {}}` but passes no explicit `config`; the constructor deliberately does not inspect opaque `api.exchange_kwargs`, so classification is AMBIGUOUS. The correct test should supply the route facts explicitly and then assert CTP refusal, or split a non-CTP configuration-preservation case. Do not make this case pass by reading the injected object's hidden config. |
| 3 | Expected unsupported-provider rejection; assertion timing migration | `futu`, `oanda`, and `vc` are in `_UNSUPPORTED_PROVIDERS`; `require_account_actor_before_local_client` now rejects at construction (`store_provider_unsupported`) before later `start()`/provider errors. Update these to assert the early rejection. This is not an enabled non-CTP route. |

### The notable local-runtime collision

`tests/unit/runtime/test_iteration41_sa_ctp_replay_runtime.py:184` expects the offline 013_3 fixture to run. But `examples/013_3_sa_midfreq_simnow/run.py:3220-3230` constructs `BtApiStore(provider="ctp")` and `BtApiBroker(provider="ctp")` for `ReplayClient`. The candidate's explicit-provider guard therefore blocks this local fixture even though the fixture is intended to make no provider call. This is a real replay-integration regression in the current composition, not a reason to exempt `provider="ctp"` or to treat it as an Actor route. The safe repair is to move this synthetic replay onto an explicitly local-only Store/Broker fixture with no CTP provider identity or provider-capable dispatch path, while keeping every CTP Store constructor fail-closed. It needs a focused no-network/no-write contract; it cannot be repaired by adding a CTP gate exception.

## Minimal safe repair plan (no skip/xfail or route bypass)

1. **Make test route facts explicit for the five generic non-CTP cases.** Use a known non-CTP selector or exact route map only in the tests that are not testing routing. Add/retain a separate assertion that absent/opaque/unknown route facts reject. For the hidden-CTP SDK case, pass the explicit CTP route and assert `external account actor unavailable`; never infer selector safety from the SDK object.
2. **Migrate the 49 CTP constructor-dependent tests and local replay separately.** For tests whose contract is a pure validator, extract/call that validator without constructing a CTP Store; where behavior itself requires Store session/arm/submit/cancel, replace the old local-positive expectation with a direct fail-closed constructor contract until a separately reviewed external Actor exists. For 013_3, create a local-only replay composition rather than a CTP Store exemption. Keep fake CTP actors non-authorizing and do not represent a local fake as real Actor acceptance.

The 3 unsupported-provider cases should be migrated to constructor-time rejection assertions alongside item 1. There is no safe production-code relaxation indicated by this JUnit.

## Evidence boundaries

The 58-error pattern proves early gate coverage, not correctness of the blocked code below the constructor and not Actor acceptance. The XML contains no downstream traces for these cases because construction failed first. The r2b candidate's own reports are author/candidate evidence only; this report does not convert those into independent acceptance. No CTP route, actor authority, provider, or write capability is enabled.

## Trigger sites in the main-tree test suite

- The candidate admission points are `backtrader/stores/btapistore.py:3689-3705` (explicit CTP and nested CTP rejection) and `:3784-3786` (central classifier/gate), with unconditional CTP denial in `backtrader/stores/ctp_account_actor_port.py:442-460`.
- CTP Store fixtures: projection bridge `_store` at `tests/unit/stores/test_ctp_managed_projection_bridge.py:261-276`; execution-evidence `make_store` at `tests/unit/stores/test_btapistore_execution_evidence.py:50-64`; entry-arm tests start at `tests/unit/stores/test_btapistore_entry_approval_arm.py:73` and import `_authorized_store` from I22 at `tests/unit/stores/test_btapistore_iteration22.py:733`; credential construction is `tests/unit/stores/test_credential_safety.py:19-32`.
- The three generic feed/broker cases are `tests/unit/stores/test_btapistore.py:1690`, `:1705`, `:1722`. The two generic normalized cases are `tests/unit/stores/test_btapistore_normalized.py:371-405`. The intentionally hidden CTP fake-SDK case is `:1398-1405`. The unsupported-provider cases are `tests/unit/stores/test_btapistore.py:3654-3663`.
- The offline replay test is `tests/unit/runtime/test_iteration41_sa_ctp_replay_runtime.py:184`; its local `ReplayClient` is passed to a CTP Store at `examples/013_3_sa_midfreq_simnow/run.py:3220-3230`.
