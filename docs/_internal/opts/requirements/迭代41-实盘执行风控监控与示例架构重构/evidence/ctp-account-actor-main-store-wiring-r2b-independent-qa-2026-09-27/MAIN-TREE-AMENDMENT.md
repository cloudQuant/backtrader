# R2b main-tree regression amendment

**Status: `NOT_READY_FOR_MAIN_MERGE`. This amendment supersedes the earlier `SAFE_TO_MERGE_FAIL_CLOSED` recommendation in this directory.**

**Hash correction (2026-09-27):** The linked main-tree apply/revert report has the same path and revised content. Its current verified SHA-256 is `EB262AE8FB391DE5933A536115D99C0739DAD7DFC06B4A99B600C43A6E019DD4`; the earlier value `DD56C80FF819E7D7B80B939F4F28021C66EBFC0B3055BAD3E71822F288772997` is stale. The first amendment ZIP/index are retained as main-tree-amendment-r1-historical.raw.zip / main-tree-amendment-r1-index.json; the current archive is rebuilt below. The original report remains an accurate record of its isolated 724-payload candidate subset, but that subset did not represent the complete main-tree Store/Runtime suite.

## Main-tree evidence

The exact PowerShell invocation was:

```powershell
python -m pytest -p no:asyncio tests/unit/stores tests/unit/runtime -q --tb=no --junitxml='D:\temp\iteration41-r2b-main-unit-store-runtime.xml' *> 'D:\temp\iteration41-r2b-main-unit-store-runtime.txt'
```

On the patched main tree it collected 2,706 cases: **258 failed, 2,403 passed, 43 skipped, 2 xfailed**, with one existing pytest config warning, in 81.95s. After the candidate patch was reversed, the exact same command collected 2,681 cases and reported **2,636 passed, 43 skipped, 2 xfailed**, one warning, in 90.02s. The restored Store source hash is `DBA2989252DB76FE010FBEE7CAACCDDBA34A9B951E3702724156482B67FAE826`.

The JUnit identity comparison is independently reproduced in `main-tree-failure-groups.json`: 2,706 patched nodes vs 2,681 reverted nodes; 46 candidate nodes added and 21 old nodes replaced; all 46 added nodes passed, while every one of the 258 failures belongs to a pre-existing node ID. The canonical main-tree report and original JUnit/output are linked below; this amendment does not duplicate the large raw JUnit files.

## First failure per file

The exact failure distribution and first JUnit failure message per file are recorded in `main-tree-failure-groups.json`. The run used `--tb=no`, so the retained JUnit provides exception messages rather than full tracebacks.

| File | Failed | First failure | Attribution |
|---|---:|---|---|
| `test_btapistore_iteration22.py` | 200 | `test_ctp_preflight_preserves_all_typed_completion_evidence` — `external account actor unavailable` | Candidate CTP constructor gate preempts existing local CTP preflight/query/recovery/arming cases. This is fail-closed behavior, but it blocks existing offline/read-only behavior and fails the acceptance suite. |
| `test_ctp_managed_projection_bridge.py` | 18 | `test_store_uses_outbox_projection_for_submit_and_cancel_without_legacy_fallback` — `external account actor unavailable` | CTP fake outbox/projection tests cannot reach their behavior because the Store is rejected at construction. |
| `test_btapistore.py` | 14 | `test_ctp_store_emits_auth_login_success_from_session_state` — `external account actor unavailable` | Mixed: 8 CTP/env cases are blocked by the CTP gate; 3 generic `btapi`/`outer` Store factory cases fail with `store route ambiguous`; 3 `futu`/`oanda`/`vc` placeholder cases now fail with `store provider unsupported` instead of the expected unsupported-provider contract. |
| `test_btapistore_normalized.py` | 10 | `test_venue_account_cache_uses_completion_time_and_force_reads` — `store route ambiguous` | Mixed: this first test and the public stop-callback test create generic `BtApiStore(provider="btapi")` without a CTP route and are rejected; 8 other failures use CTP or an SDK configuration containing CTP and are preempted by the Actor gate. |
| `test_btapistore_execution_evidence.py` | 7 | `test_ctp_arm_managed_summary_requires_all_arm_evidence` — `external account actor unavailable` | Constructor rejection preempts CTP managed-arm evidence checks. |
| `test_btapistore_entry_approval_arm.py` | 5 | `test_store_arms_sdk_from_redeemed_entry_approval_capability` — `external account actor unavailable` | Constructor rejection preempts the fake CTP approval/budget-capability tests. |
| `test_credential_safety.py` | 3 | `test_repr_does_not_leak_password` — `external account actor unavailable` | The CTP Store is rejected before `repr`/`str` masking is tested. No leak was observed, but the existing redaction test did not pass or run to its assertion. |
| `test_iteration41_sa_ctp_replay_runtime.py` | 1 | `test_real_replay_has_no_network_or_provider_writes[013_3]` — `external account actor unavailable` | The gate blocks the registered no-write 013_3 simulation/replay test before it can verify its offline run. |

At least 8 failures are clearly unrelated-provider compatibility breakage: five generic `btapi`/`outer` construction/helper tests now reject an ambiguous route, and three placeholder-provider cases change the expected exception. The `013_3` failure is a separate scope regression for an existing no-write replay. The remaining failures are intentional under the candidate's broad no-Actor CTP gate, but they still invalidate merging under the current main-tree acceptance contract until their read-only/replay behavior and explicit migration policy are reconciled.

## Why the prior 55-case run is insufficient

The isolated candidate snapshot contains only its manifest-selected 724 source payloads and the tests copied into that candidate; `tests/unit/stores` plus `tests/unit/runtime` there enumerated only 55 cases. It is a valid candidate-local fail-close check, not the complete main-tree suite. It therefore missed existing Store/runtime contracts and the generic-route failures above. Do not substitute the 55-case result for the 2,706-case main-tree result.

The prior 8/13 → 5/16 migration-table reclassification remains accurate but is not a remedy for these failures. The three moved cases concern the SDK OrderRef as second authority and two `real_queue_fails_before_second_orderref_allocator` parameter cases. R2b now rejects construction before a local fake allocator can execute, so those are future authenticated Actor/shared-ledger positive requirements. That classification does not justify blocking non-CTP APIs or the registered zero-write replay path.

## Decision

Do **not** merge r2b into the main tree as-is. Preserve its no-write/fail-closed intent. Resolve the generic `btapi` route and placeholder-provider compatibility failures, preserve the no-write 013_3 route, and explicitly decide which CTP local fake/read-only tests become refusal contracts versus which supported operations remain available without an external Actor. Do not make the suite green by skipping, xfail-ing, or deleting these existing tests, and do not restore a direct CTP write route to do so. Then rerun the full Store/Runtime suite and dependent integration/strategy gates.

No production code was changed by this amendment. The main-tree patch was already reverted by the root task; this QA only reads the retained JUnit/output and candidate evidence.

## Source evidence

- [Main-tree apply/revert report](../ctp-account-actor-r2b-main-integration-2026-09-27/REPORT.md) SHA-256 `EB262AE8FB391DE5933A536115D99C0739DAD7DFC06B4A99B600C43A6E019DD4`.
- Patched JUnit SHA-256 `6500223FE55136907A178996E3F0D5BE6DA71DD758B501BFEB9E232949B0EFFE`; patched output SHA-256 `08871BE79BE93FC5E77509070EB9E64CAA28A62650DF4591D0B5C355B02B8761`.
- Reverted JUnit SHA-256 `35D8D144E8788BA0314CAA4601077209F5F7EB55FB15CD0C49F3DE33595076FF`; reverted output SHA-256 `FBEF36C0AA126DAE38D13BAB7CF0B67301FDB235E8374A044D93DBEBA15BBADE`.
- The original isolated candidate QA report/ZIP and its hashes are retained unchanged in this directory; its merge recommendation is superseded by this amendment.

