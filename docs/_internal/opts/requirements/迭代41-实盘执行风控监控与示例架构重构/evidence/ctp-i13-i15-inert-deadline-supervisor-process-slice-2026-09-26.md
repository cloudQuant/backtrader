# I13/I15 inert-only out-of-process deadline supervisor slice

Date: 2026-09-26

## Decision

This slice demonstrates a separate Windows process enforcing a deadline for a
fixed inert sleep guardian after its owner process exits. **G1 remains
NOT_PASSED.** The code is unregistered, accepts no command or candidate input,
and does not open the ordinary preflight route.

## Process topology

`scripts/ctp_i13_i15_inert_deadline_supervisor.py` starts only the fixed
`ctp_i13_i15_windows_guardian.py --inert-only` command. The supervisor owns an
outer Windows Job; the guardian owns its existing inner Job for the inert
sleep child. Both Job layers use the existing `PROC_THREAD_ATTRIBUTE_JOB_LIST`
and kill-on-close implementation. The supervisor passes the same absolute
`time.monotonic()` deadline to `run_outer_watchdog()` and does not replace it
with a fresh per-stage timeout.

At deadline, the outer watchdog requests termination of the supervisor-owned
Job. The supervisor receipt always says `unknown`; it preserves the inner
watchdog state and observations, and never turns forced termination into a
successful operation result. Where the process/Job observations finish within
the deadline, the receipt can record them; otherwise it keeps their values
unknown. The receipt is created with the existing exclusive, value-free
writer.

The public CLI requires `--inert-only`, bounds the sleep duration, takes one
absolute stop deadline and one command deadline, and constructs the worker
command internally. The arbitrary `FixedOuterCommand` parameter exists only
on an underscore-prefixed internal seam used by the process test; the CLI does
not accept it.

## Process evidence

`test_supervisor_kills_blocked_inert_service_after_owner_death` starts an
owner process, which starts the supervisor and then remains alive. The blocked
service starts a second fixed `time.sleep()` child in its inner Job and then
stalls. The test terminates the owner by PID while the service and child are
still alive. The independent supervisor remains alive until the original
absolute deadline, requests termination of its outer Job, writes an UNKNOWN
receipt, and exits. Windows process handles then confirm the owner, supervisor,
blocked service, and inert child have all signaled. The receipt records the
deadline termination request, successful Job termination call, and observed
empty Job; state remains `unknown`.

No provider, SDK, private configuration, marker, trading account, socket, or
network operation is used. The actual supervisor CLI has no route to arbitrary
commands, and no runtime inventory or ordinary CLI registration changed.

## Validation

On the local Windows host, Python 3.11.5 / pytest 8.2.2 from the compatible
temporary venv, with pytest plugin autoload disabled to avoid an installed
`pytest-asyncio` collection incompatibility:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --color=no \
  tests/unit/scripts/test_ctp_i13_i15_parent_launcher.py \
  tests/unit/scripts/test_ctp_i13_i15_sealed_import.py \
  tests/unit/scripts/test_ctp_i13_i15_outer_watchdog.py \
  tests/unit/scripts/test_ctp_i13_i15_windows_guardian.py \
  tests/unit/scripts/test_ctp_i13_i15_windows_guardian_service.py \
  tests/unit/scripts/test_ctp_i13_i15_windows_job_backend.py \
  tests/unit/scripts/test_ctp_i13_i15_inert_deadline_supervisor.py
```

Result: **84 passed twice**, each run with one pytest configuration warning
for the existing `asyncio_default_fixture_loop_scope` option (37.06 and 37.87
seconds). The older blocked-backend process case also passed in a separate
focused run (1 passed, 5 deselected). The owner-death fixture uses the actual
PID reported by the owner script because the Windows Python launcher PID may
differ from the Python process PID. Ruff, Black (`--target-version py311
--line-length 100`), and `py_compile` passed for the new supervisor and its
test. `git diff --no-index --check` produced no whitespace diagnostics for
either new file (Git reported the expected LF-to-CRLF working-copy notice).

## Remaining blockers

- This process topology is not an externally trusted installation. There is
  no release signature, protected supervisor source root, explicit pipe or
  receipt ACL, or authenticated control protocol for a deployed host.
- The test owner is an ordinary process, not an owner in a kill-on-close Job.
  It proves survival of direct owner termination in this topology; it does not
  prove that a deployed parent Job, service manager, logoff, or machine shutdown
  will preserve the supervisor.
- The supervisor itself can block inside process creation, Job termination,
  Job accounting, or receipt I/O. There is no independent higher-level
  watchdog for that process. Kernel hangs, machine suspension, and OS failure
  remain outside the result.
- The Windows test exercises `time.monotonic()` across these Python processes,
  but the deployment has no QPC tick/frequency protocol or independently pinned
  clock-domain contract.
- The deadline triggers the termination request; writing the UNKNOWN receipt
  and observing process exit may occur after that instant. This is not evidence
  that the entire ordinary preflight command, cleanup, and reporting complete
  inside one hard wall-clock deadline.
- The service/launcher source-trust, HMAC/PID/ACL/replay, candidate setup,
  native startup/close, and ordinary preflight integration gaps remain open.

This is evidence for an inert process-supervision slice only. It does not make
ordinary preflight safe and does not change G1 acceptance.
