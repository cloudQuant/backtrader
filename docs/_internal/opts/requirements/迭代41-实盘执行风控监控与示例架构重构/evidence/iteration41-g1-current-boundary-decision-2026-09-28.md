# G1 Current Boundary Decision

Date: 2026-09-28. Status: **NO_GO**. This note records a design decision for review; it does not change the acceptance matrix, register a route, or authorize preflight, provider access, or writes.

## Current strict wording

The current G1 gate requires one absolute total budget to cover the complete one-shot command, including parent probing, setup, child work, close, and Job cleanup. The budget starts at the outer command boundary, so process startup and the final containment evidence cannot be excluded. See the [current G1 matrix row](../ctp-current-acceptance-matrix.md) and the [latest G1 verdict](../验收文档.md).

## Why the current user-mode candidate cannot prove it

`_supervise_fixed_command()` calls `run_outer_watchdog()` in its own process. The watchdog calls the Windows backend synchronously. The backend calls `CreateProcessW` or `CreateProcessAsUserW`; its source explicitly notes that `CreateProcessW` itself cannot be interrupted (`scripts/ctp_i13_i15_windows_job_backend.py`). `ResumeThread`, `TerminateJobObject`, Job accounting queries, and `CloseHandle` are also synchronous calls made by that same supervisor process. While one is stuck, that process cannot check the deadline, publish `UNKNOWN`, or perform cleanup.

The process custodian and its `atexit` cleanup live in the same process as the backend. They do not independently retain or operate the Job controls if that process hangs. A Job's `KILL_ON_JOB_CLOSE` is a fallback termination request, not observed Job-empty evidence or proof that the supervisor returned by the deadline.

The current I13/I15 candidate launches only inert Python workers. It contains no CTP SDK call, native `Join`, or `Release`. A native call placed inside a Job worker could be terminated as a process-containment action, but that would produce `UNKNOWN` unless native close evidence had already been observed. It would not protect the supervisor's own process-creation or cleanup calls. The prior overlapped-I/O review and whole-command feasibility review therefore remain local evidence only: the former accepts a channel-custody subgate; the latter records late classification, missing top-level startup timing, and no native/SCM/P14 stall test.

The candidate's 0.5-second worker-stop reserve is useful scheduling margin for ordinary runs. It does not bound synchronous Win32 calls, storage calls, or OS scheduling. A finite chain of user-mode watchdog processes still leaves its outermost process subject to those limits.

## Architecture for a policy review

An implementable request-level design would use a trusted Windows guardian service that is installed, pinned, and running **before** the request. The caller submits a one-use, authenticated ticket over local IPC; it does not start the service or choose an executable, configuration, credentials, or provider. The guardian validates the caller and ticket, durably records acceptance, then starts a fixed worker suspended and atomically assigns it to a Job. The guardian owns the process and Job controls independently of the caller. All native client lifetime work would remain in that child Job; timeout or uncertain `Join`/`Release` yields `UNKNOWN`, never a successful-close claim.

**Proposed wording, not adopted:** “For the prestarted guardian route, the ticket deadline begins when the guardian durably accepts the authenticated one-use ticket (`T0`); `D = T0 + budget`. The guardian must stop worker admission at the configured stop deadline and durably publish `COMPLETE` by `D` only when process exit, Job-empty, and all required native terminal evidence are observed. Any timeout, unavailable evidence, termination, or late completion publishes `UNKNOWN`; caller timeout, process exit code, and missing response do not count as completion. Service startup and ticket delivery before durable acceptance are outside this request SLA.”

This changes the current command-start-to-Job-empty requirement into a ticket-receipt SLA and requires an explicit policy decision. It is not an unconditional wall-clock guarantee against a stalled Windows kernel call, storage system, or OS scheduler. A separate deployed monitor and a defined failure model would be needed to classify an unresponsive guardian; even that cannot establish a universal real-time bound on general-purpose Windows.

## External dependencies before reconsidering G1

- Approve or reject the ticket-receipt SLA wording; until then, retain the current strict gate.
- Deploy and independently review the prestarted guardian, service identity, IPC authentication/ACLs, fixed worker identity, durable one-shot admission, Job ownership, and restart/recovery behavior.
- Define how the guardian's own hangs and service loss are detected, what evidence remains durable, and which conditions force a permanent no-retry state.
- Independently test the deployed topology with inert injected stalls at process creation, termination, accounting query, handle close, receipt commit, owner death, guardian death, and worker death. Do not infer native-close success from process or Job termination.
- Complete separate artifact, native lifecycle, provider, account, and read-only route gates before any future provider attempt. This note performs none of them.

**Safety state:** strict G1 `NO_GO`; ordinary CTP preflight closed; `NO_WRITE / LIVE_NO_GO`.
