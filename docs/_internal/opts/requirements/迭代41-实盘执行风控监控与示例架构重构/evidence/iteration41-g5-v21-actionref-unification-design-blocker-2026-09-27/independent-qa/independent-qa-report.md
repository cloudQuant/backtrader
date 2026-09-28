# Independent static QA — G5 / V21 ActionRef design blocker

Date: 2026-09-27. Verdict: **the design package correctly blocks G5/V21 integration and the live floor**. Status remains `DESIGN_ONLY / BLOCKED_FOR_PATCH / NO_WRITE / LIVE_NO_GO`.

## Frozen identity and integrity

- Frozen package: `D:\temp\iteration41-g5-actionref-unification-design-blocker-20260927`
- `manifest.json` SHA-256 (independently calculated): `47BFFEEF1C94E2B6478F389DFA0C4653EB7993FA8B0DB71C3CA1E36963E0650E`
- Frozen package `SHA256SUMS.txt`: all 4 listed artifacts matched hash and byte size.
- `source-preimages.sha256`: all 20 listed archived/main/G5/V21 inputs matched hash and size.
- Frozen AST-only verifier rerun: exit 0, `STATIC_API_AND_MIGRATION_SPLIT_CONFIRMED`; it imports no project package. No source tree was edited and no provider/native/credential path was used.

## Call-contract and migration blockers confirmed

1. **Separate allocators.** G5 `reserve_cancel_action_identity` reads `ctp_action_ref_watermarks` and computes its high-water mark from `ctp_action_identity_reservations` only (`ctp_identity_authority.py:367–491`). V21 `_allocate_ctp_native_action_ref` reads/updates `ctp_native_action_ref_counters` only and checks/inserts its own `ctp_native_action_ref_allocations` (`store.py:9242–9300`, staging at `9895–9909`, allocation row at `10163–10175`). Their uniqueness constraints do not cross tables.
2. **Worker and Store APIs do not compose.** G5 `stage_prepared_dispatch` accepts `action_identity=` (`ctp_single_worker_candidate.py:360–366`) and G5 stages `OrderActionRef` in its logical payload (`ctp_identity_authority.py:525–547`). V21's worker signature accepts only `cancel_target_projection=` (`ctp_single_worker_candidate.py:420–425`). V21 Store rejects non-`None` `native_action_ref` (`store.py:9705–9706`) and rejects `OrderActionRef` in the logical request payload (`store.py:9725`). This is a concrete API incompatibility, beyond merely different allocator names.
3. **Schema and migration do not bridge the ledgers.** G5 Store is schema 5 and rejects a different stored schema version (`store.py:271, 516`). V21 Store is schema 21 and accepts 20/21 for its own migration (`store.py:2189, 2574`). V21 `_migrate_legacy_ctp_action_ref_accounts` scans/fences historical V21 dispatch commands and does not import G5 reservations/watermarks (`store.py:5625+`). There is no safe drop-in shared-store migration in these frozen snapshots.
4. **Local uniqueness is not a native floor.** G5's initial seed is caller-supplied collision evidence; V21 initializes an absent counter at 1. Neither establishes an authenticated native `MaxOrderActionRef` floor. Coordinating local rows alone would not make the first live ActionRef safe.

## Archived collision scope

The archived proof is correctly labeled `STRUCTURAL_COLLISION_REPRODUCED / FAKE_ONLY_LOCAL_REPRO / G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`. Its source and result hashes are bound in the frozen source index. The archived script uses one synthetic account, one `:memory:` SQLite store, and caller-supplied synthetic zero floors. It reserves a G5 ActionRef and directly calls the V21 allocator primitive; both return 1. It does **not** stage a full V21 cancel or insert the V21 command-to-ActionRef allocation row. Therefore it proves independent local namespaces can collide, not that a provider received, accepted, or observed a duplicate. The archive records two identical fake-only runs; I reviewed the saved records and did not rerun that probe.

## Disposition

The blocker is valid and sufficiently conservative: do not integrate either side by a one-tree shim, do not migrate/renumber ambiguous history, and do not treat the synthetic collision as provider evidence. A later candidate needs one account-keyed Store allocator/typed reservation handshake, a coordinated migration that preserves and reconciles both ledgers while fencing conflicts and stale writers, and a separate trusted native ActionRef floor/cutover before any live consideration. Current G5/V21 remains **blocked / not accepted / no write / live no-go**.

## Independent QA artifacts

`independent-qa-SHA256SUMS.txt` binds this receipt, the frozen inputs, hash verification output, and the source excerpts used for the static review. `verification.json` records every calculated source and package hash plus the AST verifier result. No tests or native SDK imports were run.
