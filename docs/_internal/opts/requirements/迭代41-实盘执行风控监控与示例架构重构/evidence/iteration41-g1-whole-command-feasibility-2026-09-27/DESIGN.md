# G1 whole-command deadline feasibility probe

**Status: inert Win32 feasibility probe only; G1 remains CLOSED.** No repository or production source was edited. The probe uses only local named events, a disposable Job Object, and Python worker processes. It does not load CTP/native SDK/provider, credentials, private configuration, network, or SCM.

## Question and narrow result

This probe distinguishes an actual call to `WaitForSingleObject(INFINITE)` with an unsignaled event from a user-mode sleep before that call. It shows that the caller can classify the operation `UNKNOWN` after its deadline while a Job member is still alive, then cleanup can succeed after the deadline. In the captured 700 ms runs the classification function itself returned at D+2.3113 ms (`api_wait`) and D+9.5085 ms (`wrapper_sleep`), so neither is an on-time hard-deadline pass. The controlled wait is an intentionally indefinite Win32 wait, not an induced kernel/driver fault or arbitrary syscall hang.

For the `api_wait` trial, the worker signals `api_call_begin`, immediately calls `kernel32!WaitForSingleObject(gate, INFINITE)`, and would signal `api_call_return` only after the call returns. The controller observes begin, receives no return marker, and the process remains alive at D. It returns `UNKNOWN` from its bounded function shortly after D while the Job census is nonzero; after D, `TerminateJobObject` returns TRUE, process wait signals, and Job active count reaches zero. The event marker is emitted immediately before the direct API call; the source path contains no intervening sleep, but this is not a debugger/ETW kernel-stack proof.

For `wrapper_sleep`, the worker signals `wrapper_sleep_begin`, sleeps in Python longer than the remaining budget, and would only then emit `api_call_begin`. The caller reaches D with no API-begin marker. This is explicitly a pre-API user-mode delay.

This demonstrates the split between application response deadline and process cleanup, and the measured wait overshoot. It does **not** prove both caller return and Job-empty by the same D when an operation may fail to return.

## Reproduce

On Windows with CPython 3.11+: `python .\\probe.py --run-all`. It emits `results.json` and raw stdout/exit files. Each per-request `T0` is recorded immediately before creating the request's events, Job, and worker. Python interpreter startup for the top-level probe itself is outside this T0; therefore this is not a whole-command acceptance test.

## Architecture result

A caller can avoid waiting on a potentially nonreturning operation only by placing that operation behind an independent boundary and returning `UNKNOWN` at D. A remaining custodian can attempt Job termination and verify exact process exit plus `ActiveProcesses == 0`, but neither a process layer nor a Job Object API call is documented here as having a bounded return time. If `TerminateJobObject`, Job query, close, `CreateProcessW`, or the highest custodian's wait itself does not return, that custodian cannot prove by D that the worker tree is empty. Adding another process moves the last custodian; it does not eliminate it.

Including command launch and guardian/Job initialization in one whole-command D requires a supervisor already alive before T0 or a platform/external mechanism with bounded scheduling and call semantics. Treating a ready Windows service as outside D would be a narrower request-only contract and a requirement change. A real CTP/SDK Join/Release is not part of this probe. Ordinary preflight must stay fail-closed.

## API references

- Microsoft Learn, [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject): with `INFINITE`, the function returns only when the object is signaled.
- Microsoft Learn, [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects): Job Objects group/manage processes, can be terminated, and are signaled when all member processes terminate; the article does not state a hard wall-clock bound for the API calls.
- Microsoft Learn, [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject): describes terminating processes associated with a job; it is not an API return-time guarantee.

## Limits

- The controller uses a single fixed D per trial but T0 begins inside the already-started Python test process, not before the outer process launch/bootstrap.
- The tested blocking call is an intentional event wait. No arbitrary kernel/driver/API nonreturn was forced.
- The local `TerminateJobObject` and query calls succeeded. Their failure/hang paths and an independently hung top guardian remain untested.
- No evidence here closes startup Job setup, pipe/channel close, P14/SCM, native SDK shutdown, or the whole-command hard deadline.
- Any late cleanup is outside the recorded D; G1 remains CLOSED.
