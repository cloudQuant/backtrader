# Independent QA: BtApiStore Actor wiring r2b

**Verdict: `SAFE_TO_MERGE_FAIL_CLOSED`**, limited to the Store-level route mutation guards and explicit CTP constructor-time rejection in this candidate. This does not accept an external AccountActor, same-process isolation, G1/G5, native/provider access, a default CTP route, or live writes.

## Frozen input and reproduction

- Candidate snapshot: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b`; frozen manifest SHA-256 `ecfdf31484133fdbab34b755941f95617e7055dd705dd4238d4daf71eaf2a619`, 724 payloads.
- Store SHA-256 `24f8199e199bbe84bbb113c3edbbee9e71d4736fdd8573297e24ead3298f2518`; ActorPort SHA-256 `2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3`.
- Main-base Store SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`; exact patch SHA-256 `1a16aadb94edb99924553d6472bf72dcb02bd04c7f994276816d91991a729f37`. Independent scratch replay reversed then reapplied the patch, and the Store plus four test/module targets matched their frozen hashes.
- Independent pre-fix probe against R2a reproduced the wrapper gap with fake `GatewayClient`: after constructing an IB-web gateway wrapper, changing the owning Store route to CTP still allowed wrapper `submit_order` and `cancel_order` to hit the fake client. It reproduced for both `store.provider` and config route mutation. No actual SDK/network was involved.
- R2b attaches a route check to Store-created wrappers and rechecks before submit/cancel delegation; Store public, legacy, cancel-ref, managed cancel, and forwarding construction paths also reject mutated CTP route before touching trapped APIs/orders/client constructors. Static references: `backtrader/stores/btapistore.py` wrapper factory around 3274, Store attachment/adoption around 16936–16939, wrapper submit/cancel around 3504/3531, legacy and forwarding guards around 8357, 8693, and 17033.

## Independent results

Using Python 3.11.5, pytest 8.2.2, isolated candidate `PYTHONPATH`, plugin autoload disabled, and `-B`:

| Scope | Result | Notes |
|---|---:|---|
| Internal route mutation probes | 4 passed | Two mutation sources × wrapper/public and internal helpers |
| Candidate boundary + migrated CTP adapter tests | 43 passed | Includes all 21 migrated old CTP cases |
| Original three-file regression set | 30 passed | Retains execution adapter and live-dispatch guard coverage |
| All `tests/unit/stores` + `tests/unit/runtime` | 55 passed | Broad local scope |

Each run emitted the same existing Quandl deprecation warning. Counts overlap; they are not a unique-test total. Configured Ruff on the five changed Python files passed; `py_compile` passed. All 724 frozen payload hashes still matched after the runs. Imported `backtrader`, Store, and ActorPort origins were inside the isolated candidate; `bt_api_py`, `_ctp`, and `ctp_wrap` were absent from `sys.modules`.

Exact commands and complete output/JUnit are in `independent/run-artifacts/`. The main-base patch replay and source-origin/hash verification scripts and logs are included. One initial harness setup error and one first Ruff invocation without the repository's Ruff config are preserved; both were corrected, and the final configured checks passed.

## Migration table: 8/13 to 5/16

All 21 old node identities remain represented one-for-one as explicit constructor-time fail-closed parameter cases; the AST-derived IDs, migration table rows, and collected JUnit cases agree. No case was skipped or xfailed.

Three rows move from the earlier `FAIL_CLOSED_ASSERTION` bucket to `EXTERNAL_ACTOR_MIGRATION`:

1. `test_managed_ctp_orderref_from_sdk_ledger_is_not_reused_as_second_authority`
2. `test_managed_ctp_real_queue_fails_before_second_orderref_allocator[queue]`
3. `test_managed_ctp_real_queue_fails_before_second_orderref_allocator[unknown_classification]`

R2b makes CTP Store construction unavailable before a local fake adapter or SDK-ledger allocator can be reached. Those prior positive behaviors therefore remain future shared-ledger / authenticated-Actor requirements, not present local behavior to preserve as a passing CTP contract. Current counts change from 8 fail-closed + 13 Actor migrations to 5 fail-closed + 16 Actor migrations; the migration table retains each old intent and future positive contract.

## Merge boundary

The evidence supports merging this candidate **only while CTP remains fail-closed**. Route guards stop Store-owned wrappers and entry points after route mutation; tests do not establish arbitrary in-process tamper resistance. A caller can directly invoke the private wrapper-class factory or access the wrapper's raw client, so this is not a same-process security boundary. No authenticated external Actor, real SDK, native extension, provider, live order, or G1/G5 behavior was exercised or accepted.
