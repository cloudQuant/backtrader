# G1 whole-command feasibility probe: independent QA

**Result: FEASIBILITY_ONLY; G1 CLOSED.** This is an independent rerun of the archived probe source on local Win32 only. It uses named events, a disposable Job Object, and isolated Python workers. It did not access CTP/native SDKs, provider/account data, private config, network, services, or production routes.

## Rerun result

Command: `python .\probe.py --run-all` (the exact frozen `probe.py`, SHA-256 `20cfcb77abe2e65bf05a0f5006bf97a2f9f05d42d546e856a5fe5ada8c3d7139`). Exit code: 0. Both trials use a 700 ms request deadline.

- `api_wait`: the user-mode `api_call_begin` marker was observed. In source it is set immediately before `WaitForSingleObject(gate, INFINITE)`, with no sleep between them. At the D check the process was still alive, the return marker was false, and Job active count was 2. The result was classified `UNKNOWN` at the recorded classification sample D+2.5956 ms. After the sample, the probe terminated the Job, observed process wait signaled and Job active count 0. Post-deadline cleanup took 8.6794 ms from its own start.
- `wrapper_sleep`: the `wrapper_sleep_begin` marker was observed. The source then sleeps 1.2 seconds before it can set `api_call_begin` and enter the Win32 wait. At D, process wait timed out, the result was classified `UNKNOWN` at the recorded classification sample D+2.3799 ms, and Job active count was 2. Afterward Job termination and process wait succeeded; the Job count was 0, with post-deadline cleanup reported as 4.9226 ms.

## Timestamp and marker interpretation

The archived field `bounded_function_return_qpc` is recorded immediately after assigning `caller_result`, **before** `TerminateJobObject`, the cleanup wait, and the zero-process census. It is a classification/UNKNOWN sample, not a measurement of the Python `one_trial` function return. `one_trial` actually returns after cleanup; that actual return timestamp is not separately recorded. The reported post-deadline cleanup duration also does not timestamp the precise instant when the zero census was observed. Therefore this QA confirms UNKNOWN classification while the Job was nonempty and later cleanup to zero, but it does not claim an exact function-return or Job-zero QPC.

The API marker is emitted in user mode immediately before the call. It is not ETW, a debugger stop, or a kernel-stack observation and does not independently prove the thread entered kernel wait before D. In `wrapper_sleep`, the recorded JSON does not explicitly sample the `api_call_begin` event at D; the 1.2-second sleep/source ordering establishes the intended pre-API branch, but this marker absence is not directly recorded. No arbitrary kernel, driver, native Join/Release, SCM, or whole-command hang was forced. Probe startup remains outside per-trial T0.

The original frozen archive files were left unchanged. This QA packet preserves the exact source copy, raw stdout/stderr, JSON result, and exit code; the manifest and ZIP bind the copied payload hashes.