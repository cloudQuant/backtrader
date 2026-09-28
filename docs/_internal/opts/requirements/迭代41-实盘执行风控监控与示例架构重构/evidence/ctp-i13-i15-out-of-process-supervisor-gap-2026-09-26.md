# I13/I15 out-of-process supervisor: G1 gap and acceptance contract

Date: 2026-09-26

## Decision

**G1 remains unaccepted.** Do not add a thin `subprocess.Popen` wrapper and
describe it as a trusted, hard-deadline supervisor. The current Windows Job
backend is a useful process-local adapter, but this checkout has no independent
trusted host identity, host lifecycle, authenticated control channel, or
external process that can terminate a stuck host. Implementing that boundary
requires a separately reviewed launch/trust design; the missing properties
cannot be established by a fake-only wrapper test.

This review made no runtime, CLI, provider, network, build, wheel, or marker
changes. The existing fake watchdog/backend suite was run on 2026-09-26 with
the Windows inert-child test enabled: **28 passed**, with one pre-existing
pytest warning for the unsupported `asyncio_default_fixture_loop_scope`
configuration option.

## What the current code proves

`run_outer_watchdog()` accepts an absolute deadline and invokes an injected
backend in its caller process. `WindowsJobBackend` creates the launcher
suspended with `PROC_THREAD_ATTRIBUTE_JOB_LIST`, observes Job accounting, and
retains unresolved controls in a module-global custodian. Its `atexit` handler
closes Job handles with `KILL_ON_JOB_CLOSE`. The local inert-child test covers
one direct child on this Windows host; fake tests cover API order and failure
classification.

The containment and custodian are process-local. A second Python process
cannot reconcile a token held in the first process's `_CUSTODIAN`. If the
process that owns that custodian exits, its `atexit` handler closes the Job;
that is a shutdown termination request, not a persistent service or durable
token registry. `run_outer_watchdog()` supervises only the command passed to
it. The source/preflight/import/setup seam in `parent_launcher.py` is not
executed inside this watchdog's process tree. The backend checks the supplied
deadline before creation, but the synchronous native calls themselves are not
preemptible by this Python loop.

Relevant implementation points:

- `scripts/ctp_i13_i15_outer_watchdog.py`: `run_outer_watchdog()` accepts the
  caller deadline and calls `create_suspended_in_job()`.
- `scripts/ctp_i13_i15_windows_job_backend.py`: `_ProcessCustodian` and
  `_CUSTODIAN` hold controls only for the lifetime of this process; the
  registered `atexit` handler closes them. `resolve_retained_controls()` can
  only reach that same in-process registry.
- `scripts/ctp_i13_i15_parent_launcher.py`:
  `prepare_candidate_import_and_job_setup()` performs preflight, source seal,
  import, and the injected setup callback outside the current watchdog unless
  a future caller explicitly launches the complete parent launcher as its
  child.

## Minimum safe host topology

The next implementation should separate three roles and keep the control
ownership explicit:

1. **Trusted caller / guardian.** A deployed, independently pinned entry point
   captures the single command deadline before host preparation. It launches a
   dedicated host process from captured, hash-checked bytes or a protected
   signed installation. It retains the host process handle, waits against the
   same deadline, and can terminate the host if it stops responding. This
   caller is outside the candidate host and its native operations.
2. **Long-lived supervisor host.** The host validates its own release identity
   and the externally pinned candidate descriptor before runtime imports. It
   owns the outer Windows Job and all its process/Job handles. It atomically
   launches the complete trusted parent launcher suspended in that Job, then
   resumes it only after assignment evidence. The parent launcher performs
   source verification, leases, config/pair setup, metadata work, marker
   boundary, candidate child, and native close inside the supervised process
   tree. The outer deadline therefore covers setup, child work, termination,
   and close observation. The host remains alive until the Job is empty and
   every handle is released, or it records an unresolved token in its own
   custodian.
3. **Candidate parent launcher and descendants.** The complete candidate
   launcher runs inside the host-owned outer Job. It may use the existing
   nested Job backend for narrower worker containment, but breakaway is denied.
   Source/artifact leases remain owned by the launcher until worker cleanup;
   forced launcher termination lets Windows close those handles. Outer success
   still requires the launcher receipt, process exit, Job-empty observation,
   and control release.

The host must not exit immediately after returning an unresolved token. A
protected local IPC endpoint (for example, a named pipe with an explicit ACL
and client identity check) must support status, reconciliation, and explicit
release while the same host custodian still owns the native controls. The
wire protocol contains only a request ID, candidate ID, host instance ID,
bounded deadline, fixed command digest, value-free state, and opaque random
token. It must never serialize a native handle, path, account value, credential,
or provider result. Tokens are host-instance scoped. If a host dies or a token
is unknown, a reconnect must report `unknown`; it must not infer that the
process tree was absent or that cleanup succeeded. The host shutdown path asks
Windows to terminate contained processes by closing its kill-on-close Job,
but that event does not create a positive post-mortem cleanup receipt.

## Deadline and kill contract

Use one absolute Windows `QueryPerformanceCounter` deadline for the complete
invocation. The trusted caller captures it before host preparation and passes
the integer deadline tick value and frequency in the authenticated request.
The host reads QPC itself, verifies the frequency/domain contract, rejects an
expired request, and computes remaining time from that same absolute value at
every stage. Do not send a fresh relative timeout per stage, restart the clock
after host startup, or use a result timestamp as a replacement budget. Tests
must inject a shared fake QPC source to prove that host bootstrap, parent
launcher setup, child runtime, termination, and handle close all consume one
budget. Production use still needs a Windows-specific check that both
processes use the same system-wide QPC domain and frequency.

If the parent launcher becomes unresponsive, the host reaches the same
deadline, requests `TerminateJobObject`, and waits only within the remaining
budget. If the host itself becomes unresponsive inside a native API, the
independent guardian waits on its retained host process handle and calls
`TerminateProcess` at the same deadline. The host's process termination closes
its only non-inheritable Job handle; `KILL_ON_JOB_CLOSE` then requests
termination of the complete child tree. The guardian verifies the host process
signaled, but cannot manufacture a positive Job-empty or native-close receipt
after forcibly killing the host.

This bounds the candidate host under the documented OS assumptions; it does
not prove termination through a kernel hang, machine suspend, process handle
corruption, administrator/kernel interference, or a guardian that itself is
unresponsive. A deployment claiming a hard end-to-end bound must name the
highest independently supervised process and its OS restart/termination
mechanism. Windows Service Control Manager restart-on-crash alone is not a
watchdog for a live but hung service. Do not call the current Python watchdog
an independent guardian.

## Trusted-entry and ordering contract

The host entry must have an identity anchored outside this writable checkout:
an administrator-controlled signed install or an externally reviewed digest
and fixed interpreter identity. A digest read from the same checkout as the
module it supposedly authenticates is not a trust root. The host must start in
an isolated interpreter mode, validate its captured entry bytes and external
descriptor before runtime imports, and use a fixed protocol version. No
ordinary CLI, inventory registration, runtime route, environment override, or
provider/SDK shortcut is part of this slice.

Start the command budget before opening/capturing/verifying the host entry.
The trusted entry then starts the host; the host validates the complete
candidate/launcher pin and source closure before importing runtime modules.
The host starts the **whole parent launcher** inside the outer Job before
candidate setup begins. Within the launcher, retain the existing sequence:
source and interpreter seal, dependency/artifact validation, config/pair seal,
bounded precheck, metadata stage, candidate marker, candidate worker, native
close, and final receipt. A failure at any stage remains failure/unknown and
must not permit later marker/provider work. The outer host does not parse the
private config or touch markers itself.

## Concrete implementation gaps

1. There is no protected host executable/script release identity or externally
   supplied descriptor for this entry point. Existing `ExternallyPinnedDescriptor`
   is an injected library input, not a deployed caller.
2. There is no trusted host process creation/guardian layer, process-handle
   lifecycle, or independent timeout kill path. The current Job owner and
   `atexit` callback are in the same Python process as the watchdog.
3. There is no authenticated local IPC or cross-process custodian registry.
   Current retention tokens are random process-local dictionary keys and do
   not survive process exit.
4. The candidate source/setup pipeline is not yet executed as the complete
   child command under the outer Job. The current parent-launcher function is
   a dependency-injected library seam.
5. Absolute deadline transfer is not specified for a process boundary. The
   current API passes a Python float to a child backend in the same process;
   it has no QPC tick/frequency wire representation or shared-clock test.
6. There is no evidence for host termination while blocked in native creation,
   host-crash Job closure, descendant containment, IPC reconnect, or
   post-termination audit. The existing inert-child smoke test launches one
   local `pass` child and is not that evidence.

## Required offline acceptance tests before G1 review

- **Deadline accounting:** one injected QPC domain shared by fake caller/host;
  advance time independently during host capture/bootstrap, parent setup,
  metadata phase, worker phase, termination, and close. Expiry at each boundary
  prevents subsequent stages, uses no renewed timeout, and reports timeout or
  unknown rather than success.
- **Independent host kill:** a fresh local `python -I -S` host receives a
  lazy inert child that waits beyond the deadline. The guardian times out and
  terminates the host; on Windows verify the host process signals, the child
  and a spawned inert grandchild terminate through Job close, and the guardian
  reports no fabricated Job-empty/native-close proof.
- **Native-call stall fake:** block an injected host backend operation; the
  guardian kills the host process by deadline even though the host's Python
  watchdog cannot make progress. This test must be a real host subprocess with
  a controllable local stall, not a same-thread fake.
- **Normal completion:** a sealed inert launcher exits, its lazy child exits,
  the Job becomes empty, controls close, and the value-free result is emitted
  before the same absolute deadline.
- **Unresolved custody/reconnect:** force close/empty observation to remain
  unknown; disconnect the caller while the host stays alive; reconnect using
  the host-instance ID and opaque token; prove strong custody survives and
  reconciliation releases it only after exit plus Job-empty evidence. Drop
  backend/client/result references in the test. Token/path/raw-handle leakage
  and unknown-token behavior are negative-tested.
- **Host crash:** terminate the host with an active lazy child; Windows confirms
  Job close requests child/grandchild termination. A fresh host does not accept
  the dead host's token as positive resolution.
- **Trust and IPC:** wrong host digest, interpreter identity, descriptor,
  protocol version, caller ACL/identity, command digest, or expired QPC request
  is rejected before runtime import, candidate setup, marker, or child start.
- **No integration:** assert no CLI/inventory registration, provider/SDK import,
  private-config/marker access, socket, network call, or wheel/build action.

The existing 28-test fake/Windows smoke suite remains valid evidence for the
current watchdog and backend slices. It does not satisfy the process-boundary,
trust, deadline, or host-failure acceptance items above.
