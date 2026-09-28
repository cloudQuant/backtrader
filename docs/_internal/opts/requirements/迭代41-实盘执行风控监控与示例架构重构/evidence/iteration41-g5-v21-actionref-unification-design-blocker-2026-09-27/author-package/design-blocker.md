# G5 / V21 ActionRef allocator unification: design and blocker

**Decision:** `DESIGN_ONLY / BLOCKED_FOR_PATCH / NO_WRITE / LIVE_NO_GO`.

This package records a source-hash-bound review of the archived fake-only collision, the G5 candidate caller path, the frozen V21 caller/migration path, and a static compatibility proof. I did not edit either source tree, execute/import either SDK, run a provider/native path, or read private configuration. The static checker parses source text with Python `ast`; it does not import project code. No allocation authority or write authorization is claimed.

## Collision proof and scope

The archived fake-only report is `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-g5-dual-actionref-collision-proof-2026-09-27/README.md` (SHA-256 `D83F57F483FF401AFD8DB17B8F2EE6C86A4BCBC24C8D4E20D4512ED610E5AEA5`). Its author script is hash-bound at `23033D685FF63B4D28F9FA9E3C306F9018B7424A0299F9F7EE7E7F9714315659`; the archive records two identical fake-only runs.

The proof uses one synthetic account and one in-memory SQLite store. G5's authority and the V21 allocator each returned `native_action_ref = 1` from different tables. It demonstrates independent allocation namespaces. It does **not** prove that a provider received or accepted duplicate references, does not stage a complete V21 cancel, and does not create the V21 allocation mapping row. The archived status remains `STRUCTURAL_COLLISION_REPRODUCED / FAKE_ONLY_LOCAL_REPRO / G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`.

## Source-bound call path findings

| Surface | Exact path | Finding |
|---|---|---|
| G5 reservation | G5 `ctp_identity_authority.py:86–116, 367–477` | Creates `ctp_action_ref_watermarks` and `ctp_action_identity_reservations`; new value is `max(caller legacy seed, MAX from only G5 reservation rows) + 1`. The reservation table's unique `(account_key, native_action_ref)` constraint protects only its own table. |
| G5 staging | G5 `ctp_identity_authority.py:493+`; G5 worker `ctp_single_worker_candidate.py:360–453` | G5 worker accepts typed `action_identity`; `stage_cancel_command` injects its ActionRef into the command payload and stages it through the G5 Store. The G5 Store is schema 5 and its staging API has no canonical V21 allocator handshake. |
| G5 public bridge | G5 `backtrader_bridge/ctp_order_action_bridge.py:105–147`; main-repo candidate `ctp_i9_parent_request_builder.py:708–757` | Reserves in G5 authority then expects the worker binding/command row to echo the same numeric ActionRef. The proposed I9 worker contract explicitly passes `action_identity`. |
| V21 allocation | V21 `store.py:9242–9300, 9654–9725, 9895–9909, 10163–10172` | Allocator reads the V21 per-account counter and V21 allocation table only. First allocation starts at 1. The V21 stage transaction allocates internally, builds `OrderActionRef`, and inserts the mapping row. Caller-supplied `native_action_ref` is rejected. |
| V21 worker | V21 `ctp_single_worker_candidate.py:420–472` | `stage_prepared_dispatch` has only `cancel_target_projection`; it calls Store staging without `action_identity`. Its typed binding is derived from the Store command. |
| V21 migration | V21 `store.py:5625–5698, 7405–7451` | `_migrate_legacy_ctp_action_ref_accounts` fences pre-V2 cancel command history. It does not read/import G5 `ctp_action_identity_reservations` or `ctp_action_ref_watermarks`. V21's unmapped-history list names V21 action allocation tables, not G5's tables. |
| Version boundary | G5 Store `store.py:271, 481–517`; V21 Store `store.py:2189, 2573–2576` | The candidate snapshots are materially different Store APIs/schema generations (5 vs 21). G5 schema code rejects an unsupported schema version; V21 accepts 20/21. These frozen trees do not form a compatible drop-in package pair. |

The static compatibility checker independently asserts the above API and migration split against exact source hashes. Result is `STATIC_API_AND_MIGRATION_SPLIT_CONFIRMED`; see `verification.json`.

## Why I did not make a partial patch

A change to only one allocator leaves the other writer able to allocate the same account/ref from its independent sequence. A change to only the G5 worker cannot attach G5's value through V21: the V21 worker does not accept `action_identity`, and V21 Store expressly rejects a caller-provided ActionRef. A change to only V21 leaves the G5 authority and its reservation table intact. The frozen G5/V21 API packages therefore need a coordinated schema and call-contract release, not a one-tree shim.

A migration also cannot safely renumber a legacy reference. If the same account/ref is present for different G5 and V21 actions, those rows may correspond to actions already handed to a native queue; rewriting either identity would corrupt history. The only safe migration behavior for a conflicting or unreadable account is to preserve both source ledgers and permanently fence that account pending separately authorized reconciliation.

Even after local-ledger unification, the current seed inputs do not prove the native provider's historical maximum. G5's `CtpActionRefSeedProof` is caller-supplied; the source describes it as collision evidence, not a trusted native watermark. V21 begins its local sequence at 1 when its counter is absent. Therefore a locally unique SQLite sequence is not yet evidence that the first new live ActionRef is above all native/provider history. The current supported conclusion remains NO_WRITE/LIVE_NO_GO.

## Safe target design for a later coordinated candidate

1. Introduce one account-keyed canonical reservation/allocator API in the exact V21 Store, with a unique `(account_key, native_action_ref)` constraint and idempotent `(account_key, scope_key, managed_action_id)` key. Keep caller-supplied raw integers forbidden.
2. Let G5 reserve through that same Store API. Let V21 staging accept only a typed reservation handle which it rereads from its own Store inside the same transaction, then bind that reservation to the command. Both G5 and V21 must use one row and one transaction/lock authority; no shadow G5 allocator remains.
3. Make allocation identity pre-stageable or stage-and-allocate atomically. If pre-stage reservation is retained, retries for the exact same action return the same value; conflicting identity fails; an abandoned reservation burns its number and can never be reused.
4. Add an explicit schema migration that reads all known local ActionRef facts: G5 reservations and watermarks, V21 counters and allocation rows, and V21 historical cancel payloads/command correlations. Preserve immutable bytes. Reconcile only exact same-action duplicates. Fence the account on any ref collision, unreadable identity, mismatched action mapping, or unknown legacy state; never auto-renumber.
5. Add stale-writer barriers as part of the same coordinated release: upgrade-time triggers/guards must reject writes to retired allocator tables, and both Store versions must reject opening/allocating against an unsupported schema. Verify behavior with two separately opened Store instances and the old writer API after migration; migration without stale-writer rejection is not unified authority.
6. Keep the provider/native path disabled. To move beyond local uniqueness, a separately reviewed trusted native ActionRef watermark or a reviewed account cutover procedure must establish the provider floor. A caller boolean, digest, or asserted seed is insufficient.

## Required fake-only verification before any implementation review

- Concurrent reservations through both API facades and separate SQLite connections on one DB yield no duplicate refs; same action retry returns one ref; conflicting action reuse fails.
- Close/reopen across process-style Store reconstruction preserves next-ref monotonicity and the exact action-to-ref mapping.
- Crash-shaped sequences (reservation without staging; stage retry; staged command retry) never free/reassign a ref.
- Migration matrix: G5-only history, V21-only history, nonoverlapping combined history, exact same-action overlap, conflicting overlap, missing/malformed mapping, high-water-only counter, and int32 exhaustion. All conflicting/unknown cases preserve old bytes and fence the account.
- An old G5 API and an old V21 API both fail closed when they attempt allocation after unified migration; no test should accept a second fallback allocator.
- The caller's native request payload is derived only from the canonical typed Store row; raw ActionRef input and mismatch between reservation, command, and payload reject.
- All tests stay on synthetic SQLite/fake callbacks, with zero provider/native imports, sockets, private config reads, or live execution.

Existing tests are narrower: G5 `test_order_and_action_refs_are_distinct_stable_and_restart_safe` and `test_action_reservation_is_concurrent_unique_and_rejects_conflicting_order` cover only G5's allocator; G5 worker fake tests cover its own `action_identity` handoff. They do not test a shared G5/V21 ledger or dual-version migration. The archived collision repro is the only cross-allocator test identified in this review.

## Verification and disposition

- `python verify_static_blocker.py` — PASS; exact preimage hashes and static API/migration assertions matched.
- No SDK package tests were rerun. No project code was imported or executed; no new fake runtime behavior was implemented.
- No patch was produced because a one-sided patch would leave a live second allocator and an unsafe migration boundary. This is a design blocker, not an approval request or write authorization.
- Main repository tree was not modified.

Source hash matrix: see `source-preimages.sha256`. The verifier script and this report are frozen in this directory; the SHA manifest covers both artifacts and the captured verification output.
