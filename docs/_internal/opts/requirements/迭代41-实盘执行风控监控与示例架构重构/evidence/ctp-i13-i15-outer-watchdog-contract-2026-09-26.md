# I13/I15 outer watchdog fake contract (2026-09-26)

## Status

`scripts/ctp_i13_i15_outer_watchdog.py` defines an offline orchestration
contract for a future outer process supervisor. It accepts a caller-owned
absolute monotonic deadline and an injected process/Job backend. Its only
process target is a fixed parent launcher command. It has no Windows API
implementation, CLI registration, config or marker access, child output
capture, or provider/SDK imports.

The adjacent unit tests use synthetic sessions only. Their results establish
the Python ordering and fail-closed result rules for those fakes; they do not
show that Windows Job Objects have been created, assigned, terminated, or
observed on Windows. No I13/I15 command has been launched by this contract.

## Contract

The caller captures one `deadline_monotonic` before launcher preparation and
passes that exact deadline to the outer supervisor. A backend must create the
launcher suspended and atomically inside one Job, return process and Job
controls plus positive assignment evidence, and leave the launcher suspended.
The supervisor resumes it only after checking assignment evidence. This must
cover the launcher and every descendant that it can create.

All backend polling methods must be non-blocking. Creation, resume, whole-Job
termination, and handle release must return within the remaining deadline.
The supervisor adds no cleanup grace after that absolute deadline. At expiry
it requests whole-Job termination, then accepts cleanup only when the process
exit, Job-empty state, successful termination request, and control release are
all observed. If any fact is unknown, it asks the backend to escrow available
controls and reports `unknown` containment. An expired deadline remains a
timeout even when termination and cleanup are confirmed.

When cleanup cannot release or verify the native controls, the runner transfers
the session to `backend.retain_controls(session)`. The backend must keep a strong
reference in a long-lived host-owned custodian that remains reachable after the
backend adapter and result are discarded. It returns a non-empty opaque
retention token only after taking custody. The token is an internal identifier,
never a path or raw native handle, and is omitted from the result's default
representation. The result sets `controls_retained=True` and includes that
token only on this positive confirmation. If escrow cannot be confirmed,
`controls_retained` is unknown and `retention_token` is absent; a local Python
reference that disappears as the call returns is not custody evidence. The
backend must provide a separate way to reconcile and eventually release each
token. If creation raises before returning a session after native controls were
acquired, the backend must clean them up or raise `OuterBackendCreationError`.
That typed error can carry the retention token only after the host custodian has
taken ownership. An untyped exception has no custody evidence and is reported
as unknown without a token.

If the injected monotonic clock, wait function, or session operation raises or
is interrupted after session creation, the runner does not let that exception
escape. It requests termination and either records verified cleanup or attempts
the same backend escrow; failed escrow is reported without claiming custody.

The result contains process/Job facts, an exit code, and an optional backend
retention token. `state="exited"` means the launcher exited and its Job was
empty; it does not mean that an I13 or I15 diagnostic passed. Candidate
completion still requires the inner launcher receipt, native close evidence,
and the already documented gates.

## Fake verification

`tests/unit/scripts/test_ctp_i13_i15_outer_watchdog.py` covers normal launcher
exit, timeout with confirmed whole-Job cleanup, timeout with unknown cleanup,
launcher exit while a descendant remains, unknown atomic assignment, an
already expired deadline, immutable command/environment snapshots, and
positive/negative backend escrow ownership after the runner returns, including
unconfirmed handle release, runner/backend disposal, and interrupted waits or
clock reads, plus partial creation failures with and without a custody token. No
runtime config, marker, credential, provider, SDK, socket, or child process is
used.

## Unresolved production requirements

The injected backend contract is intentionally not a Windows implementation.
In particular, this work does not validate `PROC_THREAD_ATTRIBUTE_JOB_LIST`,
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, Job accounting, retained-handle behavior,
or assignment/termination failure windows with Windows fault injection. Python
cannot force an arbitrary native backend call to return by a monotonic
deadline. A real hard return bound therefore still needs an independently
supervised outer host whose own failure cannot strand the launcher Job, plus
Windows-specific integration, escrow-lifetime, and fault tests. Until that
exists and receives independent review, this fake contract is not evidence that
the whole command has a hard Windows deadline and does not enable ordinary
preflight or a live route.
