# Ordinary CTP preflight supervisor review (independent, inert-only)

**Disposition: `NO_GO_IMPLEMENTATION_FOR_CURRENT_G1_WORDING`; G1 and ordinary 013_3 preflight remain closed.** This package is a hash-bound review and verification plan, not a supervisor candidate and not real CTP acceptance. No source in the main tree was changed.

## Scope and safety

I inspected the ordinary CLI admission gate, read-only CTP composition/shutdown path, the unregistered I13/I15 outer watchdog and Windows Job backend, and existing G1 whole-command/R10/R11 evidence. Tests below use fake kernel APIs or local inert Python sleep/event children. They do not import CTP SDK/provider code, read private runtime config or credentials, contact a network/account, or issue CTP requests. The default CLI path remains unchanged and fail-closed.

The byte-exact frozen source payload is in [author-review.zip](author-review.zip) and bound by [source-manifest.json](source-manifest.json); the three cited design docs are expanded in [frozen-inputs/evidence-docs/](frozen-inputs/evidence-docs/). Raw stdout, JUnit, and exit codes are in [raw/](raw/).

## Ordinary preflight path

- `backtrader_runtime/cli.py:1481-1499`: establish registered runtime identity, then reject 013_3 ordinary `preflight` with reason `ctp_simnow_preflight_supervisor_required`; this is before config loading, secret resolution, SDK import, provider/network access, and dispatch. Only non-CTP or other registered runtime commands proceed to validation. The targeted guard test `test_registered_013_3_preflight_fails_closed_before_config_or_provider_io` monkeypatches config loading, credentials, socket, dispatch, and SDK import as traps and observed zero touches.
- If the gate were ever lifted, `cli.py:1552-1559` dispatches into `ctp_simnow_operator.py`; `ctp_simnow_readonly_runtime.py:477-603` performs artifact/import checks, credentials resolution, creates the native read-only factory, and performs the TD and MD observations. `ctp_preflight.py:753-844` makes synchronous session open, identity, query, final identity, and close calls.
- `ctp_sdk_readonly.py:148-269, 270-363, 717-755` accepts bounded timeouts and checks close evidence, but calls `stop_and_wait(timeout=...)` or synchronous `stop()`, then Python `thread.join(timeout=...)`. A timeout parameter is not a bound on a call that blocks before returning; a wrapper-level timeout does not prove native Release/Join completion. This path must execute only inside a separately supervised worker if it is ever re-enabled.

## Supervisor boundary and exact blockers

```text
OS launches CLI process                         outside a deadline made inside CLI
  CLI policy gate                               currently rejects safely
  outer-watchdog caller                         starts/owns D only after it exists
    synchronous backend setup
      CreateJobObject / attributes / CreateProcessW
      CreateProcessW may not return to deadline checker
    Job-contained suspended launcher
      resume after assignment is observed
      native client startup / query / stop / Join
    cleanup on the same custodian
      TerminateJobObject / process wait / Job query / CloseHandle
      any call may fail, block, or be unobserved
    receipt write
      may itself complete after D
```

- `scripts/ctp_i13_i15_outer_watchdog.py:189-233, 348-420, 446-447` carries one caller-supplied deadline and converts missing evidence to `UNKNOWN`; cleanup is synchronous on that same caller. The backend contract itself says a Python caller cannot enforce a deadline while a native API call blocks.
- `scripts/ctp_i13_i15_windows_job_backend.py:766-1017` prepares a Job with `KILL_ON_JOB_CLOSE`, uses `PROC_THREAD_ATTRIBUTE_JOB_LIST`, creates the launcher suspended, and only resumes after assignment is observed. This addresses the ordinary post-`Popen` assignment gap. Its own comment at `1017` explicitly says `CreateProcessW` cannot be interrupted by this Python caller. `481-519` performs synchronous termination and releases controls only after process-exit and Job-empty observations. `TerminateJobObject(TRUE)` remains a termination request, not proof of process exit or Job emptiness.
- `scripts/ctp_i13_i15_inert_deadline_supervisor.py:222-280` records `UNKNOWN`, asks for Job termination, and writes a receipt. Receipt creation/write is after the watchdog result and can be late; it is not by itself proof that the caller got a result by D. The module documentation explicitly excludes a blocked kernel call in the supervisor, machine suspension, and OS failure.
- Existing Windows Job custody is in-process. A separate service/reaper can contain the native worker and outlive a request caller, but the service's highest native call is still a synchronous boundary. Another guardian moves that boundary; it does not remove the topmost custodian problem. If the last live observer is blocked or not scheduled, no user-mode code can prove process exit plus Job-empty by D.
- G1 whole-command D must include process launch/bootstrap. CLI code cannot timestamp before Windows starts that CLI. `R11_G1_HARD_DEADLINE_AUDIT.md` says an already-running outside owner must stamp T0 if launch is in the promise; a READY-before-request service is a narrower request-only contract and cannot be labeled whole-command G1.

## Verification run

Environment: Windows 10 build 26100, CPython 3.11.5, `.venv\Scripts\python.exe`. No provider/native SDK import occurred.

1. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv\Scripts\python.exe -B -m pytest -p no:asyncio tests/unit/scripts/test_ctp_i13_i15_outer_watchdog.py tests/unit/scripts/test_ctp_i13_i15_windows_job_backend.py tests/unit/scripts/test_ctp_i13_i15_inert_deadline_supervisor.py -q --tb=short --junitxml=<qa-root>\focused.junit.xml`
   - 65 passed, 0 failed, 0 skipped, 28.41 s; one existing `PytestConfigWarning` for unknown `asyncio_default_fixture_loop_scope`.
   - Composition: 34 fake watchdog tests, 23 fake Win32 API/Job state tests, and 8 inert-supervisor tests. On this host the inert process test `test_supervisor_kills_blocked_inert_service_after_owner_death` ran with a disposable Job and local Python children.
2. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv\Scripts\python.exe -B -m pytest -p no:asyncio tests/unit/runtime/test_ctp_simnow_operator_route.py::test_registered_013_3_preflight_fails_closed_before_config_or_provider_io -q --tb=short --junitxml=<qa-root>\cli-gate.junit.xml`
   - 1 passed, 0 failed, 0 skipped, 0.74 s; same existing pytest config warning.

These results validate local fail-closed state contracts, local child containment on this Windows build, and the no-side-effect CLI gate. They do not validate arbitrary kernel/API nonreturn, production service custody, native SDK behavior, or a hard whole-command deadline.

## Smallest useful future acceptance plan

Keep the ordinary CLI rejection. If the owner formally narrows the requirement, define and test a separate **request-only cooperative deadline SLA** for an already-READY, prewarmed service: T0 at admission publication; no request-time process creation, synchronous pipe/queue/lock, credential lookup, SDK import, or client construction on the caller; one immutable D carried across all participants; fixed-size async ticket; classify `UNKNOWN` at the first scheduler observation at/after D; poison the slot and retain controls until every endpoint has consumed its exact I/O completion and the assigned request Job reports process signal/exit code and `ActiveProcesses==0`; never let late cleanup upgrade the result. State that this is not a hard caller-return guarantee and excludes OS non-scheduling/nonreturning kernel calls.

For the current stricter G1 wording, acceptance requires a platform/external trust mechanism with documented, independently verifiable bounds over scheduling, process creation, termination, Job census, handle close, and receipt delivery, plus one T0 before CLI launch. A Python/C++ process tree or an extra user-mode custodian alone is insufficient. Any failed/late/missing observation is irrevocably `UNKNOWN`; do not re-enable ordinary preflight on these local tests.

## Existing G1 evidence consulted

- [`DESIGN.md`](frozen-inputs/evidence-docs/DESIGN.md), SHA-256 `a80531c392b0b8db660be7bb0e3d7295068f48d5ef65ac56383f32f5f1cd6c2e`: inert `WaitForSingleObject(INFINITE)` feasibility probe; it returned `UNKNOWN` just after D, then cleanup completed after D; not a hard deadline pass.
- [`R11_G1_HARD_DEADLINE_AUDIT.md`](frozen-inputs/evidence-docs/R11_G1_HARD_DEADLINE_AUDIT.md), SHA-256 `cb100aa79f695124c87e1ccdd228090227e557eec2c4f40b02f2104f38f98401`: request boundary, whole-command T0, custodian and pending-I/O limits; R11 is design-only.
- [`REPORT.md`](frozen-inputs/evidence-docs/R10_CHANNEL_FAULTS_REPORT.md), SHA-256 `b3a510f78702c62f93cc538771c484929f1d7551e6428cedf99a2090ecf37b12`: independent R10 wrapper/API failure probe. The API fault cases are wrapper delay before API entry; no actual Win32 kernel hang or production custodian recovery was demonstrated.

**Final conclusion:** `NO_GO_IMPLEMENTATION_FOR_CURRENT_G1_WORDING`. No blocker is fixed by the existing code or another user-mode layer. Keep `G1 CLOSED`, ordinary preflight disabled, `NO_WRITE`, and `LIVE_NO_GO`.
