# R10 inert Windows async-ticket independent QA

Date: 2026-09-27. Scope: offline/local Windows fake only.

## Disposition

The frozen R10 payload is hash-consistent, and an independent disposable copy rebuilt and replayed with 9/9 checks passing. The replay supports only the one-shot asynchronous mailbox/ticket prototype and its inert local harness. **G1 remains CLOSED.** This is not G4, F14, CTP, provider, production, SCM, or default-route acceptance.

The author manifest SHA-256 is `da1252e1e25c20530a9cce358c35a1a90f0729dc7f60da85fe2600dd8790f6c3`; all 23 listed payloads in the independent frozen copy matched. Independent replay exit code was 0. Rebuilt executable SHA-256: `934b039175ce7382c815ffce2e077fb69d39182d5d942b6421a5049b510bd3bd`. C++ source SHA-256 remained `4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3` before/after replay; replay runner remained `6871645b9cecf3fd6d8d0d3520776814d4dc3ab683d6a09d8424146a39ddef7b`; the R9 baseline payload was unchanged. No process with a command/executable path pointing to this QA run remained at the cleanup check.

## Observations

- P05 Submit returned `SUBMIT_ACCEPTED` in the same sampled millisecond as request start (measured API duration 0.1 microseconds), 1,200 ms before D. The separate broker/reaper marked the ticket `UNKNOWN` at D+3 ms, poisoned the single slot, and rejected a later submit. An inert late-success CAS was blocked by `UNKNOWN`. The 2 MiB local named-pipe write was pending at UNKNOWN; cancellation drained with error 995 (`ERROR_OPERATION_ABORTED`), after which the broker and worker Jobs were empty.
- Caller-death case killed the caller while local OVERLAPPED I/O was pending. The broker survived, observed caller death, owned/canceled/drained the I/O (995), retained final ticket `UNKNOWN`, and exited with its Job empty. The caller itself was killed before it could return a poll result; its observed poll value `0` is not an UNKNOWN result.
- Popen-before / Popen-after tests block a prestarted Python helper around `Popen`. In the after case, the already-created child was in the worker Job before termination. These do not inject a kernel hang in `CreateProcessW`; P02/P03 remain wrapper-only.
- The outer Job test observed 5 active processes and terminated the tree to 0. This is a harness cleanup probe, not proof that a custodian survives a wedged broker.
- A separate QA-only derivative delayed the caller until D+50 ms before invoking `SubmitTicket`. The call returned `SUBMIT_ACCEPTED` (0) at tick 227608890, D+65 ms; the broker then marked `UNKNOWN` at D+81 ms and poisoned the slot. This reproduces late-intake acceptance. The derivative changed only `CallerMain` to wait past D and mapped a test-only `late-intake` mode to a non-writing request kind. Author frozen source/hash was not changed. The QA-only source SHA is `5be5f889fe417d0cd583af3b680906f824d218c6cc26a7e53ddabe860ddaa963`; tested binary SHA is `9421238d693101d7a0b8a2c2dadb815a3f25c02d57d299ceefac03e0fc0e54b4`. Caller, broker, worker and outer Job cleanup completed; outer Job active count was 0.
- Preserved first author run has one failed P05 assertion because its runner asked for key `submit_result`, while output used `caller_submit_result`; captured trial data showed result 0. The corrected final runner uses the emitted key. That initial failure remains preserved in the archive. The first QA-only late-intake launch also had a harness filename mismatch (`run_trial` expects `r10_custodian.exe`); no probe child launched, and the corrected rerun is retained alongside that log.

## Source boundary / limits

In `r10_custodian.cpp`, `SubmitTicket` (line 92) performs admission check plus one slot CAS and ticket read; `PollTicket` (101) is read-only. The broker transitions to UNKNOWN/poisons the slot and requests cancellation in `ReaperMarkUnknown` (257 onward); caller death is polled by the broker (322 onward). `WriterThread` (176 onward) waits on the local overlapped write and cancellation, then drains with `GetOverlappedResult`. After shutdown, broker line 340 calls `WaitForSingleObject(writer, INFINITE)`. Thus a cancellation/completion path that wedges can still block broker shutdown; this run exercised only successful cancellation and completion. No P14 blocking `TerminateJobObject`, query, cancel, or close failure was injected, and no higher custodian was demonstrated.

The author `SubmitTicket` has no direct deadline comparison. The delayed QA-only negative confirms a post-D caller can receive `SUBMIT_ACCEPTED` before the separate reaper changes the ticket to UNKNOWN; therefore the prototype does not reject expired intake at the API boundary. Request D starts after launcher/prewarm setup; synchronous setup and whole-command startup are outside this timer. Reaper scheduling lateness is measured, not bounded by an OS real-time guarantee. No SCM/startup D was tested.

No SDK, CTP/native provider, credentials, private configuration, account, network, or default route was used. Local fake/offline only.
