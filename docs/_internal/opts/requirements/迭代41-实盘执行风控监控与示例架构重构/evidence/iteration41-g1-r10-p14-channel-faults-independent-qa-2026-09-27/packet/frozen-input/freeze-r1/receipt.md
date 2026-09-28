# G1 R10-r1 P14 and channel-close inert Windows probe

**Status: feasibility diagnostic only; G1 remains CLOSED.** This is a separate temporary copy and does not edit the frozen R10-r1 candidate or main repository code.

## Frozen inputs and reproducibility

- Upstream R10-r1 candidate: `D:\temp\iteration41-g1-r10-r1-deadline-shutdown-20260927`; candidate manifest SHA-256 `88ec781edc1e6c1155ff993cd4fbb7260791386a133080a674aab9330ebf341e`.
- Copied `r10_custodian.cpp` SHA-256 `dfbe509e030906eebfdd4345cafda453f9ebfee817bfd32df32e10d607a57186` (unchanged). Copied source manifest and both original harness files are under `source/`.
- Independent R10-r1 QA packet used for provenance: manifest SHA-256 `460fe775cb79d0801d1e83e9863d497c56cbb0cfd54e4298c709481b3dfb6de4`; archive SHA-256 `f064f7bd214e03b31be896a701baba46a61ffa72be2ee8000f70600dc726f752`.
- Probe command: `python .\p14_channel_faults_reprobe.py` on Windows; exit code 0. Raw stdout, JSON, exit code, wrapper marker files, script, and copied upstream inputs are included in this freeze.

## Minimum reproducible results

The probe called actual local `kernel32` APIs on invalid/restricted handles and disposable local Jobs/pipes:

- `TerminateJobObject(NULL)` and an invalid non-NULL handle returned FALSE / `ERROR_INVALID_HANDLE` (6). A restricted Job handle with only `JOB_OBJECT_TERMINATE` returned FALSE / `ERROR_ACCESS_DENIED` (5) from `QueryInformationJobObject`; an invalid non-NULL query handle returned FALSE / error 6.
- A valid disposable Job query returned active count 1 with one inert Python sleeper. Actual `TerminateJobObject` returned TRUE; `WaitForSingleObject` returned `WAIT_OBJECT_0`; the subsequent Job query returned active count 0. These are local return observations, not latency guarantees.
- Closing a valid Job control handle or anonymous-pipe endpoint returned TRUE once; an immediate second `CloseHandle` returned FALSE / error 6. This is a real Win32 failure return on a stale handle, not an injected return value.
- Two wrapper-stall negatives put an inert child into a separate outer test Job and held it in an explicit 100 ms user-mode sleep before the target call. For the close case, the child verified its inherited pipe endpoint was valid before sleeping. The marker confirms neither target reached `API_REACHED`; the target `TerminateJobObject`/`CloseHandle` was never called. The outer test Job's actual termination call returned TRUE, its query went from active 2 to 0, and the child wait returned `WAIT_OBJECT_0`. This tests wrapper delay plus external test-Job cleanup only.
- `QueryInformationJobObject(NULL)` succeeded by querying the caller's current Job (active 2 / total 3 in this run); NULL is therefore not treated as an invalid-handle case. Invalid non-NULL handles were used for the failure probe.

## Feasibility and limits

This reproduces real Win32 failure return codes for invalid/restricted handles, a valid nonzero-to-zero Job census around successful termination, and stale-handle close errors. It does **not** inject failures into R10's own supervisor call sites. The 100 ms delays occur before the API in a Python wrapper; they are not blocked kernel calls. No safe mechanism was available to force a real `TerminateJobObject`, Job query, or `CloseHandle` kernel call to hang. The outer Job used by this diagnostic is itself the final test custodian; its own failure or hang is not covered.

No channel API was made to hang inside the kernel. The pipe test proves a real duplicate-close error and a separately labelled pre-call wrapper delay; it does not establish the R10 worker's overlapped-I/O shutdown behavior under a kernel close failure. P14 behavior in the candidate supervisor, P14 API hangs, startup Job setup, channel-close failure propagation, P14 `TerminateJobObject`/query/close failure recovery, P14 outer-custodian failure, SCM, and whole-command deadline remain unproved.

No CTP/native SDK/provider, network, credentials, private config, account, or default route was accessed. Any observation after request deadline D remains incompatible with G1 hard-D acceptance. **G1 and ordinary preflight remain CLOSED.**
