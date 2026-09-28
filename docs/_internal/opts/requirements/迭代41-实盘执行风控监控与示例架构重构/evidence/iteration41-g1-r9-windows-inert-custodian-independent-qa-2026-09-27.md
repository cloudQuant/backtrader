# R9 Windows inert custodian independent QA — 2026-09-27

## Disposition

**G1 CLOSED.** Classification: independent Windows rebuild/replay of the inert local prototype; negative deadline evidence retained. This is not service deployment, whole-command startup proof, G1 acceptance, or CTP/native/provider acceptance.

## Frozen input and archive checks

- Candidate directory: D:\temp\iteration41-g1-r9-prestarted-inert-custodian-20260927
- Candidate manifest SHA-256: 98a8110a5c99e960d052c18d57c9aaedf3bd43fa61dc3271a8b7235a0280da81
- Author ZIP SHA-256: 2055fb8329a06d80abe8fc52ae2d2fec25674686300defe96192faf3a4e44f3a; ZIP CRC test passed.
- External entry-index SHA-256: 1957b0bdc47c26903de96eed6a8c08bb4d25613d56d495de2c3add2198852665. The ZIP has 20 members: 19 indexed candidate files plus the embedded self-index. All 19 index entries and the 15 manifest payload hashes/byte lengths match.
- Independent extraction was to D:\temp\iteration41-g1-r9-independent-qa-20260927\frozen-copy. The archived C++/Python harness uses local named-pipe IPC and local inert child processes; inspected source has no provider/network route. No CTP SDK, credentials, SCM, or default runtime route was used.

## Independent Windows rebuild and replay

On Windows 10 build 26200 with Python 3.11.5, the frozen copy rebuilt with exit 0. Rebuilt custodian SHA-256: b5b8fb4df22110f9afb3c059c0caa8ba21038f2ee5d442bbc4f74435c3d83204; the archive's prior executable hash was 6db48747e23fd766af659b37511c9c010b1849c8836f45e7d0564a93d59e8891. Source inputs were unchanged: 10 of 19 indexed files stayed byte-identical, including r9_custodian.cpp, run_r9_trials.py, r9_sacrificial_popen.py, both R8 baselines, and the initial failed trial. The nine changed files are generated run/build outputs or regenerated manifest/receipt/findings.

Replay harness exit was 0 while its structured checks were 6 passed / 3 failed. The three failures are preserved and are the expected acceptance negatives:

| Trial | Request start tick | D tick | Caller return tick | Lateness | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| P05 pending 2 MiB broker write | 224356140 | 224357340 | 224357343 | 3 ms | CALLER_RETURN_LATE |
| Popen-before wrapper | 224359796 | 224360996 | 224361000 | 4 ms | CALLER_RETURN_LATE |
| Popen-after wrapper | 224361421 | 224362621 | 224362625 | 4 ms | CALLER_RETURN_LATE |

The runner returns process exit 0 despite those three false hard-deadline checks; the structured failed_checks are authoritative for this replay. Later cleanup does not repair caller lateness.

### Custody and cleanup

- P05: the caller terminal event and late API return occurred while the broker's overlapped write was still pending. The broker later completed cancellation with Windows error 995 (ERROR_OPERATION_ABORTED) at tick 224357578; its 100 ms delay is a user-mode hold after event observation, before GetOverlappedResult.
- Caller-death: request start 224358015, D 224359215; caller was killed while pending, API return was absent, broker observed caller death and survived, then drained cancellation with error 995 at tick 224359328. Caller and broker Jobs ended empty.
- Outer Job: ActiveProcesses was 5 before termination and 0 after; TerminateJobObject succeeded, all five process handles signaled, and termination plus empty observation took 15 ms.
- Independent post-run process check examined 25 PIDs from all trial markers: no same PIDs remained; no r9_custodian.exe process or sacrificial Python sleep(600) helper remained.

## Limits

P02/P03 are Python Popen wrapper stalls immediately before child creation and after a real inert child exists but before Popen returns. They do not inject a hang inside CreateProcessW/kernel process creation. P07 is a real pending overlapped write with CancelIoEx plus a 100 ms user-mode completion-consumption hold, not delayed kernel completion. P14 was not tested; no TerminateJobObject, QueryInformationJobObject, CancelIoEx, or CloseHandle stall was injected. Supervisor launch and synchronous prewarm happen before request D; no SCM service or whole-command/startup D was proven. This replay therefore leaves G1 CLOSED.
