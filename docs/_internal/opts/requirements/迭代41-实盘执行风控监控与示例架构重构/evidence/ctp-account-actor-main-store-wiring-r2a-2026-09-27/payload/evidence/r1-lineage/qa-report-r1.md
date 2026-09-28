# Independent-scope author QA: Store wiring candidate r1

## Verdict

`AUTHOR_CANDIDATE / NO_WRITE`. The narrow offline route and adapter-only focus passes. The candidate is not merge-ready by this result alone: the exact prior 30-test Store regression set is 9 passed / 21 failed against r1, while its exact-base run was 30/30. The 21 failures are existing tests of direct CTP managed local-SDK dispatch, which this candidate now deliberately blocks before local-client creation. This is a material compatibility/policy delta that needs independent review; do not remove the CTP gate merely to green that suite. Candidate-only and non-CTP adapter checks are separately reported below.

No CTP/provider, network, credential, native SDK, broker, gateway, registered runtime route, or main production source was used or enabled. This does not establish real AccountActor authority, F14, G1, G5, shared-session opening, or live acceptance.

## Exact inputs and payload identity

- Main source input: `input-sources/btapistore.py`, 780,123 bytes, SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`.
- The candidate patch's three targets are the Store above, new `backtrader/stores/ctp_account_actor_port.py`, and new boundary test `tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py`. Their candidate SHA-256 values are listed in `candidate-manifest.json`.
- Frozen AccountActorPort r4 manifest SHA-256: `8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8`.
- Frozen r4 actor-port module SHA-256: `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48`.
- Candidate actor-port module SHA-256: `19f5935bc6aabcde178f60f62619757b01fa51b99ff5389120a8404e00e70372`. Its sole text delta from frozen r4 removes the blanket `route.api`/`route.api_cls` ambiguity check in `classify_store_route`, so exact known non-CTP routes can preserve historical API injection. The separate gate still refuses injected local clients on CTP routes before client construction. DTOs, receipt contract, and actor operations remain copied from the local r4 contract.
- The existing upstream AST/input checks are retained as `evidence/upstream-r4-verification.log` and script `evidence/verify_upstream_contracts.py`; they establish local source correspondence only, not authority.

## r1 behavior and probes

1. Exact known non-CTP provider plus matching venue and a raw API sentinel is accepted without reading sentinel properties.
2. Unknown provider/API-class trap and CTP/API trap reject without property access or local client construction.
3. Nested CTP, gateway route, `BT_STORE_PROVIDER`/`BT_GATEWAY_EXCHANGE_TYPE` conflicts reject before SDK/forwarding creation. Environment or route mutation is reclassified at the dispatch boundary.
4. Bare `btapi` remains ambiguous. The adapter-only carveout requires the exact narrow conditions in `README.md`; it discards the opaque API, leaves `_api`/`_api_cls` unset, cannot start, and supplies only a guarded legacy callback that raises before any local dispatch.
5. Adapter-only submit/cancel revalidate before and after the supplied adapter call; a CTP route mutation rejects before adapter invocation. A projection is returned only when the adapter returns one. No adapter error falls through to a local SDK path.
6. The fake AccountActor receipt remains a per-command local observation. It does not authenticate the actor, verify current authority, or enable Store start/shared read callbacks.

## Tests and tools

- Candidate route boundary test plus copied default live-dispatch guard: **14 passed**, one existing Quandl deprecation warning. Raw output: `evidence/r1-candidate-focus.txt`.
- Candidate boundary test, existing managed-execution adapter tests, and live-dispatch guard: **21 passed**, one existing Quandl deprecation warning. Raw output: `evidence/r1-focused-tests.txt`.
- Ruff against candidate Store, actor-port module, candidate test, and copied managed-execution adapter test: **passed** (`evidence/r1-ruff.txt`).
- `py_compile` for the same four files: **passed** (`evidence/r1-pycompile.txt`).
- Patch replay from the exact frozen Store input with `core.autocrlf=false`: all three output files must hash byte-for-byte to candidate targets. The replay also records `core.autocrlf=true`: Store remains byte-exact, while newly added LF files are converted by Git to CRLF, so use the explicit false override for a byte-exact replay. Patch SHA-256 is recorded in the manifest.
- Exact old Store regression set: base `evidence/r0-lineage/main-related-tests-r0.log` reports **30 passed**. Candidate replay of the same three test files reports **9 passed, 21 failed** in `evidence/r1-legacy-ctp-compatibility-exclusions.txt`; failures are direct CTP-local-SDK adapter expectations reaching the candidate's `external account actor unavailable` gate. The gate is intentional, but this is not a green compatibility result.

## Scope and blockers

- Explicit non-CTP raw-client compatibility depends on the supplied route being a known exact provider/venue combination. Unknown, default generic, mixed selector, CTP, and unsupported gateway cases remain closed.
- The adapter-only carveout invokes a caller-supplied managed adapter. This offline candidate does not authenticate that adapter or make its own side effects authoritative; any true external actor must provide a separately reviewed signed/current authorization and durable account-wide fence. The legacy local dispatch callback itself is blocked.
- The r4 local fake ledger and unkeyed digest are not external idempotency or a cross-host fence. There is no accepted session snapshot, current epoch query, callback/read-feed contract, or broker/gateway service.
- The old direct CTP local-SDK managed test failures are retained, not suppressed. Do not merge or enable runtime routing without review of this compatibility/policy break and production authority.
