# G5 I9 OrderRef bridge audit — 2026-09-26

Status: `SOURCE_AND_FAKE_CONTRACTS_ONLY / G5_NOT_PASSED / NO_WRITE / LIVE_NO_GO`.
This page records an offline source review of the Backtrader I9 Store bridge
and the SDK consume-only OrderRef candidate at
`D:\bt_api_py_codex_orderref_consume_only_20260926`. No private config, `.env`,
credential, account value, or provider endpoint was inspected or used. No
provider session, native request, build, or write was attempted.

## Evidence that is useful but bounded

The existing [I9 execution artifact-set receipt](ctp-i9-execution-artifact-set-2026-09-26.md)
records an exact offline `bt_api_base`, `bt_api_ctp`, and `bt_api_execution`
wheel set installed and checked in a clean CPython 3.11.5 environment. Its
candidate verifier tests and two fake-API SDK event/close tests passed. That
receipt does not install or pin a `bt_api_py` managed parent, register a
runtime, connect the Store bridge, or prove provider readiness or writes.

The new SDK candidate method `consume_ctp_order_identity_reservation()` reads
an existing reservation, validates its account/day/scope/intent/runtime ID and
12-digit OrderRef, appends an SDK journal mirror, and returns that mirror.
Its fake-only contract file passed locally with
`python -m pytest -p no:asyncio tests/bt_api_contract/test_ctp_orderref_consume.py -q`
(`11 passed`, one existing pytest configuration warning). The tests cover
repeat consumption and restart readback, changed authority rows, malformed
reservation fields, SDK ref collisions, scope/environment mismatches, and a
second runtime reusing an account OrderRef. The method does not call the SDK
allocator, native sender, or queue. Its own docstring correctly labels the
mirror non-authorizing and says it is not bound to a later request.

In the main repo, `CtpI9ManagedDispatchBridge` now refuses structural/fake
ports before reservation, staging, or dispatch unless exact I9 classes are
importable and `single_worker._store is identity_port`, with exact scope
identity (`backtrader/stores/ctp_i9_managed_dispatch.py`). The
typed binding checks compare the reservation, request, command row,
correlation, approval-use fields, session binding, and queue receipt.
The queue receipt writer
records the receipt before dispatch and heap visibility; the dispatcher then
claims through the worker and reads back the row/projection. Cancel remains
fail-closed without trusted typed provider-order projection provenance.
These are candidate source contracts, not an accepted dispatch route.

After the exact-type/same-store guard was added, the former positive fake
end-to-end Store bridge tests were removed. Two negative tests reject
structural fake ports and fake cancel projections; a third checks the exact
eight-type tuple guard. An independent review then found that the real I9
`CtpDispatchCommand` has no direct `runtime_order_id` field. The bridge now
checks that value in the typed `correlation_key`, and requires a handle
actually issued by the same bridge for a submit before exposing queue
callbacks. With `BT_API_EXECUTION_I9_SOURCE` pointed at the isolated I9
source, the fourth test exercises real `SqliteExecutionStore` and worker
types: submit stage/readback and receipt→fake sender work; forged,
cross-instance, or cancel handles cannot write a queue receipt or reach the
sender. Root and independent review reran this source smoke. The current
focused file passed `4 passed`; the broad Store suite then passed `662 passed`
with one existing pytest configuration warning. This is source-only local
wiring evidence, not an installed-wheel, trusted authority, or provider run.

A follow-up cancel-provenance audit made the missing issuer explicit in the
bridge contract. I9's reservation binds account/scope/day/intent/runtime ID/
OrderRef, while the existing CTP query verifier can assess native query scope;
there is no trusted receipt joining those two identities to one provider
order. The prepared cancel's native target fields are caller supplied, and
the local outbox projection has no provider order identity. A negative fake
test supplies a complete target and still observes zero worker stage, queue
receipt, or sender calls. Root retained the existing public rejection reason.
A subsequent static check found that the current Store/I9 managed cancel DTO
requires both native target forms, while CTP Feed/TraderClient can accept
`OrderSysID + ExchangeID` **or** `OrderRef + FrontID + SessionID`. Future
managed cancel needs an explicit tagged target chosen from trusted provider
projection and exact reservation binding; the current stricter gate remains
closed. Three further negative tests lock rejection of single-route and
incomplete mixed targets. Root reran the Store suite with isolated I9 source
available: `667 passed, 1 existing PytestConfigWarning`. This does not enable
cancel.

## Remaining G5 blockers

**P1 — Same-store wiring is not yet trusted-source proof.** The bridge
constructor receives `identity_port` and `single_worker` separately and
initially checks callable methods.
The later exact-type and object-identity gate is a valuable local wiring check,
but the module explicitly describes it as not a security boundary against
in-process tampering (`backtrader/stores/ctp_i9_managed_dispatch.py`). The exact I9
wheel/source pin, import root, and worker/store pair have not been accepted as
the runtime's trusted dependency. The fake test worker manually receives the
fake identity port;
that does not establish an independently verified production pairing.

**P1 — I9 is still not the end-to-end unique OrderRef authority.** A subsequent
source-only SDK commit `87776bf38bd9b4ac0b9b0963deb074a4996e10a8`
rejects `_ExecutionSession.new_client_order_id()` for a bound/managed CTP
identity before clock, journal, or reservation mutation; the no-session
`BtApi.new_client_order_id()` also rejects an exact CTP venue before the
timestamp fallback. Independent offline review found no P1 in this narrow
allocator cutoff, and its focused tests passed 15. It preserves unbound
legacy CTP sessions. Separately, no-session `BtApi.make_order()` still uses
its legacy `legacy-<UUID>` builder without calling this allocator. An
independent offline composition smoke followed that request through the
actual DirectBackend/FeedAdapter and byte-matched pinned CTP Feed: the
no-session path conveyed no execution capability and raised
`ctp_execution_gate_capability_required` before OrderRef allocation,
RequestID allocation, or native submit (all three counters zero). The pinned
TraderClient also checks its write grant before recording or submitting a
request. This establishes a narrow local fail-closed result for the
no-capability path; it does not test an armed managed dispatch. The
isolated allocator commit is not integrated into an accepted artifact or
default route. At that commit neither the mirror nor the cutoff binds later
orders to I9. Do not report the whole G5 uniqueness gate as closed.

**P1 — I9 request binding is only a source candidate, with spoofable source.**
At the `87776bf` parent and separate `7fe53a0` Feed-Gitlink parent,
`OrderRequest` has no I9 intent/runtime binding: an armed managed fake
transport accepts a valid 12-digit Ref without consuming a reservation.
A separate SDK source-only commit
`decd760012ad77d0c7ddab6400951a28fea16516` (based on `87776bf`,
without the Feed Gitlink) adds an optional nested `CtpOrderIdentityBinding`
and requires managed CTP requests to match the local mirror's exact account,
day, scope, intent, runtime ID and Ref before journal, RequestID or transport.
Nine related contract files passed `403 passed, 2 skipped`; independent review
reran 33 fake cases and confirmed missing or conflicting bindings reject early
while an exact mirror still goes through the existing write gate. Old request
mapping/constructor shapes remain parseable, but an old managed CTP request
without the new binding rejects at dispatch.

At `decd7600`, the consumer still identifies the I9 Store and reservation by
class name and `__module__`, which fake tests can spoof. A separate,
source-only follow-up `5744d3cb98dbbf729078753417a22b6dbfac8cd7`
requires distribution metadata `bt_api_execution==0.2.0` and exact imported
I9 Scope/Store/Reservation classes. An independent 29-test fake review
confirmed that name/module spoofing and missing or wrong-version packages
reject before SDK journal/native/queue effects; a fake Reservation returned
by a reader necessarily incurs that one read before rejection. An isolated
real I9 source compatibility smoke used temporary local version metadata;
it is not a trusted installed-wheel or RECORD/origin proof. Python import
paths, distribution metadata and in-process module objects can still be
replaced by code already running in the process. The default interpreter has
no importable I9 distribution and ordinarily loads CTP from site-packages,
not the child source. Neither source candidate binds the native direct-call
surface or establishes one accepted same-store worker. No reviewed parent
wheel, installed-origin pin or default route includes this binding; it cannot
enable CTP dispatch until those independent gates pass.

The independent review also found no forwarding/wire contract for the new
nested identity: `forwarding/btapi_backend.py` omits it from its native intent
field list and gateway `OrderCommand`, so model `to_dict/from_dict` round-trip
alone does not prove a forwarded managed CTP request retains the binding.
`CancelOrderRequest` has no I9 cancel-action identity in this candidate;
its SDK branch only uses existing tracked-order and write gates. Both paths
need separate fail-closed integration tests before any route is enabled.

An isolated forwarding branch based on `decd7600` adds commits `fbd08485`
and `121675dbabac20dcaf30c924da827a8e1d182a5a`. Because the existing
`OrderCommand`/JSON/ZMQ/receiver chain cannot carry and revalidate the new
identity or an I9 cancel action, the branch rejects **all three** CTP mutation
methods (`make_order`, `cancel_order`, `cancel_all`) before native-intent
mapping, client creation or send, and reports all three capabilities false.
The author ran 152 related synchronous fake tests and independent review
reran 95 relevant tests. A further negative probe exposed a **P1 venue
canonicalization bypass** in this exact revision: `_scope` uppercases without
stripping whitespace, while the write guard checks only exact `CTP`.
`" CTP___FUTURE"` reaches `place_order`, `cancel_order`, and `cancel_all`
through the fake send path and reports the corresponding capabilities true.
The follow-up source commit `c33ce478a5f2557bdc9fc118cd852e8dcef2c187`
normalizes whitespace CTP aliases for the three mutation guards and capability
reporting; 15 alias negative tests and 167 related fake tests passed. A second
independent probe found a broader **P1 receiver route bypass** in that latest
revision: a non-CTP `OrderCommand` such as `UNKNOWN___FUTURE` passes the
client guard and JSON wire, then `OrderRouter.handle_command` dispatches only
by command type to its single configured adapter without comparing the
command venue. A CTP-configured fake adapter received `place_order` and
accepted the command. Direct wire clients can also bypass client-side guards.
The receiver needs a code-owned adapter/venue/account binding or an explicit
CTP mutation deny before this source branch can count as a complete forwarding
no-write boundary. MT5/SIM behavior remained available in the original tests.
No working forwarding CTP route or authority is established.

The subsequent source-only server commits `e6cd73bbddf1875a351c8519f15ece4369fa7284`
and `2fec245ec885589edc337efb144ff86a28a8f518` close the observed
**unbound/router** bypass for declared adapter identities. ZMQ mutation now
needs explicit exchange/market/account scope matching the adapter's static
fields; CTP scopes are write-disabled. Direct `OrderRouter` and embedded
`ForwardingRuntime` default to no writes, reject an enabled but missing scope,
and recheck the scope against the adapter before cache/risk/adapter effects.
The author ran 379 synchronous related tests (18 async skips); independent
exact-commit fake review reran 132 focused tests and 24 ZMQ CTP wire cases,
6 direct Router, 6 embedded runtime, 6 false SIM-scope-on-CTP adapter and
3 cross-account cases with zero adapter calls. Exact SIM/MT5 bound writes
remained positive in fake tests. This is **source-only and conditional**:
`resolve_write_scope` trusts the in-process adapter's self-reported
`exchange_name`/`account_id`; a CTP-capable custom adapter falsely reporting
SIM still accepts commands on a SIM-bound server. There is no code-owned
provider identity or authenticated ZMQ peer proof, and client capabilities
can overstate unsupported aliases. Thus this closes the specific default and
declared-scope bypass, not arbitrary in-process adapter spoofing or G5.

**P1 — The current pinned Feed still has a missing-Ref fallback under an
armed capability.** The parent SDK's no-session `BtApi.make_order()` retains
a legacy direct-backend route, but the gate observation above rejects that
specific no-capability path before native work. At the
exact CTP submodule pin used by this SDK candidate, the current Gateway CTP
adapter rejects direct place/cancel writes. The current CTP Feed is a separate
surface: under a pinned fake managed/armed capability, its `make_order()` still
uses `trader.next_order_ref()` or `_req_id+1` when `client_order_id` is absent.
A pinned fake test confirms that fallback; the native client gate rechecks
account/day/instrument capability but does not bind the OrderRef to I9.
`OrderRequest` only requires a nonempty client ID, and the SDK mirror is not
consulted when that request is dispatched. The Store bridge adds no Feed or
Gateway fallback. Thus Gateway's default hard reject does not prove the Feed
has a unique I9 OrderRef authority.

A current-architecture, source-only CTP child commit
`0609b05afee97d0cde644dac22f5c620aa088ec9` is directly based on the
parent's pinned `ce1edd60785eb4c66fefa16a994a66946a1e068f`. It removes
the Feed's missing-Ref allocator fallback and requires an exact built-in
12-character ASCII decimal `client_order_id` before readiness, RequestID,
native construction, or queue effects. A valid Ref is copied unchanged into
native `OrderRef`. Its focused offline tests passed 218; an independent
review reran the two affected files (14 and 176 tests passed respectively)
and found no regression in that narrow format/passthrough contract. The
original parent candidate `87776bf` still points to `ce1edd`; a separate,
clean source-only parent commit `7fe53a07981ec46c01a0a9993dae124b779435ee`
updates only that Gitlink to `0609b05`. It has no accepted wheel or runtime
pin. Independent review confirms this is an auditable source diff, but the
parent's managed fake transport test still accepts a default valid Ref without
ever consuming an I9 reservation. Ordinary Python import in that review
loaded `bt_api_ctp` from site-packages, not the candidate Gitlink; explicit
source paths were needed to exercise the child source. Thus neither that
fake transport result nor the parent Gitlink proves installed-origin
integration. Format alone does not bind
the Ref to an I9 reservation, account/day/scope, intent, or runtime order ID.
TraderClient's direct insert path and managed cancel require their own
binding and target-provenance checks before G5 can pass.

A newer isolated source-only child `9976bcbbbe331ee77e2d90e05da08472259a625a`
combines the Feed Ref guard with the full Join/Release ancestor chain. A
separate clean parent candidate at
`D:\bt_api_py_codex_ctp_gitlink_9976_20260926`, commit
`6d24217d858bb6ac27ca46ad8a1a13123063d047`, changes only the CTP
Gitlink from `ce1edd` to that child. With exact root/base/CTP source paths,
the child affected fake suite passed 255 tests; parent I9/execution/forwarding
and normalized API tests passed 309 with 2 skips. Ruff, compile and diff
checks passed. This removes the local missing-Ref fallback **in that isolated
candidate**, not in the default pin or installed wheel; its unchanged
`bt_api_execution` Gitlink is an initial commit without the current I9 package.
The result does not prove I9 authority, native Join/Release, cancel target
provenance, provider writes, or default-route acceptance.

The same isolated parent branch then cherry-picked the server scope fixes,
yielding clean HEAD `da2286911a376678c8f22bf8080090d4c4fdbfe2`.
The original forwarding SHAs are not ancestors of this HEAD; `git
range-diff` and patch IDs show equivalent patches as `e35ba7e7`,
`1ebf6817`, `709a2ec5`, `b18db572`, and `da228691` in its ancestry.
With exact root/base/CTP source paths, its expanded parent fake suite passed
469 tests with 21 async skips, and its CTP child focus passed 255. An
independent reviewer verified exact Gitlinks/import origins and separately
reran 18 Feed/callback, 107 Router scope, and 29 parent I9-consumer tests;
all passed. This integrated source candidate still leaves the execution
Gitlink at the old package-empty initial commit, no installed distribution
metadata, no trusted adapter/provider identity, no accepted wheel/native
close, and no default CTP write route.

A further **Gitlink-only** parent candidate at
`D:\bt_api_py_codex_execution_gitlink_b676_20260926`, commit
`c4407b09bb4fd470a3dcb498d56fd0c6034d02c7`, fast-forwards only
`bt_api_execution` from the package-empty `2700cb54` to same-repository
`b676fe666de5373c58ff59bc0b856b7f6d4ce7fd` (`0.2.0` source).
Its `installable=false` flag and default route are unchanged, so it still
provides **no installed distribution metadata** for the SDK consumer. The
I9 source fake suite passed 133 with 2 skips and the CTP child 255; an
expanded parent suite reported 640 passes, 2 skips, and 19 failures. The
same 5 arming failures (old fixtures lack reservation/mirror/binding) and
14 risk API failures (`d0c18a9` lacks `AccountScope`) reproduce before this
Gitlink change. The source-only pin does not cure them. Full I9 package
Ruff still reports 38 findings; targeted worker/callback Ruff, compile
and diff checks passed. No wheel, installed-origin proof, real account
session, or write authorization results from this candidate.
Independent Gitlink review confirmed the one-pointer diff, same-submodule
24-commit ancestry, unchanged installer `installable=false`, clean trees,
and import-from-source focus: 19 I9 store/contract tests, 29 SDK consumer
tests, and 5 installer tests passed. It independently reproduced the 38 I9
Ruff findings. It did not rerun the expanded parent suite, so the 19 parent
failures remain documented baseline failures, not independent full-suite
acceptance.

The earlier source commit `03f0b96` implemented a 12-digit Ref sentinel in an
older, divergent parent tree whose Feed/Gateway files have since moved into
separate base/CTP packages. It cannot be cherry-picked into the current
parent and is not evidence that the current pinned Feed is guarded. Its
constructible marker was never an I9 reservation or authority token, and its
Gateway JSON path lost the Python marker type. The new child candidate above
addresses only the current Feed format/fallback. Managed cancel separately
needs trusted typed provider-order target provenance, whether native
cancellation uses OrderSysID
or OrderRef with FrontID/SessionID.

**P1 — Cancel lacks trusted native target provenance.** The Store bridge
refuses even a structurally exact prepared cancel until the order target is
linked to a trusted typed projection (`backtrader/stores/ctp_i9_managed_dispatch.py`).
That is correct fail-closed behavior, but means the real submit/cancel path
cannot pass G5/G7 yet. A reservation or local queue receipt cannot substitute
for a provider callback or verified target tuple. The future port needs a
code-owned I9↔CTP scope receipt, terminal/current native query provenance,
one uniquely OPEN/PARTIAL row, and a tagged target identity bound to that same
reservation; independently typed pieces without this binding are insufficient.

**P2 — Python support floors differ.** The main repository advertises
`python_requires=">=3.8"` (`setup.py:112`). `bt_api_py` declares
`requires-python = ">=3.11"` (`D:\bt_api_py_codex_orderref_consume_only_20260926\pyproject.toml:11`),
and the bridge intentionally returns unavailable below 3.11
(`backtrader/stores/ctp_i9_managed_dispatch.py:38-49`). A combined runtime
must either narrow/document its supported Python floor or keep the I9 managed
feature unavailable on older interpreters; the project-wide 3.8 claim cannot
be used as evidence that this candidate works there.

**P2 — Fake tests and trusted integration tests need separate expectations.**
The SDK fake fixtures set their classes' `__module__` to I9 module names and
even set the fake authority's module name (`tests/bt_api_contract/test_ctp_orderref_consume.py:24-75,122-148`).
That intentionally tests payload shape and journaling, not code provenance.
Keep the SDK tests as consumer-contract tests, and add a separate offline
integration test using the exact reviewed installed I9 artifact and
same-store worker. The new source-only positive stage/readback smoke is a
useful local compatibility check, not that installed-artifact test. Neither
class-name/module checks nor a passing fake round-trip alone
certifies I9 as the unique authority.

## Minimum next step and disposition

The next slice must repeat the same-store/worker bridge in a clean,
artifact-verified CPython 3.11+ environment, then bind one exact I9
reservation, SDK `OrderRequest`, durable command row, and native request to
the same intent/runtime/ref. An isolated SDK source commit now makes the old
managed CTP allocator reject; independent source review passed, while
artifact-level integration remains. Negative tests must prove different
intent/runtime/ref, store/worker, and restart scopes reject or retain the
same mapping. The current pinned CTP Gateway adapter rejects direct writes,
but its Feed retains a missing-Ref fallback under managed/armed fake
capability. The isolated child source candidate and the separate `7fe53a0`
parent Gitlink candidate guard that fallback in source, but the accepted
artifact and default runtime are unchanged.
Then provide trusted typed order-projection provenance for cancel. Keep this
as fake/offline integration; do not turn it into a real-account run in this
slice.

G5 remains `NOT_PASSED`. There is no accepted same-store trusted source,
SDK/Store intent binding, sole OrderRef allocator, or trusted cancel target.
The no-session legacy path has a narrow local gate proof, but no accepted
armed managed-dispatch proof. No managed CTP route is authorized; retain
`NO_WRITE / LIVE_NO_GO`. This page does not establish an account session,
SimNow order/cancel, or production readiness.

## Later combined source-only candidate (2026-09-26)

An isolated, clean parent worktree at
`D:\bt_api_py_codex_i9_integrated_20260926` now has HEAD `5de97235`.
Relative to `c4407b09`, it updates only the old arming **test fixtures**, the
`bt_api_execution` source Gitlink to `557980724c04e6e172c0dd31c2c932626fd986bd`,
the `bt_api_risk` Gitlink to `dce2c84d3216cdb215f6db7157dda181178260af`,
the `bt_api_monitor` Gitlink to `8498ca7d4f551eff8e7c5ff7deffa418dee5752a`,
and the parent's `runtime_plugins/managed.py` typed risk-freeze resolution.
The CTP child remains the earlier `9976bcbb` source candidate; base remains
`3de0fa4`. The I9 child quality change is import ordering and supported
Python 3.11+ type annotations only: Ruff is clean, its source suite reports
133 passed / 2 skipped, and `compileall` passes. The arming fixtures now
consume a fake typed reservation through the real SDK consumer path before
constructing the request; production guards are unchanged.

With each source import path checked against those exact clean local commits,
the combined parent `tests/bt_api_contract` plus
`tests/test_runtime_fake_dispatch_journal.py`, excluding network-marked
tests and disabling the incompatible local async plugin, reports **1039
passed / 7 skipped**. The arming, OrderRef-consume and recovery focus reports
159 passed; fake dispatch journal reports 15 passed. The risk child suite
reports 159 passed and monitor reports 40 passed. The skipped async tests,
local pytest config warning and missing Windows CTP native extension are
recorded limits, not provider evidence. Before the monitor pointer changed,
its pinned `d515a82` lacked `DurableOutbox`: the 15-test fake journal had 13
composition failures and 2 passes. Before the risk pointer/parent resolver
changed, the 19 parent failures described above remained. These historical
failures are not silently counted as passing on `c4407b09`.

This is still a **source-only candidate**. The execution submodule retains
`installable=false`; the new monitor commit is currently only on a local
branch. The combined parent and child commits have no accepted wheel,
installed RECORD/import-origin proof, shareable remote Gitlink publication,
real TD/MD session, native Join/Release result, or actual CTP submit/cancel.
The cancel bridge still rejects before I9 staging because neither I9 nor CTP
issues, persists and reads back a trusted provider-order target joined to the
reservation. Fake classes can exercise the consumer contract but cannot prove
code provenance or account authority. G5 remains `NOT_PASSED`; default CTP
write and live routes remain `NO_WRITE / LIVE_NO_GO`.

An independent risk review found no route in this typed fake composition to
clear `dispatch-inflight` without the injected journal authority and the
risk gate's claim/proof/fence checks. Independent review of monitor `8498ca7`
ran its durable focus (18 passed) and found no blocker for the current local
outbox producer use: SQLite transactions, idempotent event IDs and scoped
checkpoint rules cover the parent call shape. This does **not** authenticate
monitor control commands: its separate control ledger accepts caller-asserted
issuer and authorization fields, and its outbox consumer offers at-least-once
delivery requiring sink-side event-ID deduplication. The parent fake runtime
currently writes local outbox events only; neither package review grants a
production monitor or account-control authority.

## G5 pre-cancel target projection source candidate (2026-09-26)

The separate clean execution worktree
`D:\work\bt_api_execution-g5-target-projection` is at
`c10ccf5f85f91fedc5407f84b3618d0788076177`. It adds a schema-11
durable projection/consumption contract for one I9 OrderRef reservation and
one pre-cancel CTP order target. The projection binds account, scope, day,
session/connection generations, managed intent, runtime order ID, exact
OrderRef and native query/target fields. Identical scoped query request IDs
are unique; a handle is one-use, same-store and process-local, so restart
requires a fresh query. Stage checks freshness after acquiring the SQLite
transaction lock. Claim rechecks the consumed target after the injected
authority verifier and immediately before transaction commit using monotonic
time. A final check before staging returns rejects an expired target and
rolls the transaction back; claim and built-in dispatch also reject stale
targets before the sender. Local fake tests cover lock delay, verifier delay,
consumption mutation, and stage-internal expiry. An independent review of
parent commit `72ef2a54` found no P1 in its timing paths; `c10ccf5f`
narrows the remaining stage-internal window. This does not establish a
native sender boundary.

Independent review found the remaining trust boundary: the API accepts an
injected `CtpOrderTargetProjectionVerifier`; its digest fields and ID do not
authenticate caller-produced evidence. The default verifier rejects. The
existing native query adapter verifies SDK-owned query provenance and row
readback, but has no independent, same-store I9 reservation-to-OrderRef issuer
or pre-cancel OPEN/PARTIAL target. A fake verifier cannot authorize a real
cancel. An injected asynchronous sender can also delay its actual native
send after the final in-process freshness check. The code-owned native
verifier, trusted sender and default route are absent.

The main runtime now has an unregistered, explicitly rejecting
`CtpTraderClientQueryEvidenceVerifier.verify_order_target` candidate. It
verifies a current account-open-orders query and uniquely matches the
reservation's 12-digit OrderRef, but returns
`native_order_target_projection_source_metadata_unavailable` because its
DTO/boolean query verifier cannot supply trusted I9 session-generation and
query-front/session/source metadata. It does not accept a strategy-selected
client ID, target row, or verifier parameter and never emits a projection.
Its six SDK-free fake tests and focused Ruff check passed independently.
These tests do not establish a real SDK query or native OrderRef authority.

Root independently reran the child package: **141 passed, 2 skipped**; focused
Ruff F/I passed. The separate clean source-only parent integration
`D:\bt_api_py_codex_i9_g5_integration_20260926` now pins that child at
`097a98a7`; its non-network contract and fake journal suite reports
**1039 passed, 7 skipped, 7 warnings**. The warnings include the existing
pytest configuration warning, absent Windows CTP extension in the clean
source tree, and async skips. This is not a wheel/RECORD/import-origin proof,
native session, provider acknowledgement, accepted cancel target issuer, or
write admission. **G5 remains NOT_PASSED; NO_WRITE / LIVE_NO_GO.**
