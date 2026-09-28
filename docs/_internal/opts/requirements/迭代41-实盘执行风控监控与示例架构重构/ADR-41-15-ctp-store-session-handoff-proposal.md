# ADR-41-15 (PROPOSED): CTP Store–Execution Session handoff

**Status:** PROPOSED — not accepted, implemented, or a write authorization.  
**Date:** 2026-09-25  
**Scope:** the missing managed CTP order/cancel bridge between `BtApiStore` and `CtpSimulationExecutionSession`.

The single OrderRef/outbox/receipt rules and local config-to-action consistency
boundary below apply to both future admission branches. Strict F14 and
production use **G6-P**, which additionally requires an external
account-wide writer fence. A bounded SimNow **G6-S/G7-S** branch is possible
only if [ADR-41-16 option B](ADR-41-16-simnow-f14-writer-fence-proposal.md)
is accepted and its separate operational permit, local owner window and
residual-risk record are verified. G6-S cannot claim cross-host exclusion or
a common account snapshot. Neither branch is accepted or connected today.

## Problem

`BtApiStore` already hands a CTP adapter typed `CtpManagedOrderDispatch` and
`CtpManagedCancelDispatch` identities; its command worker calls public SDK
`async_make_order` / `async_cancel_order`. The queue receipt means only local
enqueue/rejection or an uncertain enqueue. Separately,
`CtpSimulationExecutionSession` journals an exact
`CtpSimulationWriteRequest`, requires a signed `CtpSimulationWriteApproval`,
and currently calls `CtpTraderClientSimulationPort` directly for native
submit/cancel receipts. Its SQLite journal, the SDK's candidate runtime-
`OrderRef` journal, and the Store's in-memory heap do not form one end-to-end
contract. The public SDK CTP adapter must return exact native evidence through
the async method completion; neither the Store queue receipt nor a direct
second TraderClient path can stand in for that evidence.

The relevant seams are `backtrader/stores/managed_execution.py`,
`backtrader/stores/btapistore.py::_submit_ctp_managed_order` / `_enqueue_ctp_managed_cancel`,
`backtrader_runtime/managed_execution.py::CtpManagedExecutionAdapterPlaceholder`,
`backtrader_runtime/ctp_simulation_execution.py::CtpSimulationExecutionSession`,
and `backtrader_runtime/ctp_trader_client_port.py::submit_order_insert` /
`submit_order_action`. The placeholder must continue to reject before calling
the Store callback until this handoff is implemented and separately admitted.

## Verified implementation boundary (2026-09-25)

The local `bt_api_execution` package now has a SQLite WAL store configured
with `synchronous=FULL`, an account-keyed `ctp_order_identity_reservations`
table, an atomic `reserve_ctp_order_identity()` allocator, and a generic
`claim_for_dispatch()` lifecycle transition. These are useful primitives, not
the handoff described here. `reserve_ctp_order_identity()` allocates from the
maximum value in its own reservation table and starts an empty table at
`000000000001`; it does not seed from the native CTP login watermark, older
SDK JSONL reservations, the Backtrader CTP prototype journal, or already-used
native references. Its restart-safety therefore covers only references already
recorded in this new table.

The current SQLite `execution_outbox` and `cancellation_outbox` are append-only
lifecycle-event logs, not durable command queues. For example,
`intent_admitted` records a permit reference and `dispatch_claimed` records an
attempt number; neither event contains a complete, versioned SDK request to
execute. `read_outbox()` is a read-only ordered page and does not claim rows,
advance a durable consumer cursor, or acknowledge delivery. Meanwhile,
`claim_for_dispatch()` atomically changes an execution record to
`DISPATCHING` and appends its event, but it does not create a claimable worker
command. Do not infer a durable command outbox from the combination of these
APIs.

`BtApiStore._command_heap` is process memory. Its worker removes a command from
that heap before invoking the SDK, and the heap is prioritized rather than
globally FIFO. Queue admission and the in-memory `inflight` counters do not
survive process death. A durable command table and durable claim transition
must therefore be added; causality between a submit and cancel must be
enforced by durable order/target state, not by heap priority or enqueue order.

The CTP login response exposes `MaxOrderRef` (the SimNow CTP Mini API V1.7.0
manual lists it on `OnRspUserLogin` as the maximum order reference:
[official API manual](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf)). This is a native login observation and a required input to establish a local allocation floor. It does not prove that all other account writers have stopped or that the observed value is globally unique across fronts, sessions, or external clients. G6-P requires the independently issued account-wide fence across cutover, watermark establishment and every later dispatch. A future approved G6-S window may use only a local owner lease and bounded permit; unobserved outside writers and OrderRef collision remain explicit residual risks, not properties established by `MaxOrderRef`.

The current public SDK `async_make_order` / `async_cancel_order` path awaits the
completion of a synchronous CTP feed method executed off-thread. For submit,
that method returns the native insert call's immediate return code and request
data; it does not await or deliver the later CTP response/order callback. For
cancel, it may include an immediate callback-history snapshot, which can still
be `unknown` if the callback has not arrived. Later callback evidence remains
in the TraderClient history and is not a completion pushed through the public
async method. A reviewed adapter must return a typed immediate-submission
receipt and separately correlate and deliver callback evidence; neither may
be called provider acknowledgement without the corresponding verified fact.

The public SDK execution `Session` also currently persists its own JSONL
runtime-order bindings and submit/cancel intent lifecycle, and owns a
`runtime_action_id` issuer. That behavior is a second managed identity/state
authority today. The proposed SQLite-only authority is not achieved until the
SDK path can accept and validate the exact SQLite mapping/action IDs and its
JSONL state is reduced to non-authoritative transport/callback evidence (or a
checked projection), with no independent reservation, replay, or terminal
state decision.

There are also two unconnected pure request contracts with different digest
domains. `backtrader_runtime.ctp_managed_handoff` computes a Backtrader
handoff `request_digest` over scope, account, trading day, managed identities,
OrderRef, and the full canonical request fields. The SDK's
`CtpManagedNativeDispatchRequestV1` computes
`request_digest_sha256` in the `ctp.managed.native-dispatch.v1` domain over its
native dispatch identity and native fields. The SDK pure contract now
requires a distinct `parent_handoff_digest_sha256` and includes it in its
native digest and completion echo. These digest values are not
interchangeable, and neither contract is wired into the Store-to-SDK path.

## 2026-09-26 single-allocator cutover refinement

The isolated `bt_api_execution` I9 source candidate has an account-scoped,
transactional SQLite OrderRef reservation and a same-row staged command,
queue receipt, single claim and `UNKNOWN` recovery path. Its
`seed_ctp_order_ref_and_reserve_identity` accepts native `MaxOrderRef`, legacy
bindings and high-water marks, but those inputs are caller assertions; the
method does not authenticate their origin or exclude another account writer.
The follow-up source commit `b676fe6` maps every post-claim sender
`REJECTED` to `UNKNOWN` because a sender payload cannot prove that no native
request or callback occurred. The candidate remains unregistered and has no
native sender or wheel.

The SDK runtime integration candidate under `D:/bt_api_py` currently allocates
another 12-digit ref from `time.time_ns() % 10**12` in
`_execution_session.py::new_runtime_order_binding`; the clean
`D:/source_code/bt_api_py` checkout does not contain that method. The CTP
feed also falls back to its own `next_order_ref()` when no client ID is
supplied. The Gateway runtime overwrites an external `client_order_id` with
its JSON allocator. All three paths must be fenced for managed CTP. A future
SDK consume-only port may persist a checked mirror of an already committed
I9 reservation, but may not issue a new ID, advance a separate watermark,
overwrite the exact ref, or become another order-state authority. Managed
cancel reuses the target order's reserved ref and binds its native target
identity; it never allocates a new OrderRef.

The required sequence is: fence old SDK/Gateway/direct writers; independently
verify native and legacy order state and seed the I9 watermark; commit one I9
reservation; let the SDK consume exactly that ref; stage the I9 outbox row;
commit the exact queue receipt before worker publication; claim once; send
once. A failure before stage/claim may burn a ref, which is safe only if refs
are never recycled and no native send occurred. A failure after claim is
`UNKNOWN` and freezes further writes pending independently reviewed
reconciliation. Separate SQLite databases need no distributed transaction
*only if* the SDK mirror has no allocation/send authority and every failure
before the I9 claim stops native dispatch. This order is a proposed cutover
contract, not an accepted live route.

QA must fake concurrent/restarted reservation, account/TradingDay/scope and
legacy mapping conflicts, MaxOrderRef/old-watermark floor, malformed or
overflowed refs, SDK feed fallback, Gateway ref overwrite, exact cancel
target, receipt-before-notify, duplicate workers and all crash cuts. A local
queue `QUEUED` receipt is not provider ACK. The current Backtrader managed
submit/cancel hard rejects remain until the consume-only port and the entire
sequence are connected and reviewed.

## Proposed decision

1. **One state authority.** Use the planned `bt_api_execution` account-scoped
   SQLite WAL database with `synchronous=FULL` as the only active managed order,
   action, OrderRef-mapping, and dispatch-outbox authority, consistent with
   D41-01/D41-19. The current `ctp_sim_orders` journal is a prototype seam; it
   must be migrated behind the execution storage port or retired before an
   integrated route is enabled. Do not dual-write it and the execution ledger.
   SDK transport records may retain native callback evidence, but may not
   independently reserve managed OrderRefs or own a second managed order
   state machine.

2. **One managed dispatch entry.** The Store SDK command worker is the only
   managed dispatch entry and calls public `BtApi.async_make_order` /
   `async_cancel_order` with a reviewed typed CTP request. A reviewed public
   CTP SDK adapter behind those methods is the only code that constructs native
   fields, calls native insert/action, and returns exact native evidence to the
   worker. Do not wire the execution session to a separately constructed
   `CtpTraderClientSimulationPort` for writes, create a second TraderClient, or
   bypass the public SDK gate. Split the session's synchronous write seam into
   durable prepare / dispatch-result operations. The durable outbox, not
   `BtApiStore._command_heap`, is the source of managed work. A transaction
   changes `READY` to `CLAIMED`/`DISPATCHING` before handing its identity to the
   transient heap. The worker calls public async SDK methods once and persists
   their typed native completion against that claimed row. Managed actions
   have no legacy or direct-native fallback.

3. **Durable order identity.** For a submit, derive
   `runtime_order_id` deterministically from the canonical execution scope key
   and `managed_intent_id` (the existing `bt-managed-v1:` construction is the
   intended form); never use or truncate `Order.ref`. In one authority
   transaction, bind the scope digest, intent ID, runtime order ID, and an
   allocated exactly 12-character ASCII-digit CTP `OrderRef`, with uniqueness checks
   in both directions. Reserve the OrderRef before the outbox can dispatch;
   reservation-only IDs are never reused. The Store's managed request carries
   this typed mapping; it must not independently allocate a second OrderRef.
   Any SDK `runtime_order_binding` hook becomes a checked read projection of
   this mapping for the same account/trading day, not a competing reservation
   authority. Keep names distinct: `runtime_order_id` is the stable runtime
   key; CTP `OrderRef` is the exact 12-digit native reference. Do not overload
   `client_order_id` across the runtime and SDK layers. The versioned SDK
   request digest is canonical over scope digest, `managed_intent_id`,
   `runtime_order_id`, exact OrderRef, operation, and all native request fields.
   The versioned SDK request and typed native receipt echo those same fields
   and digest. Before completion commit, compare every echoed field to the
   claimed outbox row; any mismatch is `UNKNOWN` and freezes further writes.
   The submit approval digest covers this final mapping (including OrderRef),
   request digest, and registration/config digests.

   **Bind both digest domains without aliasing them.** Persist the
   Backtrader-side handoff digest and SDK-side native digest as separate,
   versioned values in the durable command. Add the exact parent
   `handoff_request_digest` to the SDK native request contract and include it
   in the SDK native digest payload. The native request and typed immediate
   receipt must echo both values. Before native invocation, rebuild/validate
   the handoff digest from the canonical parent request, validate the
   deterministic translation to SDK-native fields, then validate the SDK
   native digest. Before settlement, compare both digests and all echoed fields
   with the durable command. A missing or mismatched parent digest rejects
   before native invocation; any post-claim receipt mismatch becomes `UNKNOWN`.

   **Account OrderRef watermark and cutover are hard preconditions.** Before
   the first managed reservation, freeze legacy managed writes and establish
   the branch-specific writer boundary: G6-P requires the external account-wide
   fence; a separately approved G6-S requires its bounded operational permit
   and local owner window, while recording that outside writers are unexcluded.
   Reconcile and import every known
   nonterminal or reservation-only mapping from the old Backtrader prototype
   journal and SDK JSONL, and collect the applicable native login
   `MaxOrderRef` plus verified existing native order references. Persist a
   monotonic account-scoped OrderRef watermark. In the same SQLite
   `BEGIN IMMEDIATE` transaction that seeds/raises this watermark, reserve a
   new mapping above `max(watermark, imported references, existing local
   reservations)` and update the watermark with that mapping. A retry may not
   lower the stored watermark or reuse a reservation-only value. The command
   admission transaction must then bind the already-reserved mapping to the
   approved request before it becomes dispatchable. If the legacy/native
   reference set cannot be reconciled, the login watermark is absent or
   ambiguous, or the selected branch's writer boundary cannot be established
   and held, fail closed before creating a dispatchable command. `MaxOrderRef`
   supplies a local reference floor only. G6-S never upgrades this to
   account-wide uniqueness; G6-P remains mandatory for strict F14/production.

4. **Approval ownership.** The trusted runtime operator signer owns each
   short-lived `CtpSimulationWriteApproval`. It signs the exact request after
   the final OrderRef or cancel target is durably reserved and before the
   execution authority admits the action/outbox transaction. Strategy
   metadata, `BtApiStore`, the bridge, and `CtpSimulationExecutionSession` do
   not mint it; the session verifies it. Separately, the SDK owns its existing
   approval/arm and final per-action native gate, rechecked under the SDK lock
   by the reviewed public CTP adapter. The bridge must not call a private SDK
   issuer or treat SDK approval material as operator authorization. The
   operator signer/key source is not deployed; its public contract and
   protected key custody remain pre-composition work.

   The unique approval-use/nonce record must be persisted in the same SQLite
   transaction as the admitted intent or cancel and its `READY` command row.
   Signature verification alone is replayable until expiry and does not
   consume an approval.

5. **Separate enqueue from native receipt.** Name and persist the Store result
   `LOCAL_QUEUED` (or equivalent): it proves only that a command entered a local
   queue. It is not `CtpSimulationDispatchReceipt`, provider ACK, or an order
   state transition. Until the worker returns and the authority persists an
   exact native receipt, the action remains dispatch-pending and cannot be
   retried. A matching native code `0` plus SDK evidence may yield
   `CtpSimulationDispatchReceipt(QUEUED)` and an order `PENDING` state; it still
   means no more than native local queue acceptance. A negative code is
   `REJECTED` only with exact evidence that no callback arrived. Any timeout,
   exception after dispatch claim, mismatched digest/identity/session, or
   incomplete receipt becomes `UNKNOWN` and freezes dependent writes. Only
   separately verified callback/query evidence advances provider order state.

   The public async SDK completion currently provides only the synchronous
   native-call result described above, not the later response/order callback.
   The v1 bridge must make this distinction explicit in its types: an immediate
   `LOCAL_QUEUED`/native-call receipt may establish only that CTP accepted the
   local request submission call; the callback channel records a separate,
   exactly correlated response/order/trade fact. A timeout waiting for that
   fact never turns the immediate receipt into provider acknowledgement.

6. **Cancellation and restart.** A cancel reuses the durable submit mapping
   and targets the verified native tuple `(OrderRef, OrderSysID, FrontID,
   SessionID)`. It has one stable action ID: `runtime_action_id` and
   `managed_cancel_intent_id` must be equal at the v1 Store boundary. This ID,
   the target and order mapping, and the cancel fields are included in the
   approval/request digest, typed SDK request, outbox row, and native receipt.
   A unique action row is committed before dispatch. Native `OrderActionRef`
   is allocated by the SDK request path; never derive it by truncating the
   runtime action ID. A cancel
   enqueue/ACK remains pending until native order reconciliation proves a
   terminal order state. On restart, an unclaimed durable outbox item may be
   delivered once; any action durably claimed for dispatch without a persisted
   native receipt is `UNKNOWN`, is not resent, and requires exact verified
   reconciliation. A missing volatile cancel callback may be resolved only
   under the existing verified terminal-target rule (`TARGET_TERMINAL`), never
   recorded as cancel acceptance. Conflicting mapping, missing target identity,
   or incomplete evidence blocks before dispatch.

   The generic event outbox and `claim_for_dispatch()` are not substitutes for
   a durable command state. Add a versioned typed command row with at least
   `READY`, `CLAIMED`, and receipt-settled states. In the same SQLite
   transaction that admits the intent/cancel and consumes its unique approval
   ID, persist the canonical command, full request digest, exact mapping or
   cancel target, scope/session binding, and `READY` state. The Store heap holds
   only the durable command ID. A worker uses a conditional
   `READY -> CLAIMED` update under `BEGIN IMMEDIATE`; only the transaction that
   changes one row may enqueue/invoke it. `READY` means no worker has claimed
   the command and it may be claimed after restart. `CLAIMED` means the native
   boundary may have been crossed: after any crash or lost worker without a
   durable matching receipt, recovery changes it to `UNKNOWN`, never back to
   `READY`, and never resends it. Persist the exact typed native receipt and
   settle the claim in one transaction after checking command ID, request
   digest, account/scope, lease/fence generation, and SDK session generation.
   A crash between claim commit and heap handoff is therefore conservatively
   `UNKNOWN`, not redeliverable. The generic lifecycle event log remains
   available for projection/audit and is not the command delivery protocol.

7. **Account ownership.** The execution composition owns the local
   `CtpAccountFlowLease` and holds it from before TraderClient construction
   through Store worker drain, SDK close, and journal close. G6-P additionally
   requires an independently owned external account-wide fence; only its
   issuer/coordinator can establish that authority. An approved G6-S would
   instead require a separately verified bounded operational permit and local
   owner window, without claiming outside-writer exclusion. The execution
   owner validates the branch, account and environment at open and rechecks
   its branch-specific boundary immediately before dispatch and reconciliation.
   The worker and public CTP adapter receive only a session-bound dispatch
   grant and refuse work after lease, required boundary, account, trading-day,
   or connection-generation change. A Store-local lock does not replace the
   external fence required for G6-P. If worker stop, native close, or final
   receipt is uncertain, poison the owner and retain the local lease; do not
   release ownership while a native call may still be active.

The adapter must project durable states to Backtrader as nonterminal
`submitted`/pending responses until verified native facts arrive. It must not
take the Broker's optimistic local-cancel path for a queued or unknown cancel.
Existing execution projection semantics for `UNKNOWN`, pending cancel, and
late fills remain authoritative.

## Handoff / required implementation boundary

The Store adapter canonicalizes the framework order and supplies the stable
intent/runtime identity. The execution authority first commits the unique
OrderRef mapping and watermark; the runtime operator signer can then sign the
exact request including that reference. After approval verification and risk
admission, one transaction consumes the approval-use ID and commits the
intent/action plus typed `READY` command row and lifecycle event. The Store
worker claims that command row transactionally before putting its ID in the
transient heap, then calls only public `async_make_order` / `async_cancel_order`.
The reviewed public CTP SDK adapter performs the native operation and returns
a typed immediate receipt; a separate callback channel delivers later native
response/order/trade evidence. The worker persists the immediate receipt
against the claimed command row; the execution authority compares the full
echoed identity before changing state.
The bridge projects only the resulting durable state to the Store/Broker.
Queue receipt and native receipt are distinct messages, types, IDs, and state
transitions.

This requires new, versioned bridge contracts; it is not a wiring change to
today's dataclasses. The current `CtpManagedOrderDispatch` does not carry the
exact OrderRef, `CtpManagedCancelDispatch` does not carry the verified native
target tuple, and the current `CtpSimulationDispatchReceipt` does not echo the
complete scope/runtime-ID/order/action mapping required above or flow through
the public async Store worker for comparison with a SQLite command row.

The first cutover must address the existing Backtrader SQLite prototype and
SDK candidate JSONL mapping without dual-writing: freeze writes, reconcile all
nonterminal rows, import/validate mappings into the single execution ledger,
then switch the managed route. SDK JSONL may retain transport/native callback
evidence, but is not a second managed OrderRef allocator or OMS. Until that
cutover, reviewed package pins, operator signer/key custody, native lifecycle
readiness, public SDK typed receipt delivery, and explicit route admission are
accepted, the default inventory and `CtpManagedExecutionAdapterPlaceholder`
remain fail-closed. This proposal does not wire a route or authorize provider
I/O.

## Required fake end-to-end QA

Use temporary journals, synthetic scope/account values, and a fake Store
worker/public SDK/native adapter chain only; assert zero sockets, credentials,
and provider calls.

- First submit runs through fake `BtApiStore` → durable typed command outbox →
  public `BtApi.async_make_order` → reviewed public CTP adapter → execution
  authority completion. Prove one mapping and one native dispatch; exact scope,
  intent, runtime ID, 12-digit OrderRef, request digest, HedgeFlag, and typed
  receipt agree at every hop. Replaying identical intent dispatches zero
  additional requests;
  changed payload or either-direction identity collision rejects before dispatch.
- Watermark bootstrap and allocation: an empty local reservation table with
  verified login `MaxOrderRef=79` allocates `000000000080`; importing a legacy
  or verified native reference `000000000123` allocates `000000000124`. Seed
  and reservation are linearizable across independent SQLite connections,
  survive close/reopen, and never lower an existing watermark. A conflicting
  mapping import rejects; an older valid imported mapping may be retained but
  cannot lower the allocation floor. Injected failures in seeding/import leave
  no dispatchable command. Tests separately show that a `MaxOrderRef`
  observation alone cannot admit a write: G6-P still requires its external
  fence; G6-S still requires an accepted, current bounded permit and local
  owner window, and its outside-writer risk must remain `UNPROVEN`.
- Command-outbox distinction and recovery: prove lifecycle `read_outbox()`
  cannot claim or redeliver work; verify durable command rows contain the
  canonical request and approval-use identity. Two workers racing on one
  `READY` command produce one `CLAIMED` transition and at most one native call.
  Restart reclaims only `READY`; `CLAIMED` without receipt becomes `UNKNOWN`
  and is never resent, including a crash after claim commit and before heap
  insertion. Heap priority changes cannot violate submit/cancel target-state
  prerequisites.
- Digest-domain binding: assert the Backtrader handoff digest and SDK native
  digest are distinct persisted fields, the exact parent digest is included in
  the native digest material, and both are echoed in the immediate receipt.
  Recompute both from the same immutable command; mutate or omit each parent
  field/digest and each native field/digest in turn and prove rejection before
  a native call. A native digest that is internally valid for altered native
  fields must still fail if it is not bound to the durable parent handoff.
- A local Store queue receipt alone leaves the intent pending with no provider
  ACK. Matching native `QUEUED`, verified local rejection, malformed receipt,
  timeout after claim, and callback-received negative code each land in their
  specified distinct states; all uncertain cases freeze and never resend.
- Expired, wrong-scope, wrong-request, or reused approval rejects before the
  worker; approval-use uniqueness and command insertion are atomic. Submit
  immediate native-call receipt and final order callback/reconciliation remain
  separate: a zero return with no callback stays locally queued/pending, and a
  callback arriving before or after the SDK future completion is correlated
  exactly once to the same request. Partial fill followed by cancel retains
  fill and order identity.
- Cancellation traverses the same fake Store → typed command outbox → public async SDK →
  public CTP adapter path. Approval, request, outbox, and completion carry the
  same action ID and exact order mapping/target. Queue receipt and cancel-request
  ACK do not terminalize the order; exact terminal reconciliation does. Late
  fill, duplicate cancel, rejected cancel, unknown cancel, and target mismatch
  preserve the freeze/mapping rules.
- Inject crashes before reservation commit, after reservation/command commit,
  after atomic durable claim but before transient-heap handoff, after heap
  handoff, after native call but before receipt commit, after receipt commit but
  before Store projection, and at the same cancel cut points. An unclaimed
  outbox row may be claimed once. Any crash after claim but before durable
  receipt is `UNKNOWN` and never automatically replayed. Reservation-only
  OrderRefs are not reused.
- Restart/reopen with same and changed scopes; check exact mapping recovery,
  generation/trading-day binding, duplicate/corrupt rows, 11/13-byte,
  non-ASCII/NUL OrderRefs, and absent/ambiguous target evidence. Expired or
  wrong signer approval, lost branch-specific fence/permit, local lease loss,
  and stale SDK generation reject before public SDK dispatch. Test G6-P
  external-fence loss separately from G6-S permit expiry/revocation; every
  such reject has a zero native-call count.

## Open decision before acceptance

The design target is the D41-01/D41-19 execution SQLite authority. The package
has a generic lifecycle event log and an atomic single-attempt intent claim,
but its typed CTP command table/API, atomic `READY`→`CLAIMED` worker claim,
account OrderRef watermark bootstrap, and approval-use persistence have not
been implemented or frozen. The public async SDK request/receipt schema and
separate callback correlation/delivery path are also absent; the current async
completion is not a callback completion. Maintainers must prove the safe-
delivery rule across command commit, claim, heap handoff, native call,
immediate native receipt, later callback, durable settlement, and Store
projection. The G6-P external account-wide writer fence and runtime operator
signer deployment/key custody remain independently unassigned. G6-S option B
has neither an accepted decision nor a trusted operational permit issuer and
must not inherit G6-P's PASS label.
These are acceptance blockers, not permission to fall back to either existing
journal or direct native writes. Until resolved, status remains
`PROPOSED / NO_WRITE / LIVE_NO_GO`.
