# 007 SimNow 33-case staging acceptance record — 2026-09-28

**Status:** `STAGING_ONLY / NO_WRITE / LIVE_NO_GO`
**Evidence boundary:** Offline configuration and entry-contract checks plus one credential-free TCP front-reachability probe. No SimNow session, provider login, market-data subscription, CTP SDK import, or trading write is evidenced here.

## Staging inventory and offline checks

The current tree contains 33 case directories at
`examples/007_ctp/live_certification/simnow_penetration/cases/<ID>/`. Each has
`config.yaml`, `<ID>_strategy.py`, and `run.py`. The per-case configuration is
scenario configuration; it does not carry account credentials. The strategy
files state intended real actions and required evidence. They do not implement
provider execution. The case-local `run.py` files delegate to
`managed_case_entry`; the historical flat `cases/*.py` files remain closed
source.

The suite-root protected `config.yaml` was prepared from the 013_3 protected
configuration by rebinding only `strategy.id` to
`example.007_ctp.simnow_penetration`. It remains Git-ignored and protected;
the suite-root config and runtime-directory ACL match the 013_3 private
directory. Its contents and front addresses are intentionally not reproduced
in this record. The current inventory has 17 registrations, including a 007
zero-write `simulation/sandbox` runtime/front-check route. This is not a
certification case runner, trading runner, or write authorization.

Root's final offline check verified all 33 case configurations with
`backtrader_runtime.config.load_runtime_config` without registry resolution:
schema-v4 `simulation/sandbox`, `secrets_ref: none`, and zero private blocks.
All 33 new case directories have exactly the three requested files; their
33 strategy-plan files have no fixture, fake, local-replay, or seed-bar
references. The historical flat case sources are separate and closed.
The check did not expose configuration contents. Root also ran each of the 33
case entry scripts in an individual child process. Every result was exit code
2, `status=BLOCKED`, `reason=managed_ctp_certification_not_registered`, with
`network=0` and `order_write=0`. Therefore the verified counts are 0 real
`PASS`, 0 real order writes, and 0 real cancel writes. These are offline
fail-closed entry results, not SimNow case runs or provider evidence.

The root-reported combined focus across six relevant runtime test files
passed 176 tests, skipped 13, and reported one existing pytest-configuration
warning with `-p no:asyncio`. The run was fake/offline contract testing; it
does not establish TCP, provider, account, or trading behavior. The latest
`tests/unit/live_certification` run passed 170 offline tests with the same
configuration warning. The `runtime_not_registered` doctor result predates the 007 route
registration and is superseded by the current status below.

After adding the 007 read-only registration, a full `tests/unit/runtime`
regression initially found four local failures: a test still expected the
frozen R5 worker hash instead of the recorded overlapped-I/O successor, one
synthetic registry clone included an unrelated private binding, the offline
smoke selector assumed only one private CTP route, and the new suite-root
`secrets.yaml` ignore rule was missing. The test now verifies both frozen
source identities through the preserved manifest, the clone and selector
recognize the exact 007 binding, and the ignore rule is present. The full
runtime suite then passed **2,118 tests**, skipped 30, and reported 2 expected
failures with one existing pytest configuration warning (108.83 seconds).
This is offline regression coverage, not provider or account acceptance.
The separate offline smoke command skipped both private CTP read-only routes
and the public shadow route before loading their configs, as designed. Of its
14 eligible offline runtimes, 12 passed and two managed L2 replay runtimes
returned `capability_dependency_missing` for `bt_api_execution` in the current
Python environment. No package was installed to mask this result, and the
smoke run is not counted as fully passing.

## Current 007 read-only route status

The suite-root offline `bt-runtime doctor` exited 0 with
`provider_preflight_started=false`, reports 5 configured front pairs, and
reports `preflight_available=false`. Ordinary provider `preflight` remains
fail-closed pending a bounded Windows Job supervisor and independent
acceptance. Separately, on 2026-09-28 root explicitly ran
`bt-runtime check-ctp-fronts` against those configured pairs. It exited 0 with
`status=selected`, `reason=selected_configured_pair`, and selected index 3;
both MD and TD had 3/3 TCP successes at index 3, while indexes 0, 1, 2, and 4
each had 0/3. The probe was credential-free and reported
`tcp_probe_only=true`, `sdk_imported=false`, `provider_login_started=false`,
and `trading_writes=0`. This is an immediate transport observation from this
host on this date, not a durable front guarantee or evidence of CTP login,
market-data subscription, settlement, order, or cancel behavior. The
registered 007 route is code-connected for zero-write sandbox configuration
and front checking only; it does not execute certification cases or submit or
cancel orders.

## Subsequent case and gate work (still unaccepted)

The unregistered `managed_case_scope.py` now binds one of the 33 exact case
identities to the sealed suite runtime and records digests of that case's
`config.yaml`, static `<ID>_strategy.py` plan, and `run.py`. The new
`common/case_engine.py` parses all 33 plans without importing or executing
them; it separates provider callbacks from runtime intents, monitor records,
local validation, and external controls. Its strongest result is
`REVIEW_REQUIRED`, never certification `PASS`. Focused scope and engine tests
passed 27 cases. Re-running the actual 33 entry scripts after these edits
still yielded 33 `BLOCKED`, 0 unexpected results, and 0 real `PASS`.

The unregistered typed decision engine defines an explicit intent and
observation rule for each of the 33 cases. A diagnostic converter binds its
plan digest to the sealed case/runtime digests. Without a trusted observation
authenticator it remains `BLOCKED`; with a test-only verifier it can reach only
`REVIEW_REQUIRED`, with `dispatch_permitted=false` and certification
`PASS=false`. The scope/case-engine/decision-engine focus passed 38 offline
tests. There is no production authenticator or provider execution adapter.

The unregistered pure-data `common/completion_invariants.py` adds 33-case
closure checks for canonical scenario/provenance evidence, managed request
receipts, native order/trade lifecycle, and final order/position/account query
snapshots. Missing scenario evidence keeps all 33 cases below review; order
cases also require terminality, request/trade quantities, no remaining open
orders, and coherent position/funds observations. B01 partial orders, B02
cancel/fill races, repeated-order thresholds, and external error/emergency
conditions have explicit negative branches. Its maximum result is
`REVIEW_REQUIRED` with `certification_pass=false`,
`dispatch_permitted=false`, and `source_authenticity_verified=false`. The
case/decision/completion focus passed 45 synthetic tests; the full
certification unit suite passed 170. The 33-ID negative loop checks only that
missing scenario evidence cannot advance to review; it does not exercise all
positive and negative paths for every case class. Independent QA found and
the author fixed missing cross-checks for trade/order external IDs and
managed submit quantities. Accepted and partial facts now conserve
`traded + remaining`, filled facts require full submitted quantity, and
canceled facts retain a separate trade-callback check. It cannot authenticate in-process
callbacks or prove provider/account ownership, and cash, fee, and margin
effects after fills require independent review. It is not registered or used
by the 33 entrypoints.

A subsequent independent read-only pass found an ordinary order case could
still end in a provider `REJECTED` fact after earlier acceptance. The checker
now marks such a terminal rejection contradictory for required-order cases,
while preserving the explicitly expected E01/E02/E03/EM01 remote-rejection
paths. A synthetic partial-fill-then-cancel example confirms that matching
trade quantity and signed position change can still reach only
`REVIEW_REQUIRED`. These narrow checks remain unauthenticated source-shape
contracts; they do not prove the real terminal sequence or account delta.

The historical reconciliation table was corrected so E03 and EM01 require
an order request, B01 requires actual trade activity, and cancellation cases
can carry a reconciled fill race. B01's derived `partial_count` no longer
accepts an event-name set, caller-supplied count, or local partial label;
distinct sourced CTP partial-order callbacks are needed. These are local
evidence contracts, not authenticated provider records.

The legacy SimNow evidence reader also stopped accepting caller-supplied
labels and unsourced local disconnect/reconnect logs as provider facts. It
requires stronger order/position snapshot and trade reconciliation shape.
Unsourced error, emergency-control, and repeat-order events are rejected
because the legacy JSONL reader cannot verify the corresponding provider,
monitor, or control-plane origin. This prevents a local log from being
reported as a real case pass; it does not create real evidence.

The legacy `CaseTimer.pass_result()` now returns `FAIL` without a trusted
post-reconciliation evidence adapter and cannot derive certification events or
fields from caller-controlled details. `CaseResult.to_dict()`,
`CaseResult.exit_code()`, and `save_result()` also demote a hand-built or
mutated `PASS` before export, process exit, or persistence. The full
`tests/unit/live_certification` rerun passed 170 offline tests, including these
negative cases. Root then reran all 33 individual `run.py` entrypoints:
33 returned `BLOCKED` / exit 2 with zero network and order-write requests;
there were no unexpected results or real passes.

The unregistered G1 inert Job candidate now reserves at least 0.5 seconds
between worker stop and whole-command deadline; its two focused test lanes
passed 10 and 23 cases. The synchronous native/OS boundary remains unbounded,
so ordinary preflight stays closed. The managed CANCEL verifier now requires
a fresh account-wide G5/V21 ActionRef mapping and native-floor snapshot at
claim and final recheck; absent a trusted producer, it rejects. Its focused
and adjacent fake/offline run passed 48 cases and skipped 4. Independent review
found that a newer epoch could regress the earlier ActionRef floor or mapping,
and that CANCEL target fields were not required to match its logical payload.
The verifier now rejects these changes within one process and requires exact
target-field equality; the adjacent rerun passed 54 cases and skipped 4.
Source digests are still syntax-only and the verifier's epoch memory does not
survive restart. With no trusted producer, this remains contract-only and
cannot authorize CANCEL. The unregistered I9 session candidate now requires
final native-call admission before constructing a CANCEL field; the
dependency-free negative/ordering focus passed 2 tests. Its three SDK
source-root integration cases were skipped and are not counted as passing.
The local fake
AccountActor remains isolated from production imports (one focused test
passed); it is not an external account writer fence or a coherent snapshot.

An isolated G4 rebuild produced matching A/B wheel bytes for the base, CTP,
and parent packages and verified installed wheel payloads, hashed `RECORD`
rows, and wheel-bound `direct_url.json` in two clean virtual environments.
This is a reproducible artifact candidate only: its parent wheel used a
156-file hash-bound composite source snapshot that differs from the clean
parent Git checkout (7 matching, 55 different, 94 missing files), the base
and CTP hashes differ from existing code pins, and there is no code-owned
parent pin. No SDK/native load was intentionally run, and no native lifecycle
or provider session was accepted. G4 remains `NOT_ACCEPTED`; the candidate
does not change 007 routing or permit an order or cancel.

A second isolated G4 candidate rebuilt all three wheels twice from a clean
parent Git checkout, and the wheel bytes and two offline installed RECORD and
direct URL inspections matched. That clean parent builds as `bt_api_py 0.15`
and its archive lacks the managed authorization modules required by current
CTP source; it also carries its own native CTP payload. Its build used a
temporary NumPy include shim and its new CTP `.pyd` differs from the existing
pin. This removes the composite-source mismatch for that candidate but does
not make it a compatible parent package or close G4. No native lifecycle was
run and default pins remain unchanged.

A follow-up static compatibility audit of that clean `bt_api_py 0.15` source
found that five parent module paths needed by the current managed CTP client
and request builder are absent, including credential binding, execution
authorization, runtime plugins, contract DTOs, and the reservation mirror.
The request builder also requires `bt_api_py 0.15.5`. The earlier 156-file
composite source differs from the clean parent in 55 files and lacks 94 clean
counterparts; its central `BtApi` file is substantially expanded. A small
import-stub patch would not supply those contracts. The isolated report at
`D:/temp/iteration41-g4-parent-compat-gap-analysis-20260928` records the
static comparison and checksums. No compatibility patch/wheel was produced;
G4 remains `NOT_ACCEPTED` pending a clean compatible source and native tests.

Native CTP `SettlementInfoConfirm` rows contain `ConfirmDate` and
`SettlementID`, but no `TradingDay`. The unregistered TD readiness helper now
rejects a confirmation-only query and invokes owner cleanup. A separate
offline dual-query shape candidate joins `SettlementInfo.TradingDay` and
confirmation by account and `SettlementID`; it does not attest SDK source or
enable settlement readiness. An unregistered typed pair-port contract now
requires both query results, post-close request-ID readback, and a complete
native stop receipt. The currently pinned child SDK exposes typed confirmation
query but lacks the matching high-level SettlementInfo query and callback
archive; its confirmation verifier treats `ConfirmDate` as a possible
`TradingDay`, which cannot establish the session's settlement day. The latest
four-file focused readiness/query run passed 41 tests and skipped 1. These
changes leave the G6-S and G7-S real-provider gates closed.

An isolated G6-S SDK source patch candidate adds typed SettlementInfo query
archival and removes the `ConfirmDate` fallback, but its baseline is an
already-dirty child SDK working file; three AST checks and syntax compilation
do not prove the native ABI, real callbacks, close behavior, or the dual-query
join. It was not applied to the pinned SDK or connected to 007 readiness.

A separate unregistered, read-only MD tick bridge passed 21 fake-source
tests. It validates an already-owned stream's lease, selected front/account,
instrument, generation, subscription and first-tick watermarks, and poisons
on stale or mismatched ticks. It does not create a Feed or native client.
The current pinned child has a public MD identity, but its public tick callback
does not carry callback-bound generation or sequence and its subscription
callback drops native request ID and terminal flag. The managed owner therefore
cannot yet supply the bridge's required stream provenance; no live Feed is
connected to a 007 strategy.
The [pinned child subscription source audit](ctp-md-subscription-ack-correlation-source-audit-2026-09-28.md)
confirms that native `SubscribeMarketData` accepts no caller request ID. Its
callback exposes `nRequestID`, but the high-level wrapper discards it and
the source does not tie it to a particular request or connection generation.
A single-pending-instrument Python policy could limit ambiguity but cannot
be treated as provider-authenticated ACK correlation.

An isolated broker-session adapter candidate at
`D:/temp/iteration41-007-managed-broker-session-adapter-r2-final3` projects
bounded local SUBMIT/CANCEL request shapes and correlates already-observed TD
status, but its `submit` and `cancel` methods always reject before approval
issuance or session/native dispatch. Its 15 fake tests passed. Independent
static QA verified the candidate's 13-file checksum sidecar, manifest, and
ten bound main-source preimages. The adapter has no direct provider query or
write path; an arbitrary injected `query_evidence_verifier.verify()` could
have side effects, so that static conclusion applies only to the adapter's
own call path and the pure test fake. The candidate is not installed in the
repository or connected to a 007 runner. It does not close G1/G4/G5/G6 or
enable real orders.

An offline `bt-runtime run --strategy-dir <suite-root>` safety check returns
exit 2 with `profile_dispatch_unavailable` and
`diagnostic.provider_preflight_started=false`. The newly registered 007
read-only route has no runner; this rejection is separate from the retained
local replay runtime at `examples/007_ctp/runtime`.

## Route and front boundary

The 013_3 selected-front facility remains a private read-only route. The 007
zero-write runtime/front-check route is now separately registered and
code-connected. The one recorded TCP probe selected configured pair index 3
for this host and time only. It does not establish CTP login, market-data
subscription, TradingDay settlement, orders, or cancellations. 007 still has
no certification case runner, real-trading runner, or write permission.

Selection checks only the sealed 1–8 configured MD/TD pairs. With three
samples per endpoint, both endpoints need at least two successful TCP
connections. Each eligible pair scores the larger of the MD and TD successful
sample median latencies; the lowest score wins, with configuration order as
the tie-breaker. A single reachable address is insufficient, and the selected
whole pair is passed unchanged. The selection does not test native login or
trade permission.

SimNow's 7x24 label does not establish account settlement readiness. The current
acceptance matrix requires actual account and TradingDay settlement evidence
for G7-S and records the current G7-S result as `NOT_RUN / NO_WRITE`. No case
below may replace a missing external condition with a local fixture, fake,
synthetic market event, hand-filled log, or TCP success.

## Per-class real acceptance evidence and external dependencies

The rows describe evidence the planned case would need in a future reviewed
managed route. They are requirements, not claims that any case has run.

| Class / cases | Required real evidence | External condition and limits |
|---|---|---|
| **C01 — authentication/login** | Native authentication/login callbacks with exact request IDs, ErrorID, locally captured arrival order/time, and login callback FrontID/SessionID/TradingDay; clean stop; zero order/cancel requests. The auth callback has no native front/session/day or provider timestamp/sequence. | Valid account/authentication and real MD/TD session callbacks. A TCP probe or local lifecycle event cannot prove login. |
| **T01–T03 — open, close, cancel** | For each request, trace ID, exact request/order references, provider acceptance and terminal callback, fill/cancel state, and before/after order, position, and funds reconciliation. T02 also needs a confirmed closeable position; T03 needs a still-cancellable accepted order and its cancel acknowledgement. | Approved account, instrument, quantity, market state, budget, and provider acceptance. Open/close may change positions or funds; every remaining order must be reconciled. |
| **M01–M03 — connection status** | Native MD/TD connection and readiness callbacks with locally captured arrival times and actual session transitions. M02 requires evidence of the disconnect source. M03 requires a genuine reconnect transition with session/generation identifiers and restored readiness. | Real session and, for M02/M03, a controlled real disconnect/reconnect condition. Calling local `stop()` or observing TCP reachability alone does not prove transport-loss detection or recovery. |
| **M04–M05 — request counts** | Monitor events whose order/cancel counts reconcile to real provider request references and locally captured callback times; final open-order reconciliation. | Actual bounded order/cancel requests accepted through the reviewed route. Market movement and fills remain possible; count-only local events are insufficient. |
| **O01–O03 — repeated requests** | Real repeated-intent key, threshold/window, count, timestamps, and corresponding monitor/risk event; per-order/cancel outcomes and final reconciliation. | The duplicate intent must be genuinely repeated within the configured window. Requests can reach the counter; quantities must be bounded and all resulting orders/fills reconciled. |
| **TH01/TH03/TH05 — threshold settings** | Runtime-resolved effective threshold values and a real monitor summary. TH05 also requires the effective repeat window. No order activity is required for these setting cases. | Managed runtime must actually load the setting and emit its summary. A YAML value by itself is not runtime evidence. |
| **TH02/TH04/TH06 — threshold alerts** | `risk_threshold_triggered` with effective threshold and observed count; TH06 also needs repeat key/window/count; correlate the alert with provider-backed request references and reconcile all orders. | Actual bounded request activity is required to cross the configured threshold. Synthetic counters or fabricated alerts cannot prove this behavior. |
| **V01–V03 — validation** | Broker-originated validation rejection tied to the submitted instrument, tick, or maximum-size evidence; prove rejection occurred before provider dispatch and that no order remains. | Current contract metadata and limits must have an authoritative source. Injected `contract_metadata` may exercise local code but cannot establish real-contract facts or count as provider acceptance. |
| **E01–E03 — counter errors** | Correlated remote `order_reject_remote`, counter `ErrorID`/`ErrorMsg`/`StatusMsg`, request references, timestamped source callback, and final order/fill/account reconciliation. | E01 needs a genuine insufficient-funds condition; E02 a genuine insufficient-position condition; E03 a naturally occurring counter-reported market-state rejection. These conditions and messages must not be synthesized. A 7x24 endpoint does not guarantee settlement or any of these rejections. |
| **EM01–EM03 — emergency actions** | EM01 needs evidence that account trading permission was actually restricted and a subsequent request was denied. EM02 needs the real pause command/state transition, strategy identity, and proof that later callbacks/new requests stopped. EM03 needs an external logout/session-termination acknowledgement, resulting disconnect, and proof that new requests stopped. | EM01's broker-local `disable_trading()` is not account-level permission evidence. EM03's local `stop()` or a changed boolean is not proof of external forced logout. EM01 and EM03 require the corresponding authorized external control; these conditions cannot be fabricated. |
| **B01–B02 — batch cancel** | B01 requires provider execution reports showing each targeted order is genuinely partially filled (`filled > 0`, `remaining > 0`), then batch-cancel requests and per-order terminal cancel/remainder callbacks. B02 requires multiple accepted working orders and per-order cancel acknowledgements. Both require trade, position, funds, and no-open-order reconciliation. | Active market liquidity, real partial/working states, bounded accepted orders, and exact order-reference mapping. B01's partial-fill state cannot be supplied by a fixture, a status label, or an assumed fill. |
| **L01–L04 — logging** | L01 correlates real request, order, fill/trade IDs, trace, and account deltas. L02 ties local startup/stop records to native connect/login/ready callbacks. L03 ties monitor metrics to their source events and request counts. L04 retains the original typed error callback, source classification, locally captured time, and correlation ID. | Real provider callbacks and runtime logger output. L01 requires actual fills; L03 requires the observed monitor inputs; L04 must distinguish a local validation rejection from a counter rejection. Hand-authored log entries are not evidence. |

## Acceptance gates

The following gates have not passed for this 007 certification work. The current
matrix remains authoritative for full gate definitions and evidence:

| Gate | Current disposition | Blocking boundary |
|---|---|---|
| **G1 — whole-command deadline supervision** | `NO_GO_IMPLEMENTATION_FOR_CURRENT_G1_WORDING` | No accepted hard deadline covers whole command creation and cleanup. |
| **G4 — exact native artifact/pin** | `NO_EXACT_PIN_REBUILD / NO_G4` | No accepted exact pin, trusted three-package install chain, or native lifecycle acceptance. |
| **G5 — ActionRef authority** | `NOT_ACCEPTED` | Local/fake contracts do not establish one trusted account-wide allocator, native floor, or provider duplicate-action evidence. |
| **G6-P — external account actor** | `BLOCKED` | No trusted deployed external AccountActor with account-wide identity, writer fence, and common account snapshot was found. |
| **G6-S — SimNow TD/MD readiness** | `NOT_ACCEPTED` | No callback-correlated MD stream, authoritative settlement TradingDay join, or accepted native close lifecycle. |
| **G7-S — minimum real SimNow order/cancel** | `NOT_RUN / NO_WRITE` | Requires G0–G5, G6-S, actual TD/MD/native lifecycle, and account/TradingDay settlement readiness before any bounded request. |

G7-S cannot be inferred from
front selection, a 7x24 label, a TCP result, an offline test, or this staging
record. Until the required gates and evidence are independently accepted, the
suite remains `NO_WRITE / LIVE_NO_GO`.

## Later 2026-09-28 continuation: typed case logic and independent review

All 33 case strategy files now contain unregistered, read-only typed observation
logic while retaining their static plans. The common decision, case, and
completion contracts can reach at most `REVIEW_REQUIRED`; they cannot attest
source authenticity, dispatch, or certification `PASS`. The case-local
`run.py` files still call the fixed fail-closed staging entry. A fresh
individual-process run of all 33 returned 33 `BLOCKED` / exit 2 with reported
network and order-write counts zero. **Real SimNow acceptance remains 0/33.**
The same 33 individual entries were rerun after the later candidate fixes:
all again returned the expected `BLOCKED` / exit 2, with zero reported
network/order-write requests and zero real `PASS`.

Independent review found source-shape contradictions that previously reached
review state. The common checks now reject M02/M03 query/callback sequence
inversion, same-generation restoration, and mismatched control receipts;
managed submit/cancel receipts outside the before/after account snapshot
window or after corresponding native callbacks; C01 login before
authentication or account queries before login; L01 trade-log fields that
disagree with native trade facts; and mismatched EM01/EM02/EM03 external
control references. V01/V02/V03 now require an actual unknown-instrument,
off-tick-price, or above-limit-size condition from supplied reference facts,
with historical and typed field aliases agreeing. V02/V03 bound decimal
shapes before exact arithmetic. TH04 now counts unique
dispatched submit and cancel request IDs against a combined threshold and
checks config, monitor, request, and native-event references. These remain
pure-data or synthetic-verifier checks; they do not authenticate a real CTP
source or grant execution.

A later independent negative probe found that O01 accepted a different-contract,
ten-year-old, or semantically rejected/negative-quantity supporting order;
T01/B01 accepted managed submit receipts naming another contract, and T01
accepted stale or cross-account synthetic evidence. The unregistered typed
candidate now checks provider session/day/generation, occurrence time, native
order status/quantity, contract correlation, and account fingerprint across
native events, authenticator receipts, and managed receipts. The common order
candidate checks a caller-supplied evaluation time, contract identity across
subscription/tick/managed/native facts, and a scope-bound account fingerprint
across submit and six baseline/final query families. Missing sealed case-scope
identity or a trusted event authenticator leaves the current production
candidate `INCOMPLETE`.
An independent post-fix synthetic rerun closed all 12 recorded negative
probes by record rejection or `INCOMPLETE` (36 focused tests passed); see
`D:/temp/ac41-007-read-only-candidate-qa-after-fix-20260928/after-fix-report.md`.
The 007 case-scope binder now derives a scheme-marked pseudonymous account
digest from the already validated in-memory sealed CTP config, incorporates
it into a v2 case-scope hash, and passes it to `DecisionScope`. The binder
rejects hand-built/replaced scope objects in this process. The digest is an
unkeyed, potentially guessable logical-account identifier, not a provider
signature, credential-version proof, or writer authority. The binder uses no
separate case credential copy. Its dedicated synthetic tests passed 13, and
the full live-certification suite then passed 320. The later 007/static runtime
focus passed 48. The 33 individual entry points still all returned BLOCKED.

At this checkpoint, `tests/unit/live_certification` passed **320 tests** with
one pre-existing pytest configuration warning using `-p no:asyncio`; broad
Ruff checks passed for the suite's common modules and certification tests.
The full `tests/unit/runtime` rerun passed **2,124**, skipped 30, and xfailed
2 after relocating a typed helper outside the historical flat `cases/*.py`
directory; the count there remains exactly 33. `tests/unit/stores` passed
**742** and skipped 13, and `tests/unit/brokers/test_btapibroker.py` passed
**149**. These are offline regressions, not provider runs.

The G4 audit located the exact old pinned base and CTP wheels and matching
clean source commits. A clean `bt_api_py 0.15.5` parent wheel and those pinned
base/CTP wheels passed isolated static installation `RECORD` and source-link
checks. A later isolated run closed 38 dependency wheels from a pre-existing
local wheelhouse, passed `pip check` and 5,416 hashed installed dependency
`RECORD` rows, and imported the pinned CTP `.pyd` with its expected hash.
One urllib3 import-time local IPv6 `socket.bind` probe was blocked by a Python
audit hook; that hook does not cover native Winsock. No client was constructed
or native lifecycle or provider session run. The original CTP wheel build
recipe is not reproduced. G4 remains `NOT_ACCEPTED`; see
`D:/temp/iteration41-g4-pin-parent-abi-check-20260928/REPORT.md`.

An independent G1 audit confirmed the strict whole-command hard deadline
does not cover highest-level synchronous Windows service and OS calls. The
ordinary preflight route remains closed. A separately scoped deadline for a
request inside a protected, already-running service is a possible new
contract, but it would need an explicit acceptance change and its own tests;
it is not a G1 pass. An isolated Windows Job prototype for that narrower
already-READY request boundary passed 8 inert tests with a single absolute
deadline and `UNKNOWN` on timeout or cleanup ambiguity. It did not exercise
native calls and cannot bound the highest-level service call or scheduler;
see `D:/temp/ac41-g1-request-boundary-prototype-20260928/README.md`.
No real CTP order or cancel has been accepted.

The separate G6-P review reproduced 56 isolated fake account-actor tests:
one winner under same-local-database contention and fail-closed freeze after
writer crashes. The current local lock, SQLite journal, and injected
`writer_fence` do not attest an external authority, exclude other hosts or
manual terminals, or prove a common-version provider snapshot across account
queries. G6-P remains blocked; see
`D:/temp/iteration41-g6p-account-actor-review-20260928/G6P-MIN-SERVICE-BOUNDARY-REVIEW.md`.

The G5 source audit confirms that the checked CTP 6.7.7 login response
exposes `MaxOrderRef`, not an ActionRef maximum; `OrderActionRef` is a
separate cancel field, and the checked API exposes no `ReqQryOrderAction`.
The G5 and V21 local allocators can each allocate ActionRef 1 for the same
synthetic account. Current G5 snapshot verification has no authenticated
issuer or durable account-wide floor. A single externally fenced account
actor and canonical durable ActionRef ledger remain prerequisite to a real
cancel path; see
`D:/temp/iteration41-g5-actionref-trusted-producer-gap-20260928/DESIGN.md`.

Isolated G6-S source candidates now preserve MD subscription ACK callback
request ID, terminal flag, instrument, connection generation, and the first
matching post-ACK tick (4 fake tests), and separately collect SettlementInfo
and SettlementInfoConfirm query envelopes under one session identity (17 fake
tests). `SubscribeMarketData` has no caller request ID, so the MD candidate
permits only one submitted instrument per client lifetime; the callback ID
is not used as a caller correlation token. The checked settlement confirmation
row has `ConfirmDate` but no `TradingDay`; the existing high-level SDK helper
falls back to ConfirmDate, while the repository's TD trading-readiness gate
already rejects confirmation-only evidence. The isolated SDK copy now makes
that old single-query helper fail closed and clear readiness/grant state;
the pinned SDK itself is unchanged. Neither isolated candidate has
native/provider acceptance, durable authenticated source ownership, or a
registered route. See `D:/temp/ac41-g6s-md-callback-archive-20260928/README.md`
and `D:/temp/g6s_settlement_dual_query_candidate_20260928/README.md`.

## Further 2026-09-28 independent real-path audit

The exact 007 protected suite config is present, and the previously recorded
credential-free front check observed one reachable configured whole MD/TD pair.
An independent source/deployment audit found no executable **007 real read-only
probe** under the current gates: ordinary `preflight` rejects before config or
SDK access, the candidate guardian worker and output binding are fixed to
013_3, its protected deployment/pins and service are absent, and strict G1
remains `NO_GO`. The pinned SDK client also imports order/cancel modules on the
nominal read-only path, so it cannot be described as a query-only import
surface. The audit did not read protected values or start a native session;
see `D:/temp/iteration41-007-real-readonly-probe-audit-20260928.md`.

A follow-up exact-pin import audit confirmed that the `bt_api_ctp` package
eagerly imports the full Trader API and a single generated `_ctp` extension
exports `ReqOrderInsert` and `ReqOrderAction`. A Python facade over that wheel
cannot constitute a query-only native/API boundary. The proposed remedy is a
separately generated, allowlisted native extension and separately routed
query-only client/package; `ReqSettlementInfoConfirm` must remain excluded as
a state-changing request. Sixteen static assertions and a fresh-process import
probe passed, but no restricted wheel or native client was built in that audit;
see `D:/temp/ac41-007-query-only-sdk-boundary-20260928/REPORT.md`.

An independent C01 source-contract audit found that the present read-only
result preserves generation/day and digest summaries, but loses the individual
TD authentication/login callbacks and their request IDs, plus per-query raw
facts needed for distinct baseline/final snapshots. No lossless adapter to C01
exists; its static missing-contract guards passed 5 tests. The checked CTP
`OnRspAuthenticate` callback itself has no FrontID, SessionID, TradingDay,
timestamp, or provider sequence; those values must not be invented or labeled
as native auth fields. SDK callback archive and source-attributed C01 schema
candidates are being developed in isolation. See
`D:/temp/ac41-c01-readonly-adapter-contract-r1-20260928/README.md`.

The 33-row real-case feasibility audit classifies 10 cases as requiring a real
read-only session, 10 as requiring bounded managed actions, and 13 as also
depending on external account controls or genuine market outcomes. Every case
remains `BLOCKED`. B01 and B02 require at least two simultaneous working orders,
contradicting the current one-live-order limit. B01 further requires positive
filled **and** remaining quantities on each of at least two orders; with
integer futures lots, each such order needs at least two lots, contradicting
the present one-lot per-order and gross-position limits. No default limit was
changed. See `D:/temp/ac41_007_real_case_feasibility_20260928.md`.

An independent legacy-entry audit found no reachable bypass in the checked-in
007 scripts: the flat entrypoints stop before Store construction and the new
33 `run.py` files return `BLOCKED`. Guarded legacy tests passed 26 selected
cases, managed-entry tests passed 8, and 33 separate child-process entries all
reported `BLOCKED` with zero reported network/order writes. This is static and
local-test evidence only, not real provider or write acceptance.

The independent native order/cancel/trade adapter audit found no lossless 007
adapter in the inspected SDK source. Order and trade callbacks enter separate
volatile queues without a shared callback-bound sequence, capture time,
generation envelope, event ID, or durable artifact. The active client does not
capture cancel-response callbacks; an isolated candidate's action response
only acknowledges the request and cannot prove terminal cancellation. Query
rows cannot be renamed as `OnRtnOrder` or `OnRtnTrade` callbacks. Therefore no
adapter was emitted and G7-S remains `NOT_RUN / NO_WRITE`; see
`D:/temp/ac41-007-native-callback-adapter-audit-20260928/README.md`.

An isolated G1 integration exercised the repository's actual outer watchdog
and Windows Job backend around a fake service worker: 4 Windows test methods,
16 normal/fault scenarios passed. A stalled outer watchdog made the caller
return `UNKNOWN` **after** the strict deadline, and the caller could not
independently observe the lost watchdog's Job-empty/native-close facts. This
does not satisfy the current whole-command G1 wording. The proposed
already-READY request deadline is a different, still-unaccepted contract;
neither the CLI nor acceptance matrix changed. See
`D:/temp/ac41-g1-whole-command-inert-20260928/README.md`.

The clean SDK MD login source passes its connection generation as the native
`ReqUserLogin` request ID; the SWIG wrapper preserves that integer in both
directions. An isolated fake callback with ID zero after request ID one was
correctly rejected without marking login complete or reading account identity.
The historical real callback ID zero therefore remains unexplained; the
checked source does not justify accepting zero or attributing it to the vendor
without process-mapped module and callback evidence. See
`D:/temp/g6s-md-login-path-audit-20260928/`.

A further isolated SDK candidate captures authentication, login, and all seven
read-only TD query callback families with native request ID/ErrorID/IsLast and
explicitly local arrival time, sequence, and baseline/final round labels.
Seven fake tests passed. Authentication callback front/session/day fields stay
unset because the vendor callback does not provide them. The archive is
volatile and is not connected to the one-pass, digest-only main preflight;
it cannot yet provide C01 values or source authentication. See
`D:/temp/ac41-g6-query-callback-archive-candidate-20260928/CANDIDATE-REPORT.md`.
Independent QA reran the seven fake tests and confirmed the source/field
attribution, but found that normal generic `OnRspError` for auth/login is not
archived, the row-digest redaction list omits BrokerID/UserID, and fake tests
do not exercise the patched client wiring. The current C01 schema still
requires provider session/day/front on the pre-login auth callback, which the
vendor row cannot provide. See
`D:/temp/ac41-g6-query-callback-archive-independent-qa-20260928/QA-REPORT.md`.

The separate order/trade callback archive prototype passed four fake tests
and independent QA confirmed its local stale-generation/session rejection.
QA also found that its records omit a poison/completeness marker, a bad
capture does not itself revoke client readiness or a write gate, and the
prototype was built against the older `bt_api_py` layout rather than the
clean pinned `bt_api_ctp` source. It supplies no durable/source-authenticated
007 evidence or G7-S acceptance; see
`D:/temp/ac41-007-native-callback-archive-independent-qa-20260928/report.md`.

The main-tree, unregistered `managed_case_invocation.py` now binds an issued
case scope to a freshly revalidated sealed runtime, one configured MD/TD pair,
the full TCP evidence ranking, account/contract identity, case-file digests,
and optional lease generation. It rejects candidate-order/score and file-drift
contradictions; endpoint values are omitted from its redacted summary. Root's
focused rerun passed 9 synthetic tests, Ruff, and a fresh import check that
loaded no CTP SDK modules. The TCP samples are unauthenticated transport
observations, the in-process object checks are not a security authority, and
all 33 case entrypoints remain `BLOCKED`.

A separate read-only structure audit confirmed 33/33 case directories each
contain the matching `<ID>_strategy.py`, `config.yaml`, and `run.py`; the child
configs have scenario parameters only and no account/front fields. The suite
root protected config matches the 013_3 private source at every YAML leaf
except the rebound 007 strategy identity, with all five MD/TD pairs in the
same order. Its Git-ignore rule and directory/config ACL match the private
source. The selector and invocation binder implement the same complete-pair
median-latency ranking. Root reran four focused offline entry/scope/probe test
files: 63 passed with one existing pytest-configuration warning. This audit
did not perform a new network, native, login, or trading operation.

The combined MD/settlement SDK source candidate produced two byte-identical
Windows CPython 3.11 wheels under candidate-only MSVC `/Brepro` flags (SHA-256
`5a68fd2b5968a889e64e5382b7ecd278d8a039cfe16b1cb85d21b170cd051378`).
Independent QA verified its source delta, 86 hashed wheel RECORD rows, an
isolated no-system-site install, installed RECORD/direct-url hashes, `pip
check`, pure imports, and 56 fake tests. The exact build invocation and epoch
log was not retained, and the wheel still contains write-capable CTP APIs.
The fail-closed settlement helper intentionally conflicts with ten old
readiness-promotion fake tests. There was no native client/lifecycle/provider
test, no pin/route change, and G4/G6 remain unaccepted; see
`D:/temp/ac41-g6s-independent-qa-20260928/INDEPENDENT-QA.md`.

A separately logged, one-shot rebuild reproduced all 87 wheel-member payloads,
their compressed streams, the RECORD payload, and the native extension bytes.
Its whole-wheel SHA-256 differs from the frozen two-wheel pair because every
ZIP entry timestamp is eight hours earlier. The original pair's build epoch
was not retained, so the exact frozen wheel hash was not reproduced and the
G4/G6 gates remain closed. The command, environment, toolchain, and comparison
are in `D:/temp/ac41-g6s-single-rebuild-logged-20260928/REBUILD-RESULT.md`.

An isolated Windows Job supervisor prototype also passed three inert tests,
including a child blocked in an infinite wait and a hanging child/grandchild
tree. It confirmed process termination after the local timeout, but the
supervisor's synchronous Job creation, process launch, termination, wait, and
close calls remain outside an enforceable whole-command hard deadline. Forced
termination does not prove native SDK `Release` or a clean provider session.
Thus strict G1 remains `NO_GO`, with no CLI route change; see
`D:/temp/ac41-007-job-supervisor-prototype-20260928/README.md`.

An independently checked query-only SDK proof of concept was built as a
separate Windows CPython 3.11 wheel from the clean SDK source pin. Its generated
SWIG surface includes nine TD reads and MD login/market-data callbacks, while
order/cancel, settlement-confirm **write**, transfer, and password-change
requests are absent. Wheel RECORD, isolated import, installed payloads, and
three fake callback tests passed. The bundled vendor DLLs remain full runtimes;
this is a candidate API boundary, not process confinement, 007 integration, or
native/provider acceptance. See
`D:/temp/ac41-007-query-only-sdk-poc-independent-qa-20260928/QA-REPORT.md`.

The revised isolated query-only wheel v0.0.4 was independently checked against
the clean source pin, generated Python/C++ API and callback allowlists, wheel
RECORD, isolated install/import and five synthetic callback tests. It adds MD
generic `OnRspError` handling and an unsubscribe-error test while retaining
only the nine TD read requests. The full vendor DLLs remain bundled, MD ACK
correlation is not provider-authenticated, and no native/provider session was
run. See
`D:/temp/ac41-007-query-only-sdk-poc-v004-independent-qa-20260928/QA-REPORT.md`.

The isolated clean-SDK order/trade callback archive port passed 44 fake and
focused regression tests. Its six hooks include SPI origin checks, expose
archive poison, revoke execution proof on bad capture, and keep
cancel request ACK distinct from terminal order status. Records remain volatile,
not atomically linked to the existing queue/query history and without a shared
query/order sequence or durable journal. It is not 007 or G7-S acceptance; see
`D:/temp/ac41-007-native-callback-archive-port-candidate-20260928/CALLBACK-ARCHIVE-PORT-REPORT.md`.
Independent QA reproduced a stronger blocking defect: after reconnect on the
same API/SPI, an old `OnRspOrderInsert` callback was archived with the new
session/generation while the archive remained healthy. The candidate is
`NOT_ACCEPTED` pending an issued-request ledger and cross-generation fence;
see `D:/temp/ac41-007-native-callback-archive-independent-qa-g4audit-20260928-01/QA-REPORT.md`.

The isolated order/trade callback archive v2 keeps lifetime request-ID
tombstones and poisons ambiguous reuse before native send. Independent QA
reran 88 fake/focused tests and reproduced the old unissued callback and two
old-issued-callback reconnect routes (same SPI and new SPI): all poisoned with
zero archived rows. This fixes those local regressions, but the provider does
not authenticate callback generation or quiescence in this evidence, so the
archive remains unregistered and not accepted. The candidate report's commit
SHA has a transcription error; QA verified the candidate and clean pin both
at `28157ce33009f932fbf8b3a78f7e77cb42c9cc4b`. See
`D:/temp/ac41-007-native-callback-archive-v2-independent-qa-g4audit-20260928-01/QA-REPORT.md`.

An unregistered read-only baseline/final query-round coordinator passed 44
focused fake tests and strict schema checks. It binds request IDs, closure,
ErrorID/IsLast, client/generation/session, and local arrival order, but the
frozen v1 archive exposes only row digests/counts. Raw reconciliation values
and C01 completion therefore remain false; see
`D:/temp/ac41-c01-readonly-query-rounds-20260928/CANDIDATE-REPORT.md`.

Root reran the complete main-tree `tests/unit/live_certification` after the
source-plan and invocation-binding correction: 336 passed, with one existing
pytest-configuration warning. This is offline regression evidence only; no
managed case execution, SDK session, or provider session was accepted by that
test command.

Independent audit of the unregistered invocation binder passed its nine
focused tests and five adversarial QA probes. It confirmed exact case-file,
sealed-config, and full candidate-ranking consistency, but a caller-created
active lease snapshot can be replayed and synthetic TCP successes can bind
without a socket. One internally contradictory success sample was also
accepted. This binding is non-authorizing; it needs a current lease-owner
verifier and source-backed probe receipt before a future runner can use those
claims. See
`D:/temp/ac41-007-managed-case-invocation-independent-qa-20260928/QA-REPORT.md`.

The independently reviewed minimum correction was integrated into the main
tree. It rejects all caller-supplied active lease snapshots until a trusted
current owner verifier exists, and rejects contradictory connected/failure
and latency-component TCP samples. Coherent synthetic probe samples remain
unauthenticated. The focused main test passed 16 cases, Ruff passed, and the
complete live-certification suite passed 336 cases with one existing pytest
configuration warning. The review record is
`D:/temp/ac41-007-managed-case-invocation-review-20260928/independent-review.md`.

An isolated query-only callback client prototype passed 13 fake tests, but
independent QA found that a late MD subscription ACK for an expired token could
complete a new same-instrument token because the native ACK has no caller
token. A separate v2 prototype fences that instrument for the rest of the
local generation (15 fake tests passed). A local generation change cannot
prove native session replacement or callback quiescence, so neither prototype
is registered or accepted; see
`D:/temp/ac41-007-query-only-client-port-qa-20260928/QA-REPORT.md` and
`D:/temp/ac41-007-query-only-client-port-v2-20260928/README.md`.
Independent v2 QA then modeled same-API reuse with a newly registered SPI:
old in-flight TD and MD callbacks delivered through that SPI were accepted
under the new local generation. The synthetic model is conditional on API
reuse; the candidate cannot exclude it without native replacement and
quiescence evidence. See
`D:/temp/ac41-007-query-only-client-port-v2-qa-20260928/QA-REPORT.md`.

Independent QA of the SDK query archive v2 reproduced a mapped generic
`OnRspError(ErrorID=0, IsLast=True)` incorrectly satisfying local round
completion and found that the protected row fact can be serialized with
`pickle`/`dataclasses.asdict` despite a "no serialization" claim. It passed
13 existing fake tests but is held for correction; its in-process row values
are not a secrecy boundary. See
`D:/temp/ac41-g6-query-callback-archive-v2-independent-qa-20260928/QA-REPORT.md`.

The corrected isolated query callback archive v3 passed 15 candidate fake
tests and four supplemental current/stale SPI probes under independent QA.
Mapped generic `OnRspError`, including `ErrorID=0`, remains a blocker rather
than closing a query round; `pickle` is rejected for protected row facts.
In-process introspection can still see typed values, and one candidate wiring
test uses a `native_api=None` shortcut, so this is no native/provider or C01
acceptance. See
`D:/temp/ac41-g6-query-callback-archive-v3-independent-qa-20260928/QA-REPORT.md`.

A proposed 16-file C01 native/local source-schema patch is also held after
independent QA. A duplicate native RequestID across auth/login with distinct
caller-supplied local generations reached `REVIEW_REQUIRED`; no outbound
issued-request ledger verifies the echo. M02/M03 still attached later-login
session/day identity to payload-less `OnFrontConnected`, and callback-time,
sequence, and lower-level tracker checks were inconsistent. No part of that
patch was integrated. See
`D:/temp/iteration41-c01-source-schema-qa-20260928.md`.

The isolated C01 v2 patch corrected the duplicate native RequestID and
payload-less front callback cases in 105 focused tests, but independent QA
kept it on hold. A caller-injected verifier whose `verify()` always returned
true promoted the public strategy-level result to `REVIEW_REQUIRED`; the
default path and separate completion tracker remained incomplete. Two new
Ruff findings (`B023`, `SIM114`) were also confirmed in patch contents. No
part of v2 was integrated; see
`D:/temp/c01-v2-independent-qa-20260928/QA-REPORT.md`.

Independent 33-case logic review found two additional review-state gaps:
EM01 did not require its submitted request and permission-denied rejection to
occur strictly between the external disable and restore events; O02 did not
require a close offset, opposite position side, or bounded closeable quantity.
These could admit internally consistent but wrong-scenario facts to
`REVIEW_REQUIRED`; neither can generate certification `PASS`. Isolated
fail-closed corrections are in progress, and no real source has been admitted.
The first integration patch is held after independent QA reproduced five
remaining false `REVIEW_REQUIRED` paths: a pre-disable EM01 scenario submit
event paired with an in-window receipt, a permission-control `ErrorID`
mismatch, an O02 trade with a different close offset, two dispatched O02
submits plus one blocked retry, and an O02 request tagged to a prior provider
session. Scalar net position and per-instrument closeable quantity also lack
CTP side/today-yesterday bucket proof. See
`D:/temp/case33-em01-o02-independent-qa-20260928/QA-REPORT.md`. No part of
that patch was integrated.

The later EM01/O02 v3 correction was independently reviewed and integrated.
It requires EM01 submit/rejection timing and account/error scope to match the
permission-control window. O02 now requires one dispatched and one blocked
repeat close, matching account/session/trading day and native order/trade
facts, plus typed long/short and today/yesterday closeable buckets; generic
`close` remains incomplete. The focused main test passed 53, Ruff passed, and
the complete live-certification suite passed **351** with one existing pytest
configuration warning. Typed account labels remain unauthenticated source
claims, and all certification/dispatch/authenticity flags remain false. See
`D:/temp/em01-o02-v3-independent-qa-20260928/QA-REPORT.md` and
`D:/temp/case33_em01_o02_v3_independent_qa_20260928/QA-REPORT.md`.

The private CTP preparation CLI now supports the exact registered 007 runtime
ID while retaining 013_3 as its default. Public path and arbitrary strategy
overrides are closed, and existing private files are never overwritten. The
target-focused main test passed 58 with three platform skips, Ruff passed,
and the complete runtime suite passed **2,131** with 30 skips, two expected
failures, and one existing pytest configuration warning. No protected source,
provider SDK, network, or write route was used by these tests.

The unregistered local TCP front-selection receipt was independently reviewed
and integrated after a frozen patch hash and apply check. It binds the exact
issued 007 case scope and freshly resealed suite configuration to a selected
configured pair index, ordered pair-set digest, and bounded TCP checker
counts; a caller-built clone and config or pair-order drift reject. It
contains no endpoint or secret values and grants no provider or write
authority. The 22-test main focus, project Ruff gate, and full
`tests/unit/live_certification` suite passed; the latter now has **357**
offline tests with one existing pytest configuration warning. The independent
report is at
`D:/temp/ac41-007-front-selection-receipt-v4-independent-qa-20260928-01/REPORT.md`.

A separate source review mapped the future `PASS` boundary: a supervised
collector must retain raw native callback and query artifacts, an external
verifier must attest their hashes and source domains, the account owner must
attest the exact account/run scope, and a separate adjudicator must review the
verified projection and sign the outcome. The current strategy, case, and
completion checkers remain review-only and cannot self-attest source or
account ownership. This is an implementation plan, not an accepted route;
see `D:/temp/ac41-007-source-authenticity-adjudication-plan-20260928.md`.

A further static review compared every new case strategy with its historical
flat script. It records all 33 legacy action/`PASS` gaps, the native and
account evidence each case needs, and external conditions that automation
cannot synthesize. The report is
`iteration41-007-simnow-33-case-legacy-vs-current-review-2026-09-28.md`
(SHA-256 `C958FC7015A9E10F45EE7234C4EDDC49BDAEE0A7401A29E36A668BF8BF27ADE2`).
The latest individual-process rerun again produced 33 `BLOCKED`/exit 2
results with zero recorded network requests and trading writes.

An isolated prestarted Windows guardian prototype passed three inert tests
and showed that a guardian-owned Job can outlive its caller and contain an
inert blocked worker. It did not hard-bound synchronous command, IPC, Job,
or disk operations and did not test a CTP native client. Forced termination
would skip native Release. Its verdict remains `G1 NO_GO`; no default route
or private preflight was changed. The frozen report and evidence are at
`D:/temp/ac41-007-guardian-service-boundary-prototype-20260928/README.md`.

The managed-write parent SDK pin is also still `HOLD_PROVENANCE`. Its clean
parent commit points at a gateway Gitlink whose tree contains only README;
the old available gateway wheel lacks the parent-required constructor API
and failed four fake dispatch tests. A temporary gateway source snapshot and
temporary updated parent Gitlink produced reproducible wheels and a four-pass
isolated fake consumer with matching installed RECORD/PEP 610 hashes. The
gateway snapshot is not an upstream-retrievable reviewed source pin, so this
does not accept a managed SDK bundle or any CTP write. Independent QA verified
the final/old artifact separation at
`D:/temp/ac41-parent-sdk-pin-independent-qa-20260928-02/QA-INDEPENDENT.md`.

## Source references

- `examples/007_ctp/live_certification/simnow_penetration/README.md` — staging
  boundary, private suite configuration description, route separation, and
  historical-case status.
- `examples/007_ctp/live_certification/simnow_penetration/managed_case_entry.py`
  — code-owned 33-scenario registry, config/path checks, unconditional redacted
  `BLOCKED` result, and zero external request counters.
- `examples/007_ctp/live_certification/simnow_penetration/cases/<ID>/` — each
  staged case plan and entry wrapper.
- `examples/013_3_sa_midfreq_simnow/README.md` — private read-only TCP front
  reachability boundary; TCP is not login or settlement evidence.
- `../ctp-current-acceptance-matrix.md` — current gate definitions and status.
- `iteration41-g1-whole-command-supervisor-no-go-2026-09-27/README.md`,
  `iteration41-g1-current-boundary-decision-2026-09-28.md`,
  `iteration41-g4-triplewheel-candidate-2026-09-28.md`,
  `iteration41-g4-clean-parent-triplewheel-candidate-2026-09-28.md`,
  `g4-msvc-pe-timestamp-author-review-2026-09-27/README.md`,
  `iteration41-g5-v21-current-contract-independent-qa-2026-09-27/QA-INDEX.md`,
  and `g6p-account-actor-resource-discovery-2026-09-27/README.md` — gate-specific
  evidence records.

## 2026-09-28 C01 r3、G1 与 G4 来源状态增补

### C01 r3 主树集成与 source-only QA

C01 r3 的 17 个目标已主树集成。冻结候选完整套件为 **482 passed**；主树 `tests/unit/live_certification` 集成后实测 **488 passed、1 个既有 warning**。17 个目标 Ruff 通过，应用后内容与冻结候选在 CRLF 归一化后逐字一致，`git diff --check` clean。

独立 r3 source/schema QA 对精确 patch 给出 **`GO for source-only integration`**（报告 SHA-256 `5B2BB518996622ADA2539F53DAF593FB0DB38706A8875D6355A87C432C5ACF30`）：隔离副本八模块焦点 **319 passed**，选定 C01/alias/EM01/O02 回归 **83 passed**。r3 alias/session 独立增量审查为 **197 passed**（报告 SHA-256 `CD5500243A16633AEF218418EE0BD4A57E08C34BCE89ED88B397C222560E8933`）。r3 patch SHA-256 为 `A89BAB7A8D8A80D54DD93299DA386DDB1E4BF4C0B31C384940FF9A77525BBA83`。这些结论只接受精确源码/测试补丁的离线集成，不表示 provider、callback 来源或案例认证通过。

C01 仍为 **`INCOMPLETE`**：可信 SDK issuer 私有 RequestID ledger verifier 与 baseline/final query receipt path 未接通，也缺 native callback 来源认证、受信账号 owner 和 provider 回执。逐目录重跑的 33 个 `run.py` 均为 `BLOCKED` / exit 2，原因 `managed_ctp_certification_not_registered`；network/order_write 为 0，真实 `PASS` 为 0。

### Issuer RequestID ledger 原型（fake-only）

独立 issuer-side 原型按完整 C01 序列需要八个不同 RequestID 建模：auth、login，以及 baseline/final 各自的 orders、positions、funds 查询。16 项 fake-only 测试通过，验证本地分配/调用/回调关联、重连和终态约束（原型研究报告 SHA-256 `741ED98137A5963AC32A3DA870017EA8A712F94F6145A932A476A57CE8EF5328`）。它不调用真实 native API；fake 可直接调用 Python SPI，故不证明 callback 的 native/provider 来源，也未接入受信 SDK verifier。该结果与 C01 `INCOMPLETE` 一致。

### G1 strict whole-command deadline 的六项故障注入

2026-09-28 的只读审查对现有 outer watchdog 和 receipt writer 做六个 fake 同步延迟注入：backend creation、launcher resume、Job termination、handle release、control escrow、receipt `fsync`。本地测试 **6 passed**；注入调用均先超过配置 deadline 才返回。独立审计报告 SHA-256 `B8F08446FCE669DE907BB8F0F16B267C4553EC287BCA2C6F17DFA847F5EAB8B9`。结论为 **`G1_STRICT_WHOLE_COMMAND = NO_GO`**。测试没有调用真实 Win32 API 或 CTP，也没有制造真实磁盘/内核故障；普通 preflight 仍 fail-closed，未开放任何写或 provider 路由。

### G4 parent/gateway source provenance 与独立 QA

G4 来源审计与独立复核均标记 **`HOLD_PROVENANCE`**。兼容 parent API 所需的 gateway 实现来自本地未跟踪源码快照；记录的 upstream gitlink 树只有 README。来源审计报告 SHA-256 `A5509C8A0434DD694B2C31D930CF342EEA69BE299218E1CF813F79F61907931A`；独立 QA 报告 SHA-256 `E6730BDD15FA066F8CDEE3142D6E20ECC39E40FD02583CA9DDA9F10542338159`。本轮来源独立 QA 核对候选提交、源码清单、Git archive、两次 wheel 构建以及 69 项 gateway fake 和 4 项 parent binding fake 测试记录；此前的制品独立 QA 核对了 installed RECORD 与 PEP 610 来源；这些本地检查彼此一致，但不能认证 upstream 源代码或发布者。它不构成 CTP native、provider、G4 生命周期或写入验收。

`NO_WRITE / LIVE_NO_GO` 保持有效。

## 2026-09-28 further isolated, non-authorizing slices

The C01 issuer-ledger/schema projection research candidate is held outside
the repository at D:/temp/c01-r3-issued-ledger-candidate-20260928/REPORT.md
(SHA-256 EDE03BE15947BB1284F11CC15FE6840E36CB91B946C8EEEDD0C8816FB734C2B1).
Its 26 fake-only tests exercise eight native RequestID values and partial
query rows. A fake client can still invoke the Python callback directly; the
C01 tracker and completion report remain INCOMPLETE, with certification PASS,
dispatch, and source authenticity all false. Disposition: HOLD_LOCAL_RESEARCH.

The MD subscription local-epoch candidate is also outside the repository at
D:/temp/iteration41-ctp-md-subscription-ack-local-correlation-candidate-20260928/REPORT.md
(corrected report SHA-256 D8D39312182C78D06ADE5CE10CB3BEDFC8DA3A7BAB2490BAB7016D6145B90814;
the earlier EA34EFB5... report is superseded). Twelve fake-only tests and
SDK-configured Ruff passed. Native SubscribeMarketData has no caller token,
and ACK/tick callbacks have no callback-bound connection generation. The
single-API local epoch cannot become a native/provider subscription proof.
Disposition: PASS_LOCAL_BEHAVIOR / HOLD_NATIVE_CORRELATION; G6-S remains closed.

The 33-case certification-profile dependency audit is at
D:/temp/ac41-007-certification-profile-gap-20260928/REPORT.md
(SHA-256 B496113399DB9A0084A8118F2A42E0937A62668E10E555C1E8A4FFC8E7A3FE27).
It groups session-only, single-action, repeated/threshold, remote-error/
permission, and batch cases. Existing TestExecutionProfile observations hard
code zero execution/provider/write authority; the one-lot operational window
cannot cover B01/B02. Batch figures in the audit are design examples, not
approved risk limits. Trusted account ownership/fencing, atomic account-wide
budget, one-use action approval, supervised TTL, cleanup and reconciliation
remain required before a 33-case runner can be registered.

These held candidates did not change the main runtime, default registration,
protected config, native SDK, provider state, or write permissions. The latest
individual 33-entry check is still 33 BLOCKED / zero real PASS.

G1 的预启动服务请求合约设计审查保存在
`D:/temp/ac41-g1-prestarted-service-contract-review-20260928/DESIGN.md`
（SHA-256 `51A4CBDBA3691E8CA1C7FAF537F5D4BD5CD84E4C2D9461F38F8B4CF706491961`）。
设计将服务端单调 `T0/D`、票据消费和 `ACCEPTED` 原子持久化置于 worker Resume 前，
并明确晚到或不明的同步调用只能得到 `UNKNOWN`。它只提出与原整条 CLI 命令截止
不同的服务请求级验收目标，未运行新测试、未打开普通 preflight，原 G1 仍为
`NO_GO`。是否采用新目标待用户决定。

同日 G4 只读远端来源复查见
`D:/temp/ac41-g4-parent-source-provenance-audit-20260928/REPORT.md`
（SHA-256 `D5AB993346BC71254EE8AA17EAD6D03987AEEC43C8CAB458B2B38D6BA6CCF5D5`）。
公开 gateway `dev/master` 指向仅含 README 的 `44fd2fe…`；本地所需实现
`7f54c21…` 并非公开发布。父包 `76d5e0e…` 仅在本地分支，当前公开父包 refs
也没有与其完整候选源对应的 release。故 `HOLD_PROVENANCE` 仍不解除：需要
上游发布包含 gateway 实现的可重取提交，以及精确绑定该 gitlink 和完整 API
源的父包提交，之后从 clean clone 重建并独立审查三包 pin。

SDK 私有 issued-request ledger r2 仍在隔离目录：补丁 SHA-256
`03B233DDBF2B5CACCB6A26AB5F08003063840FF13B31E1A4850DFEF3D66F727A`，
独立 QA 报告
`D:/temp/c01-sdk-issued-ledger-r2-independent-qa-20260928/review.md`
的 SHA-256 为 `6135E02578E5CD0DCB78B4803C291427C8B5B9AF0982A0307366BD958F06CAF1`。
22 项 fake/旧回调焦点通过，Ruff 与 Python 3.9 grammar 通过。独立 fake 可确定性复现
账本登记后、native 调用前替换 API 时，旧 API 仍收到 Authenticate、Login 或只读查询；
最终 query/ledger 保守判为不完整，没有测试出假终态，但无法撤销已发出的旧 API 调用。
单独再检查一次绑定不能原子封闭该窗口。结论 `HOLD / NO_MERGE / NO_AUTHORITY`；
C01 仍 `INCOMPLETE`，默认 SDK 与主树路由未采用该候选。

r3 未产生 production patch。隔离设计报告
`D:/temp/c01-sdk-issued-ledger-r3-hold-design-20260928/REPORT-r3-HOLD_DESIGN.md`
（SHA-256 `5C382D2D795DCE171B8D1BD9A0B60BB0D641AF23011C4F835B996140CC060732`）
用四项 fake probe 进一步复现 API 替换与 reconnect 的 issue-to-call 窗口。
跨 native `Req*` 持锁或等待 active-dispatch lease 均需证明不会与 inline/异线程
callback、reconnect、stop/Release 自等待；缺少精确 pinned native 阻塞语义时
结论为 `HOLD_DESIGN / NO_PATCH / NO_MERGE`。真实会话和 33 案例状态不变。

## Additional credential-free TCP snapshot (2026-09-28 12:05 UTC)

From the local D: working tree, root ran `python -m backtrader_runtime.cli
check-ctp-fronts --strategy-dir` once for each protected 013_3 and 007
runtime. Both commands exited 0. For both configs, candidate indexes 0–3 each
returned MD 3/3 and TD 3/3 TCP connections; index 4 returned MD 0/3 and TD
0/3. The 013_3 command selected index 0 and the 007 command selected index 2.
The selector uses the lower configured-pair latency score among eligible pairs
(with config index as a tie breaker), so the selected index is an observation,
not a permanent preferred front. Both receipts reported
`tcp_probe_only=true`, `authentication_attempted=false`,
`credential_resolver_invoked=false`, `sdk_imported=false`,
`provider_login_started=false`, and zero settlement/trading writes. The
private addresses and credentials are omitted. This later transport snapshot
does not supersede the zero real-PASS case result or certify MD/TD login,
subscription, orders, or cancels.
