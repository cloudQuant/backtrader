# R9 Windows prestarted inert custodian prototype findings

Status: INERT PROTOTYPE ONLY / G1 CLOSED. This is a local process-topology experiment, not an SCM deployment or acceptance claim.

Platform: `Windows-10-10.0.26100-SP0`; Python `3.11.5`.
Reviewed design input: `R9_DESIGN_INPUT.md` SHA-256 `77500a63eabd0df5673b923458893fbd44c0d3ca1ec22c403dff95b98d869bd0`; design receipt manifest SHA-256 `ad6fb53200789e051fc93d76d073c54c6f2d7d9bfaea4b3e288da0bd055765c0`.
R8 frozen baseline: manifest `f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb`, trials `4c412a14af1cb5fe5ea5f6ff39f23d7952187e5f60bc2015f70d0098af6cf58a`.
R9 source SHA-256: `92c3bc3a2a85399473059e36f23572f48442778326dbd5cd2917413f1f740b2a`; trial log SHA-256: `c848ab2f51360399a399a16a441e66821eb3368ee36bdd44c17d2018dbd50dc7`.

## Caller deadline and pending I/O

The final P05 row reports D=1200 ms, deadline tick `223810700`, caller return tick `223810703`, lateness `3 ms`, and caller return by D=`False`. This is a failed hard-deadline sample. At that late return, I/O was still pending=`True`; the separate broker later canceled and consumed completion error `995` (Windows ERROR_OPERATION_ABORTED=995), then exited with its Job empty. The caller path performs only fixed-size shared-memory publication and atomic polling; the prestarted broker owns the connected pipe, OVERLAPPED/event, and 2 MiB buffer through final completion.

The first preserved trial log is `r9_trials_initial.json`; its SHA-256 is recorded in the manifest. The latest run’s structured `deadline_observations` lists absolute ticks and lateness for P05 and both Popen wrapper probes. Late UNKNOWN is classified as a failed caller return, never upgraded by later cleanup.

The caller-death row terminates the caller Job while the write is pending. It checks that the broker remains alive and observes caller death, then cancels and consumes final completion. The broker is outside callerJob but remains inside the outer Job.

## Sacrificial Popen boundary

A Python helper process is started and assigned to its worker Job during prewarm, before READY. At request time, one injection blocks at the outer Popen wrapper before child creation; another creates an inert Python child and then blocks before the Popen wrapper returns. The supervisor holds the worker Job handle before either request and terminates it at D; the post-create case checks the Job had at least two active processes before termination and became empty afterward. These probes wrap Popen before/after its real CreateProcess work; they do not hang inside the OS CreateProcess syscall.

Popen-before stage `1` returned at `223814406` vs D `223814403` (lateness `3 ms`); Popen-after stage `3` returned at `223816031` vs D `223816028` (lateness `3 ms`). Both caller deadline checks fail. Their eventual worker Job termination/empty proof is cleanup evidence only.

## Coverage by reviewed cases

P02/P03: partial wrapper probes only (blocked immediately before Popen creates a child, and blocked after a real inert child exists but before Popen returns). No true CreateProcessW hang was injected. P07: pending overlapped write + cancellation + 100 ms user-mode post-event hold, but no delayed kernel completion. P14: untested. The outer-Job test kills the five-process tree and observes all process handles signaled plus ActiveProcesses=0; it does not prove survival of a dedicated service reaper or caller return when that reaper wedges.

## Limits

The local supervisor is launched by Python `subprocess.Popen` during prewarm. That call is synchronous before the runner receives the duplicated outer Job handle, so this prototype does not prove a deadline over startup. No SCM service was installed. Win32 synchronous API hangs and kernel-level delayed I/O completion were not injected; the measured completion hold delays final completion consumption only. The outer Job test proves tree termination after the external duplicate is available, not caller return by D if the only custodian wedges.

R8 timing facts are distinct: the frozen R8 admission-sync trial and design receipt record D=1200 ms with caller decision at 1218 ms and no caller API return; an older replay finding recorded 1234 ms. R9 does not merge those samples, upgrade the R8 negative, or treat the R9 local topology checks as G1 acceptance.

No CTP/provider, credentials, private config, network route, SCM, default preflight, or production runtime path was accessed.
