# Independent G4 native lifecycle / G1 supervision review

Date: 2026-09-27 (Asia/Singapore)
Classification: `LOCAL_STATIC_REVIEW + LOCAL_INERT_FAKE_DEADLINE_NEGATIVE / G1_NOT_PASSED / G4_NATIVE_LIFECYCLE_NOT_ACCEPTED`

## Scope and hygiene

Read-only source review of SDK source at `D:\bt_api_py\bt_api\bt_api_ctp_source_synth_20260926` (HEAD `9976bcbbbe331ee77e2d90e05da08472259a625a`; `git status --porcelain=v1` was empty), Backtrader lifecycle call sites, the current G1 watchdog/Job/service candidate, and existing G1 evidence. No source files in either repository/worktree were edited.

The only executed test is `inert_blocking_deadline_probe.py`, a standalone inert fake importing only `scripts.ctp_i13_i15_outer_watchdog`. It imported no `bt_api_ctp`, SWIG/native CTP module, account/config/credential, and made no provider or network calls. No CTP route was opened. It does not exercise a real Windows Job, service installation, native API, or CTP Join/Release behavior.

## G4 SDK synchronous native boundaries

The CTP client layer directly calls native methods without a timeout-bearing wrapper:

- MD `start()` creates the native API and synchronously calls `RegisterSpi(spi)`, `RegisterFront`, and `Init`: `client.py:1501-1563`. In `block=True` mode it calls `_join_native_api()` synchronously at `1595-1600`; otherwise it starts the Join observer at `1603`.
- Trader `start()` creates its API, synchronously calls `RegisterSpi`, topic registration, `RegisterFront`, and `Init`: `client.py:3504-3572`. Its Join observer is a daemon Python thread: `3484-3502`.
- Both `_join_native_api()` implementations call `api.Join()` directly (`1395-1419`, `3448-3472`). After Join returns, the observer calls `_release_retired_ctp_native_session_after_join()`, which calls `api.Release()` synchronously (`client.py:302-351`, call at `334`). A timed `wait_native_join()` only waits on a Python event, capped at 60 seconds; its own doc says Join return does not certify Release or process emptiness (`1421-1429`, `3474-3482`; tracker wait at `231-243`). It cannot cancel a blocked Join.
- `stop()` first sets the startup-cancel event, but then can call `api.RegisterSpi(None)` synchronously while Join is active (`client.py:1616-1660`, `4552-4594`). When Join is not active, it calls `RegisterSpi(None)` and then `Release()` synchronously in one suppressed-exception block (`1662-1665`, `4596-4599`). Startup-abort and create-cancel cleanup also call these native methods synchronously (`1384-1392`, `1530-1535`, `3437-3445`, `3531-3536`). The cancel fence prevents later startup steps; it does not interrupt a call already entered.
- Generated wrappers forward straight to `_ctp` (`ctp_md_api.py:115-137`, `ctp_trader_api.py:800-825`). SWIG wraps Release/Init/Join/RegisterSpi in `SWIG_PYTHON_THREAD_BEGIN_ALLOW` / `END_ALLOW` (e.g. `ctp_wrap.cpp:472507-509`, `472553-555`, `472600-602`, `472865-867`, and trader equivalents `485926-928`, `485972-974`, `486019-021`, `486337-339`). This releases the GIL so other Python threads can run; it provides no cancellation of the native call.
- Vendor headers declare `Release()` as deleting the interface, `Init()` as starting work, and `Join()` as waiting for the interface thread to end, with no timeout parameter (`ThostFtdcMdApi.h:93-103`, `ThostFtdcTraderApi.h:518-528`). `RegisterSpi` is a synchronous void API (`Md:129`, `Trader:558-560`).

The Backtrader store's legacy CTP `disconnect()` calls both client `stop()` methods directly (`backtrader/stores/btapistore.py:2023-2035`). Separately, `_bounded_sdk_close()` uses a daemon thread and timed `thread.join()` (`5285-5313`): a timeout marks shutdown `INCOMPLETE` and blocks restart, but the native call/thread remains alive in that process. Broker/store timeout propagation therefore bounds waiting only where the underlying path cooperates; it cannot establish that a blocked CTP native call has stopped.

## G1 supervision interface and gaps

`run_outer_watchdog()` is explicit that the caller supplies one absolute deadline and that the backend's native calls must be bounded; Python cannot enforce a deadline while blocked inside a native API (`scripts/ctp_i13_i15_outer_watchdog.py:49-65`, `189-216`). Its cleanup still invokes `terminate_job()` synchronously (`358-379`) and later `release_controls()` synchronously (`381-424`); initial `create_suspended_in_job()` is also called synchronously (`445-459`).

The Windows backend creates a suspended process with atomic Job-list assignment and `KILL_ON_JOB_CLOSE` as its containment design (`scripts/ctp_i13_i15_windows_job_backend.py:8-18`). However, its `terminate_job()` directly calls `TerminateJobObject` (`481-488`); `release_controls()` synchronously queries and closes native handles (`499-534`); and its own source explicitly says `CreateProcessW` cannot be interrupted by this Python caller and may return after the deadline (`1017-1023`). Its retained-control registry is module-process-local (`563-603`), not a separate guardian that survives a blocked host. Closing a Job for kill-on-close is a containment request, not proof that CTP detached callbacks, returned Join, or ran Release cleanly.

The two-Job read-only service candidate makes the limitation explicit. It says it does not install a Windows Service or establish production pipe ACLs (`windows_guardian_service.py:1-9`). Its two-stage layout waits for Job1 process exit, Job-empty evidence and control release before Job2 receipt writing (`3776-3790`). But `_serve_one_readonly_os_request()` explicitly says synchronous anchor/Win32 setup in the service process is still outside an independent host watchdog and therefore it does not establish a whole-command hard deadline (`4108-4124`); anchor and dependency verification run before the request deadline is established (`4149-4155`). Its public client distinguishes a local IPC wait timeout from service completion and says the timeout does not prove the service Job stopped (`4342-4351`, timed event wait at `4467-4480`).

Existing local G1 evidence agrees: r4 is `LOCAL_FAKE_CLASSIFICATION_PASS / HARD_DEADLINE_NOT_PASSED / G1_NOT_PASSED`; synchronous terminate/release late returns outlive the caller deadline and the candidate lacks real Job/named-pipe/guardian wiring, with startup/prewarm outside the request deadline (`ctp-g1-prestarted-host-r4-independent-review-2026-09-27.md:3-9`). The service deadline counterexample records blocked receipt creation after worker cleanup, and says no real SCM/Job/CTP was exercised (`ctp-g1-service-deadline-fake-counterexample-2026-09-27.md:3-7`). The r6 output-channel review says its local tests do not prove complete two-Job supervision, Session0 token transfer, protected deployment, or native CTP; G1 remains NOT_PASSED (`ctp-g1-output-channel-r6-post-resume-independent-review-2026-09-27.md:3-5`).

## Independent inert negative probe

Command: `python -B D:\temp\g4-g1-native-supervisor-review-20260927\inert_blocking_deadline_probe.py` (Python 3.11.5; bytecode disabled). It used an injected fake session whose `terminate_job()` or `release_controls()` waits on a local `threading.Event`. The watchdog ran on a test thread; the harness observed it after the same 240 ms absolute deadline, then opened the fake gate so the test could finish.

- Fake `terminate_job()` case: caller still blocked 42 ms beyond the hard deadline; after unblocking, result was `timed_out / outer_worker_deadline_exceeded` at 282 ms.
- Fake `release_controls()` case: caller still blocked 56 ms beyond the hard deadline; after unblocking, result was `timed_out / outer_deadline_exceeded` at 296 ms.

This is a direct negative for the synchronous watchdog interface's whole-call deadline promise when these injected methods block. It is a local Python fake only; it neither predicts Windows kernel behavior nor establishes real process containment.

## Interface requirements before any hard-deadline or clean-close claim

1. Capture one trusted monotonic absolute deadline at the externally visible operation boundary. Carry it unchanged through protected-anchor/dependency verification, any prewarm/bootstrap, pipe/token/channel setup, process creation, worker execution, receipt/output, termination, exit/Job-empty observation, and native-handle cleanup. The current inner watchdog begins too late to include all of those operations.
2. Keep every potentially blocking CTP operation inside the killable worker process assigned to its Job before resume: API creation; SPI/front/topic registration; Init; synchronous requests; callback detach via `RegisterSpi(None)`; Join; and Release. Do not rely on daemon threads or Python event waits to interrupt them.
3. Keep the hard-deadline owner outside that worker Job. Provide a separately supervised host/custodian path able to terminate the worker Job even if the request supervisor blocks in CreateProcess, TerminateJobObject, CloseHandle, output/receipt I/O, or another synchronous OS/filesystem operation. Its own process lifetime, bootstrap, Session0/token transfer, pipe ACL, and response path must be wired and independently bounded. The current local module custodian is not that host.
4. Distinguish containment from orderly native close. A clean-close receipt needs the ordered evidence that callback detach returned when an SPI was registered; if Init was entered, Join returned before Release; Release returned exactly once; worker exit was observed; and the entire worker Job was observed empty with controls closed before the same deadline. If Init was never entered, the receipt must say so and still prove detach/release return and process/Job cleanup. Forced Job termination or an IPC timeout is `UNKNOWN`/incomplete for clean close, even if containment is later confirmed.
5. Preserve opaque custody of unresolved Job/process controls outside a returning request object. If cleanup or observation misses the absolute deadline, retain the controls under the external custodian and report `UNKNOWN`; do not release ownership or turn a late result into an on-time success.

## Conclusion

The SDK source exposes multiple synchronous no-timeout native entry points in normal start/stop and Join/Release cleanup. A process Job around the complete SDK client lifecycle is necessary for process-tree containment, but current code and evidence do not establish a hard whole-command deadline or clean native Release under timeout. The local inert negative test confirms the watchdog call stack itself can return after deadline when termination/release fakes block. Classification remains local static/fake evidence only: G1 is not passed; G4 native Join/Release is not accepted. The default CTP route was not changed.

