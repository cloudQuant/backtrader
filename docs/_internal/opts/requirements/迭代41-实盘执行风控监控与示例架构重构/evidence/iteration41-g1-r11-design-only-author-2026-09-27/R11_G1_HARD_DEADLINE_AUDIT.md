# R11 G1 request-boundary and custodian audit

**Status: read-only design audit + lazy inert test plan. R11 is not implemented or accepted. G1 and ordinary CTP preflight remain closed.** No acceptance matrix or production/default route change is made.

## Frozen basis

- Main matrix: `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\ctp-current-acceptance-matrix.md` (SHA in `r11_design_manifest.json`); it retains G1/preflight closed and R9 as design-only.
- R8 negative list: `...\evidence\ctp-g1-r8-independent-reaper-review-checklist-2026-09-27.md` (SHA in manifest), including P02/P03, P06-P10, P14, P17-P21 and the required Job-empty predicate.
- R9 design-only input SHA-256: `77500a63eabd0df5673b923458893fbd44c0d3ca1ec22c403dff95b98d869bd0`.
- R10 author page SHA-256 `e421fa38eda80585d9a8d890f51ebcdcc897ed1b608a9c2bd462c14dc26f1344`; manifest `da1252e1e25c20530a9cce358c35a1a90f0729dc7f60da85fe2600dd8790f6c3`; receipt `deb34cbe0584710fa41f6623f0febcec0a2a2a71c5ff15e0c54f2fbf39c877c7`; final trials `ba4ab18e585ff66a3af956b17fc84426ec055d4f5f6ae4916ed40fe2651894d5`; first trials `32bca66edba15ae73a7cf8777ecafcaabcd346df4326e69c39c49a44ae781040`.

`audit_frozen_r10.py` is read-only: it verifies R10 hashes and payloads, reports timing/gaps, starts no processes, and accesses no provider/API. Output: `r10_readonly_audit.json`.

## Strict whole-command deadline definition

For a whole-command claim, set one trusted monotonic start `T0` **before the externally visible command launch** and one immutable `D = T0 + budget`. Carry the same QPC clock domain/frequency, `T0`, `D`, request ID and generation across processes. Do not restart the clock at Python entry, service readiness, ticket acceptance, worker start, or native API start. A newly created CLI cannot timestamp before its own CreateProcessW; including that launch requires an already-running external caller/launcher to stamp T0 and retain the deadline owner.

The interval includes outer process launch/Python bootstrap; source, dependency, identity and protected-config checks; service/broker connection/readiness; admission; pipe/token/handle/Job setup; CreateProcess/ResumeThread; worker/native body; response framing and receipt creation/write/flush/readback/delivery; cancellation; exact process-handle signal/exit code; every request Job independently queried `ActiveProcesses == 0` after assignment closes; final completion consumption for every pending I/O at its issuing endpoint; and required control release. For full completion, valid receipt delivery, worker and receipt-writer Job-empty, no pending I/O, and required controls released must all be evidenced at or before that same D. If any evidence is missing at D, outcome is irrevocably UNKNOWN. Late cleanup/receipt is audit-only and cannot upgrade it. `TerminateJobObject(TRUE)` is a request, not exit or Job-empty evidence.

Acceptance is the first public admission action, not the later server ACK. A pre-READY rejection must itself return within D under the whole-command promise; an ACK cannot reset D.

A persistent service can be a precondition for a **separately scoped request** only if it is already READY before that request. Its startup/prewarm needs a separate lifecycle/readiness contract. If the command launches or warms that service, this time is inside whole-command D. A request-only READY boundary is narrower than the existing whole-command G1 requirement and cannot be described as satisfying it.

## R10 adjudication

Final P05 uses a 1200 ms request budget: D tick `225406450`; ticket UNKNOWN tick `225406453` (observed D+3 ms). The `0.1 µs` number measures only atomic mailbox submit, which returns a ticket before final classification. It is neither end-to-end command latency nor caller receipt by D. The final UNKNOWN was observed after D; it is not “UNKNOWN by D,” and another scheduler delay can make it later. R10 READY and setup occurred before the budget, so its request clock excludes outer launch and prewarm. Final 9/9 assertions are only inert state-machine assertions, not a hard deadline proof.

## Boundary review

| Item | R10 evidence and consequence |
|---|---|
| P02 CreateProcess before creation | Popen wrapper-only stall. No true CreateProcessW hang. No request-time CreateProcess is preferred; outer launcher creation remains in whole-command D. |
| P03 child exists before call returns | Wrapper creates inert child then blocks; Job count/termination observed. This is not a native syscall hang. Require Job membership from first instruction/no breakaway; absent exact exit facts, never success. |
| P14 terminate/query/close | Not tested. Hang/false terminate, query failure/nonzero, cancellation failure, or ambiguous close means UNKNOWN, retained controls and poisoned slot. A timer on the same blocked reaper does not run. |
| Unique reaper wedged/dead | Client broker can preserve its side/ticket but cannot prove server Job empty. G0 with duplicate controls can supervise G1, but if G0's own call wedges, a finite user-mode chain has no remaining observer. SCM restart/KILL_ON_JOB_CLOSE is cleanup, not Job-empty proof. |
| Caller death with pending I/O | R10 partial positive: broker survived, saw caller death, then consumed cancellation completion error 995 and observed its own Job empty. Each endpoint must retain its own handle/OVERLAPPED/event/buffer to final completion. |
| P07 | R10 delayed user-mode consumption 100 ms after event. It does not inject delayed kernel completion. Pending resources cannot be released/reused until that exact completion is consumed. |
| Receipt/setup | Prewarm is outside D; no SCM. Receipt writer/flush/readback may itself block after worker cleanup; it remains inside whole-command D. |

R10's monotone UNKNOWN CAS is useful state logic but does not make a state transition happen while its owner is descheduled. D+3 ms already misses the literal deadline in the observed run.

## Minimal R11 topology (design only)

```text
Windows/SCM trust root (declared assumptions; not a hard-deadline proof)
  persistent client I/O broker: owns connected client pipe + client OVERLAPPED contexts
  already-running caller: fixed atomic mailbox publish/read only
  persistent guardian G0, outside request Jobs: owns G1 process/Job + duplicate request-Job controls
    persistent request reaper G1: owns server I/O contexts + exact worker/Job controls
      one-shot prewarmed worker/output slot(s), Job-assigned and READY before admission
```

Use a single-use prewarmed slot: before READY, create/assign the worker and output writer, connect both IPC endpoints, allocate all OVERLAPPED/event/buffer contexts, and validate identity. During a request, no caller-stack CreateProcess/Popen, pipe open/connect, synchronous WriteFile, blocking queue/lock, or handle release. Caller only publishes a fixed-size ticket and reads it; it does not get an on-time command result just because ticket submit was fast. G1 retains server-side exact controls; client broker owns client-side I/O; G0 has independently duplicated controls and is outside G1's Job. After UNKNOWN, keep slot/handles poisoned until all pending completions and exact Job-empty facts resolve; otherwise refuse reuse.

G0 adds a testable process layer for G1 death/hang, not a proof against a hung G0 syscall or OS starvation. A killed service or kill-on-close behavior cannot prove empty unless a live process still owns and successfully queries that exact Job handle.

## Minimum negative-test plan

Full declarative cases are in `r11_negative_test_plan.json`; it is not executed. All future runs must be inert and isolated, with no CTP/native/provider, credentials, private config, network, SCM installation, or ordinary preflight.

1. Stamp one T0 in a pre-existing outer test driver before process launch; log every phase to receipt/Job-empty and inject cumulative delays. No reset at READY/ACK. Late stage or output is a whole-command fail even if cleanup later succeeds.
2. Block launcher, Python startup, prewarm, pipe connect and readiness. Prove not-ready is rejected, never accepted/observed. If service startup is excluded under a different contract, test/document it as a separate lifecycle contract, not G1 whole command.
3. P02/P03/P04 barriers before/after create/resume: label wrapper probes versus true native/API fault injection. Prove zero request-time process-create/resume calls after READY. Do not infer true syscall-hang coverage from wrapper stalls.
4. Saturate synchronous admission; verify no accepted-stack sync pipe/queue calls. Record submit separate from terminal result.
5. P06-P10 pending I/O/cancel success, ERROR_NOT_FOUND, other failure, delayed event consume, caller/broker death. Record issuing PID, pipe/context identities, cancel code and exact completion/release. Distinguish post-event user-mode hold from actual kernel completion delay.
6. Descendant, grandchild, breakaway, stale/nonzero/failing Job query. Require exact retained Job handle, assignment closed, process signaled/exit code and ActiveProcesses zero by D; ignore worker self-report.
7. P14 terminate before/after side effect, FALSE, query block/failure/nonzero, cancel failure/no completion, close before/after side effect. G0 keeps duplicate handles, caller is UNKNOWN, slot poisoned; no success/reuse on late cleanup. Label wrapper gate separately from native result.
8. Kill/wedge G1 at every setup/terminate/query/close edge; verify G0 acts from preheld controls. Then kill/wedge G0 and record the exact point with no surviving user-mode proof owner; status stays UNKNOWN/G1 closed.
9. Block receipt/frame/flush/readback/output path; all receipt and all request Job-empty facts must precede the same D.
10. P17/P18/P20/P21: one declining D, caller disconnect/death, busy/poisoned slot, stale completion, normal on-time positive, and D+epsilon late positive. Late evidence cannot upgrade UNKNOWN.

For every case log T0/D/frequency, accepted/decision/response timestamps, PID+creation identities, exact Job handle owner/rights, ActiveProcesses samples, process exit code, pending I/O ownership/completion, and slot/control state. Post-test teardown is separate from request-deadline facts.

## Hard-deadline limit and required decision

Windows user mode cannot prove a thread will be scheduled by a specific wall-clock instant. A synchronous Win32 call can fail to return to the deadline-checking thread; an independent user-mode watchdog also needs scheduling and its own terminate/query/close calls to return. Adding another process moves the top boundary, not removes it. A finite chain has a highest custodian; arbitrary scheduler starvation or a nonreturning kernel/driver call leaves no user-mode observer that can prove caller return or Job-empty by D. No such platform guarantee is in the reviewed evidence. Therefore keep G1 closed under the current hard whole-command wording.

If the owner wants a narrower operational contract, acceptance text must be deliberately amended before implementation to state: scope starts at ticket publication to an already-READY broker/service (not CLI/SCM/launcher startup); UNKNOWN is committed when its independently scheduled owner next runs at/after D and caller observation may be later; native API nonreturn and OS non-scheduling are outside the promise; unresolved jobs/handles stay quarantined; the property is application-level deadline classification, **not** hard whole-command caller return. That would be a requirement change, not a G1 pass. To keep the present hard wording, a platform/external mechanism with specified and independently evidenced scheduling plus bounded-call guarantees is required; a Python/C++ process tree alone is insufficient.

No acceptance wording was changed in this audit.



---

# R10 independent static-review addendum (post-freeze)

This is a post-freeze source review supplement to the R11 design audit. The original R11 design source remains byte-for-byte preserved at `frozen_source/R11_G1_HARD_DEADLINE_AUDIT.md`; the original R10 source remains unchanged in the frozen R10 author archive.

The independent R10 replay/static reviewer identified an unbounded broker shutdown path in the frozen `r10_custodian.cpp` (SHA-256 `4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3`):

- `WriterThread` calls `CancelIoEx` at line 200 and then unconditionally calls `WaitForSingleObject(c->ovEvent, INFINITE)` at line 205 when the cancel event wins. If cancellation fails or the final I/O completion/event never arrives, the writer thread can remain blocked and never set `writerDone` at line 216.
- `BrokerMain` sees shutdown at lines 333–337, signals `cancel` when `writerDone` is false, and does not break its loop until `writerDone` becomes true. It can therefore remain in its `Sleep(1)` loop if the writer is stuck. After the loop, line 340 also performs `WaitForSingleObject(writer, INFINITE)` before closing broker resources.
- This means caller-side UNKNOWN/ticket CAS does not bound broker shutdown, cancellation drain, or control release. Without an already-live higher custodian holding independent process/Job controls, R10 cannot claim the reaper remains available to prove eventual Job-empty. A higher custodian that itself blocks still has the same top-level user-mode limitation documented in R11.

**Evidence class: static source-path review only.** R10’s successful trials did not dynamically trigger a stuck writer, failed `CancelIoEx`, missing kernel completion, P14, or higher-custodian failure. This supplements the R11 risk analysis; it does not change the frozen R10 source/trials or claim a reproduced Windows hang. G1 remains closed.
