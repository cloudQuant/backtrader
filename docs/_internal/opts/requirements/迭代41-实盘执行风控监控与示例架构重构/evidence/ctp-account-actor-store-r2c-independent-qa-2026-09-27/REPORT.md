# BtApiStore AccountActorPort r2c independent QA

**Disposition: `LOCAL_SAFETY_INCREMENT_ONLY / MAIN_MERGE_REJECTED`.**

This review covers the r2c Store route-safety increment replayed on top of the exact r2b main-base patch in an isolated copy. It does not approve merging r2b+r2c into the main worktree. The Store/Runtime broad suite remains red: the reviewed run has 258 failures, and its failed node-ID set is exactly the same 258 IDs as the earlier r2b patched-main run. The original main-tree Store/Runtime result after reverting r2b remains the relevant green baseline; see the existing r2b main integration evidence linked from the evidence index.

## Source and patch identity

- Isolated source copy: `D:\temp\iteration41-r2c-independent-qa-20260927`; copy/exclusion details are in `QA-COPY-MANIFEST.json`.
- Exact main Store base SHA-256: `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`. The live main-tree `backtrader/stores/btapistore.py` was rechecked at that exact hash after QA; no main source was edited.
- r2b base patch SHA-256: `1A16AADB94EDB99924553D6472BF72DCB02BD04C7F994276816D91991A729F37`.
- r2c additive patch SHA-256: `4EEAB367C80D1D4B5545892DB56376DCB170557DD3098BC4787A5AC5BD8B14FC`.
- Both patches replayed in the isolated copy. The additional clean replay needed `--ignore-space-change` because its checkout uses CRLF; all five changed files match the QA candidate after CRLF→LF normalization. Raw byte hashes differ only because of line endings. The replay log and per-file comparison are included.
- r2c changes the Store, its route-candidate tests, and the Store unit tests. The additive behavior under review wraps the exposed SDK API in a Store-bound route-checking view and rechecks public gateway-wrapper calls and worker dispatch after route mutation.

## Test evidence

All tests ran from the isolated copy with the compatible Python 3.11.5 environment, pytest 8.2.2, plugin autoload disabled, asyncio plugin disabled, bytecode writes disabled, `BT_API_PY_LIGHT_IMPORT=1`, source-only package roots from the included map, and the per-worker import/network/private-config guard. `pip check` reported no broken requirements. The fixture root was owned by this QA run.

| Scope | Result |
|---|---:|
| r2c route candidate and migrated gateway alias focus | **44 passed**, 1 existing pytest configuration warning |
| query-evidence focus | **7 passed**, 1 existing pytest configuration warning |
| `tests/unit/stores tests/unit/runtime` | **2,460 passed, 258 failed, 28 skipped, 2 xfailed**, 1 existing pytest configuration warning; 227.88 s |

The broad run's JUnit represents xfails as skipped cases, so its XML has 30 skipped records; the pytest console summary separates 28 skips and 2 xfails. The author r2c run had 258 failed, 2,425 passed, 43 skipped, and 2 xfailed. The earlier r2b patched-main run had 258 failed, 2,403 passed, 43 skipped, and 2 xfailed.

### Failure identity comparison

JUnit identities were compared using `(classname, name)` across the exact r2b main JUnit and the reviewed r2c broad JUnit. Result: 258 failures in each, 258 in the intersection, 0 r2b-only IDs, and 0 reviewed-r2c-only IDs. The packet includes the comparison script, JSON result, and all 258 exact failed node IDs. This is evidence that the r2c increment did not add a new failing node in this patched candidate run; it does not make the 258 failures acceptable or establish merge readiness.

The independent source-only lane executed 22 optional tests which the author run module-skipped because its optional package roots were unavailable: 15 `test_ctp_managed_action_scope_resolver` cases and 7 `test_ctp_simulation_query_evidence` cases. All 22 passed. Relative to the author JUnit, those 22 test nodes replace two module-level skip placeholders, for 20 more total case records. The seven query-evidence cases also passed in a separate focused invocation.

An earlier run with a mismatched/unreviewed source mapping produced 293 failures. It is preserved as a diagnostic only and is superseded by the corrected reviewed-source run, which removed the 35 environment/source-mapping-only failures and exactly matches the 258 r2b baseline failures.

## Runtime/source guards and limitation

The included source-origin check resolves all 11 source-only package roots to their explicit mapped origins; it reports `native_ctp_modules_loaded=0`. The per-worker guard log records 26 initialized workers, 151 source-import events, 2 blocked native-import attempts, 36 synthetic-origin allowances, and 23 synthetic-config allowances under the owned pytest basetemp. No non-loopback network access or protected-config access was observed; the protected runtime `config.yaml` was not copied to the isolated source tree. Synthetic test configs were confined to the owned basetemp.

The package origins and metadata are **SOURCE-ONLY test inputs**, not installed SDK wheels or release evidence. In particular, the parent composite is represented as source version `0.15.5`; this source-only run does not resolve its same-version/different-source release identity issue. The clean CTP source snapshot is from reviewed commit `29f8ff171f61a71038328a7067e0909bf44774b2`; no SDK wheel, provider, credentials, account session, order, or native client was used.

A final fake-only same-process probe confirmed the boundary limit: after mutating the Store route to CTP, the Store-bound public wrapper rejected submit and made zero fake-client calls; directly reaching `wrapper._client.submit_order` through the private in-process attribute made one synthetic fake call. The candidate's wrapper is a compatibility guard, not an in-process isolation boundary. This does not reproduce an installed SDK or a real provider bypass.

## Decision

**`LOCAL_SAFETY_INCREMENT_ONLY / MAIN_MERGE_REJECTED`.** The r2c route guards and focused fake tests are useful local safety evidence. The full patched Store/Runtime suite still has 258 failures, so the combined candidate is not ready for the main tree. Do not resolve that red suite by skips, xfails, deleting tests, or by describing the focused scope as broad acceptance. This packet does not authorize a provider route, native import, real account session, or live write.
