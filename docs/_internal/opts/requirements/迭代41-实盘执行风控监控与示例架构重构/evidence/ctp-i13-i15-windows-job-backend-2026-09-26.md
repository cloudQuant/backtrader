# I13/I15 Windows Job backend offline candidate

Date: 2026-09-26

## Scope and status

`scripts/ctp_i13_i15_windows_job_backend.py` is a new, unregistered adapter for
the offline outer-watchdog protocol. It is not imported by an operator CLI,
runtime registry, CTP path, provider, SDK, or network module. Its test seam
accepts an injected `kernel32`-shaped object; the deterministic tests use only
that fake. One Windows-only test, when the host supports
`PROC_THREAD_ATTRIBUTE_JOB_LIST`, launches an inert local `sys.executable -I -c
pass` child.

This is a backend candidate, not an accepted I13/I15 command route. The real
local-child test covers one process on this host only. It does not establish
descendant behavior, failure recovery on every Windows build, a production
trust root, or acceptance of real provider work.

## Process and Job ownership contract

The adapter creates an unnamed Job and sets only
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. It does not enable
`JOB_OBJECT_LIMIT_BREAKAWAY_OK` or `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK`. It
then creates the launcher with `CREATE_SUSPENDED` and
`EXTENDED_STARTUPINFO_PRESENT`, with a single `PROC_THREAD_ATTRIBUTE_JOB_LIST`
value pointing at the Job handle. There is no create-then-assign fallback. If
the attribute API is unavailable or rejects the list, creation fails closed.

`CreateProcessW` receives the absolute executable as `lpApplicationName`, a
writable Unicode command-line buffer, the explicit working directory and
environment, and `bInheritHandles=FALSE`. The backend keeps the Job handle array
and attribute-list storage alive through `CreateProcessW` and destroys the
attribute list before returning. The launcher remains suspended until the
adapter queries Job accounting and observes one active process. Only then can
`resume_launcher` resume its primary thread.

Exit observation uses the process handle. Whole-tree observation queries the
Job's `ActiveProcesses`; a successful `TerminateJobObject` call is only a
termination request, so cleanup still waits for the process to signal and the
Job count to reach zero. Controls are closed only after both observations.
If cleanup cannot be confirmed, `retain_controls` transfers the session to a
module-level custodian and returns an opaque token. The token can be passed to
`resolve_retained_controls` for a later bounded retry. A token records custody,
not termination. Orphan Job handles from partial-creation/setup failures use the
same custodian and have a separate empty-query/close reconciliation path.

The module-level custodian is independent of a short-lived backend instance
and watchdog result. At host shutdown its registered cleanup closes retained
Job handles; `KILL_ON_JOB_CLOSE` asks Windows to terminate associated processes
when the last Job handle is closed. A Python `atexit` callback is not an
independent supervisor: it cannot run while this host is stuck inside a native
call or after abrupt host termination. Therefore neither this adapter nor the
Python watchdog proves a hard end-to-end deadline for a blocked host. A
separately supervised host process remains necessary for that property.

## Verification

The fake tests assert the Job-list attribute is populated before process
creation, creation is suspended and non-inheriting, the attribute backing
storage is retained through list deletion, Job kill-on-close is enabled,
unsupported setup does not create a process, ambiguous partial creation
returns a typed custody token, and unresolved Job state remains unknown until
the empty state is observed. Both an exception and a false `CreateProcessW`
result with only a thread handle are transferred into custody; the backend does
not close the thread or Job or claim process-exit evidence when the process
handle is absent.
That session remains unknown and unreleased because this adapter cannot
positively observe process exit without the process handle. The test then
simulates host shutdown to avoid leaving fake handles in the test process.
Other tests drop the backend and watchdog result and verify the module
custodian still retains a normal session until token reconciliation.

The Windows-only test uses only a local inert Python process. A pass is a
single-host smoke observation; it is not independent Windows Job acceptance.
No test reads private runtime configuration or markers, imports a CTP/provider
SDK, contacts a network endpoint, or builds a wheel.

The targeted command
`.venv\Scripts\python.exe -m pytest -q -p no:asyncio tests\unit\scripts\test_ctp_i13_i15_windows_job_backend.py`
passed **11 tests** on this Windows host, including the inert-child test, with
one existing pytest configuration warning (`asyncio_default_fixture_loop_scope`
is not recognized by this environment). Ruff and `py_compile` passed for the
new backend and test files.

## Platform references

- [`PROC_THREAD_ATTRIBUTE_JOB_LIST` and attribute value lifetime](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute): the attribute accepts a Job handle list on Windows 10 / Windows Server 2016 and newer; `lpValue` must remain valid until the attribute list is deleted.
- [`CreateProcessW`](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw): documents the separate application-name and command-line parameters, command-line mutability, creation flags, and handle inheritance behavior.
- [`JOBOBJECT_BASIC_ACCOUNTING_INFORMATION`](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information): `ActiveProcesses` is the number of processes currently associated with the Job.
- [`JOBOBJECT_BASIC_LIMIT_INFORMATION`](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information): defines `KILL_ON_JOB_CLOSE` and the breakaway flags deliberately left unset here.
