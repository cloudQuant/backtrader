# G1 r6 admission-boundary review — design-only receipt

## Scope and identity

This is a read-only adversarial design review of the frozen fake-only r6 candidate at `D:\temp\iteration41-g1-r6-warmed-worker-custodian-prototype-20260927`. Its manifest SHA-256 is `3053ce67aea77fa7b1486837adbdd20d4de86343182e687d4c511ebcec1380e7`; its freeze receipt SHA-256 is `646e4817126272f263f3681ffeb6c994497f633a255daf72196e41187f6ea017`. `manifest-audit.json` records exact file sizes and SHA-256 for all 18 manifest payloads; all match. The frozen candidate declares `REJECTED_FOR_HARD_WHOLE_COMMAND_DEADLINE; G1 REMAINS CLOSED` and has no real Win32, Job Object, independent service process, real control handles, CTP, provider, credentials, or default-preflight implementation.

No candidate or main-repository file was edited. Candidate source was copied to `frozen-copy` under this review directory. The only execution was fake/inert Python code against that copy.

## Finding

Changing only admission enqueue to a nonblocking queue operation would not establish a request-caller return deadline. In r6's fake prototype, the caller synchronously acquires `_active_lock` at `prototype/g1_warmed_worker_custodian.py:266-267`, calls `Queue.put_nowait` at line 270 before its timed `Event.wait` at lines 274-276, then calls `job.snapshot()` at line 295. `put_nowait` avoids waiting for queue capacity; Python's `Queue` still acquires its condition mutex. A lock holder can therefore delay it. The separate “custodian” and worker are Python threads (`:108-119`, `:186-206`), so a blocked thread is not independently killable and does not provide process isolation.

The production-shaped service-host function has the same boundary problem by explicit contract. `PreparedServiceHost._claim` takes a synchronous lock (`source/scripts/ctp_i13_i15_service_host_supervisor.py:80-85`). `supervise_prepared_request` executes `send_request_nonblocking` on the calling stack (`:500-512`), then only checks the deadline after return. The same pattern applies to launcher exit polling (`:554-557`), Job-empty polling (`:587-590`), control release (`:613-617`), Job termination (`:701-704`), termination-time exit and empty polling (`:739-744`, `:768-773`), and release (`:798-801`). `backend.retain_controls` is synchronous (`:395-400`); its deadline check also follows the call. The poll sleep/callback is synchronous too (`:657-659`). If any such operation never returns, its post-call check is unreachable and the request caller remains blocked.

Prewarm creates a separate availability boundary: `create_suspended_in_job` (`:233-240`), `resume_launcher` (`:272-285`), and readiness poll (`:296-312`) are synchronous. The source says to prepare before accepting requests (`:202-211`). This is the right admission ordering, but a hung startup still needs an external lifecycle supervisor to recover; the request deadline does not cover prewarm.

## Negative probes

1. Re-ran the frozen admission-enqueue probe from the isolated copy. Its JSON reports a 180 ms caller timeout, caller still blocked 54 ms past deadline while the injected enqueue stall remains held, and `UNKNOWN` with controls retained after releasing the stall. Full output is in `candidate-negative-probe.log`; the rerun modified only `frozen-copy/evidence`, outside the frozen candidate.
2. `sync_api_boundary_negative_probe.py` imports the copied `supervise_prepared_request` and supplies an inert fake session whose `send_request_nonblocking` blocks on an Event despite its name. At a 120 ms deadline, the calling thread remains blocked 52 ms after deadline. Once the fake is released, the function returns `UNKNOWN` and marks `operation_returned_after_deadline=true`. Log: `sync-api-boundary-probe.log`.

These are executable counterexamples to caller-deadline enforcement. They do not model Win32 scheduling or prove a native call's duration.

## Design disposition and acceptance evidence required

The request-serving caller must do only admission work with a defensible bounded/nonblocking contract and a timed wait. Every operation that may block—including send, process/Job polling, terminate, custody transfer, and control release—must execute away from that caller stack. An independently running custodian must own the real OS handles after admission and preserve them on `UNKNOWN`; a single-use host must not be reused or retried while cleanup is uncertain.

If a custodian can itself get stuck inside a native call, a higher-level process/service supervisor must be able to detect and recover that custodian. This is why queue-only changes or a second Python thread are inadequate under an unbounded-call failure model. OS Job evidence is also required for containment, but Job assignment and Job-empty checks alone do not bound the Python caller. On Windows acceptance, demonstrate that the launcher is created suspended and assigned to its Job before resume; the custodian retains actual Job/process/thread handles; target process exit and Job active-process count zero are independently observed before release; and gates/stalls at send, poll, terminate, retain, and release cannot hold the request caller past its operational timeout. A startup stall must leave admission closed and be recoverable by the outer lifecycle owner.

Windows is not a hard real-time operating system. State a measurable operational return target and tolerance, classify any late or uncertain operation as `UNKNOWN`, retain custody, and avoid claiming a mathematical hard real-time bound. A real G1 acceptance requires a real Windows backend/service and OS-verifiable Job/process evidence; this fake-only candidate cannot supply it. These requirements do not imply enabling CTP/provider activity or default preflight.

**Disposition: design review only; r6 remains rejected for hard whole-command deadline; no G1 PASS or real Windows acceptance is claimed.**
