# R10-r1 inert Windows deadline and shutdown prototype

**Disposition: author prototype only; G1 remains CLOSED.** This isolated copy
addresses two R10 prototype gaps. It does not establish a whole-command hard
deadline, P14 containment, a service topology, or G1 acceptance.

## Frozen inputs and run

The frozen R10 input source is preserved byte-for-byte under `R10_BASELINE/`
(source SHA-256 `4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3`;
trials SHA-256 `ba4ab18e585ff66a3af956b17fc84426ec055d4f5f6ae4916ed40fe2651894d5`).
R10's independent static review identified an unconditional
`WaitForSingleObject(writer, INFINITE)` after cancellation; a stuck writer could
hold broker shutdown. The R10-r1 source is a separate copy and does not modify
that frozen input or production/default-route code; its final evidence is
archived separately under the Iteration 41 evidence tree.

Run command: `python run_r10_r1_trials.py` on Windows, using MSVC 2022 via
`vcvars64.bat`. The final harness trial record is `r10_r1_trials.json` and the
earlier, unrepeated interim run is preserved as `r10_r1_trials_initial.json`.
The final run recorded **15 checks, 0 failed**. It includes the exact QPC
timestamps, all scenario JSON, cleanup observations, platform details, and the
final build result.

## Local changes and test evidence

Admission now samples QueryPerformanceCounter against the same absolute QPC D
before the slot CAS and after each claim/publication phase. At D or later before
the CAS, it returns `SUBMIT_EXPIRED` without touching the slot. If the claim or
publication crosses D, it rejects, poisons the slot, and makes any published
ticket irreversibly `UNKNOWN`. The broker applies the same QPC D before its
ticket transition and before starting the worker.

The deterministic boundary probe used D=100 QPC ticks: D−1 accepted; D and
D+1 rejected before slot mutation. Injected claim-to-D and publish-to-D races
were rejected and poisoned; publication-at/after D ended in UNKNOWN. An actual
eight-thread mailbox race produced one accepted ticket and seven BUSY results.
The repeated live late-admission runs sampled submit start at D+3 and D+3 QPC
ticks (0.3µs at 10MHz), and returned at D+8 and D+10 ticks. Both
returned EXPIRED with no ticket or worker write, followed by exact broker exit
and Job-empty.

An earlier full run is preserved as
`r10_r1_trials_failure-late-admission-tick-mismatch.json`. Its first late probe
waited on a separate millisecond clock and invoked SubmitTicket at D−4,674 QPC
ticks, so it was correctly accepted before D; the repeated sample was late and
rejected. The harness was corrected to inject lateness using the same QPC D and
the final repeated trials above are clean. This was a test-clock mismatch, not
evidence of post-D acceptance.

The ordinary P05 run accepted before D: QPC frequency was 10,000,000 ticks/s;
submit began at D−11,999,956 ticks and returned at D−11,999,953 ticks. The
broker transitioned the ticket to UNKNOWN at D+1,175.1µs; the caller observed
that state at D+1,179.9µs. The normal caller-death case killed the caller
while the local 2 MiB overlapped pipe write was pending; the broker remained
its I/O owner, consumed cancellation completion, exited, and reached Job-empty.

Two shutdown negatives exercise retained ownership:

| Trial | Injected condition | Caller observation | Broker / controls at report |
| --- | --- | --- | --- |
| `cancel-stall` | Inert code deliberately skipped `CancelIoEx`; pending overlapped write never completed during the observation | Broker marked UNKNOWN at D+209.5µs; caller observed it at D+15,456.5µs and exited 0 | Writer remained pending and live; broker Job had 1 process; supervisor retained its controls; outer test Job later terminated 3 processes and reached 0 |
| `cancel-stall-caller-death` | Same pending I/O plus caller killed while write was pending | Broker observed caller death and marked UNKNOWN at D+3,789.2µs; there is no caller poll after death | Writer remained pending and live; broker Job had 1 process; supervisor retained controls; outer test Job later terminated 3 processes and reached 0 |
| `join-stall` | Writer reported completion, then an inert user-mode loop prevented thread exit | Broker marked UNKNOWN at D+12,346.2µs; caller observed it at D+27,012.4µs and exited 0 | Broker's 100ms join wait timed out; broker Job had 1 process; supervisor retained controls; outer test Job later terminated 3 processes and reached 0 |

The test harness's outer-Job termination is post-decision fixture teardown; it
is not evidence of normal cancellation, release, exact worker exit, or successful
Job-empty for the retained cases. The injected cancellation case skips the API
call; it is **not** a real Win32 `CancelIoEx` failure or delayed-kernel-completion
test.

## Limits

Caller-terminal UNKNOWN was observed after D in every caller-survives case.
Even when the broker transitioned UNKNOWN shortly after D, the caller observed
it later (for example `cancel-stall` at D+15.4565ms and `join-stall` at
D+27.0124ms). The results therefore do not prove
that an UNKNOWN decision reaches the caller by D. QPC checks also do not make
the call stack immune to OS preemption or a nonreturning system call.

The measured D begins at the test's GO barrier. Process launch, Job/pipe setup,
and synchronous prewarm remain outside it. P02/P03 true `CreateProcessW` kernel
hangs, P14 `TerminateJobObject`/query/close failures, failure of a higher
custodian, SCM/service behavior, and a whole-command deadline were not tested.
The ordinary CTP preflight and default route were not changed. No CTP/native
provider, SDK, credentials, private config, account, or network was used.

**Conclusion:** R10-r1 demonstrates local admission-at-D checks and fail-closed
retention for selected inert shutdown stalls. It does not meet the existing
whole-command G1 hard-D contract. G1 and ordinary preflight remain closed.
