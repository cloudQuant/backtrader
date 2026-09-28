# R10 Windows inert asynchronous ticket prototype

Status: AUTHOR PROTOTYPE ONLY / G1 CLOSED. This is not a Windows service, production route, or OS real-time guarantee.

R9 baseline manifest `98a8110a5c99e960d052c18d57c9aaedf3bd43fa61dc3271a8b7235a0280da81` and trials `c848ab2f51360399a399a16a441e66821eb3368ee36bdd44c17d2018dbd50dc7` are frozen copies. R9 final recorded P05 and both Popen wrapper caller returns at D+3 ms; the R10 request API returns on mailbox publication and leaves outcome polling to the caller.

The first R10 full run is preserved in `r10_trials_initial.json` (SHA `32bca66edba15ae73a7cf8777ecafcaabcd346df4326e69c39c49a44ae781040`) with its exact source, binary, build log, and runner under `first_run_failure/`. Its sole failed check was a harness key mismatch (`submit_result` vs the emitted `caller_submit_result`); this was not treated as an implementation pass or discarded. The final rerun corrects the assertion and retains all observed rows.

## Protocol

The single-slot mailbox is preconfigured before READY. Admission starts disabled; a pre-READY submit returns NOT_READY. An accepted submit is one atomic slot CAS, with no request-time process creation, pipe setup, queue lock, or I/O. A second submit returns BUSY. `poll(ticket)` is an atomic read only. The separate prestarted broker/reaper transitions the ticket to UNKNOWN at its first scheduled observation at or after one absolute monotonic D and poisons the slot. This is an asynchronous API model; it does not promise an OS scheduling deadline.

In P05, D tick `225406450`, submit result `0`, observed submit API duration `0.1 µs`, ticket UNKNOWN tick `225406453` (reaper lateness `3 ms`). Pending overlapped I/O at UNKNOWN `True`; final completion error `995`; caller poll observed `3`. The late success CAS saw state `3` and did not change final state `3`. Busy submit `1`, poisoned submit `2`.

Caller-death trial: caller killed `True` with pending I/O `True`; broker alive at caller terminal `True`, broker saw death `True`, final ticket state `3`, and writer completion error `995`.

Popen-before stage `1` and Popen-after stage `3` are wrapper-only stalls. The after case observed worker Job active count `2` before Job termination; both were fenced to empty. Outer Job test active processes `5` → `0`; all observed process handles signaled.

## Limits

UNKNOWN transition timing is recorded but can be late if the broker/reaper is not scheduled. The late-success attempt is an inert CAS injection, not an external result. P02/P03 do not inject true CreateProcessW hangs; P14 is absent; no higher custodian proves caller behavior if the reaper wedges. Launcher and synchronous prewarm/setup are outside D. No SCM, CTP, provider, credentials, private config, network, or default route was used.

Disposition: G1 CLOSED; R10 is local author evidence only.
