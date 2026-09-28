# G1 R10-r1 P14/channel-close independent Windows probe

**Disposition: FEASIBILITY_DIAGNOSTIC_ONLY; G1 remains CLOSED.** This probe exercised local Win32 APIs with disposable inert Python children. It does not establish a kernel/API hang, a P14 supervisor recovery path, a hard whole-command deadline, or G1 acceptance.

## Frozen input integrity

- Frozen directory: `D:\temp\iteration41-g1-r10-p14-channel-faults-20260927\freeze-r1`.
- `manifest.json` SHA-256: `8eb904c372046b233c474dc5c9825ebbe82c95cfb3ece4277aa6eaffdc4994c5`.
- `evidence.zip` SHA-256: `880fb7b05152de0e9099b0d236b2f602178470d80bcf409d79e8ecb14f57fddd`.
- The manifest has 12 payload entries, all size/hash checks matched. The ZIP has 14 entries, `testzip()` returned `None`, and every ZIP member matched the frozen directory copy byte-for-byte. Full per-entry results are in `independent-run/frozen-zip-verification.json`.
- The probe source hash in both frozen and QA copies is `00fa8322a2f2804e008c6799d9923a74aeb19976f0c61f30cf7fdcad4acbd577`; copied `r10_custodian.cpp` hash is `dfbe509e030906eebfdd4345cafda453f9ebfee817bfd32df32e10d607a57186`. The C++ source was retained for provenance, not compiled or executed.

## Independent run

From a byte-isolated copy, on Windows/CPython `C:\anaconda3\python.exe`, the command `C:\anaconda3\python.exe .\p14_channel_faults_reprobe.py` exited 0. Raw stdout, stderr, exit code, JSON, wrapper markers, interpreter-safe Job-assignment preflight, and source copies are under `independent-run/`. Before the main probe, a separate safety preflight created a fresh Job, assigned one inert sleeping child, terminated it through that Job, and waited for exit; assignment returned true and the child exited with the test Job status. No SDK/provider/network code was involved.

Observed API results in the independent JSON:

- `TerminateJobObject(NULL)` and invalid non-null handle: `FALSE`, Win32 error 6 (`ERROR_INVALID_HANDLE`).
- `QueryInformationJobObject` on invalid non-null handle: `FALSE`, error 6. A duplicated terminate-only handle was valid but query returned `FALSE`, error 5 (`ERROR_ACCESS_DENIED`).
- A valid disposable Job moved from `ActiveProcesses=1` to `0`: assignment succeeded, `TerminateJobObject` returned `TRUE`, wait returned `WAIT_OBJECT_0` (`0`), and the final Job query returned true with active count zero.
- Closing a valid Job handle and pipe handle succeeded once; repeat closes returned `FALSE`, error 6. These are actual local API return values.

## Wrapper-delay distinction

The two wrapper negatives each waited about 100 ms in user mode before the target call. Independent elapsed-to-outer-termination measurements were 104.04 ms for the terminate wrapper and 104.93 ms for channel close. In both cases the marker contains only `WRAPPER_ENTERED`; both `api_reached` and `api_returned` are false. The channel child verified its inherited pipe handle as valid before sleep. The outer test Job returned true from termination, its active count moved from 2 to 0, and the child wait returned `WAIT_OBJECT_0`.

Therefore these cases demonstrate a pre-API wrapper delay and cleanup by a separate outer test Job. They do **not** demonstrate that `TerminateJobObject` or `CloseHandle` hung in the kernel, nor that the production custodian can recover if its own API or outer Job blocks. Invalid/restricted handle failures and ordinary duplicate-close errors likewise do not inject failures into R10's supervisor call sites.

The first preflight invocation did not start: PowerShell command resolution failed before launching an interpreter. The draft was replaced before execution with an inert Python-sleep preflight; no Win32 probe or network action occurred on that failed invocation.

No CTP/native SDK, provider, credential, private config, account, network, or default route was accessed. **G1 and ordinary preflight remain CLOSED.**

## Reproduction command

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\anaconda3\python.exe .\p14_channel_faults_reprobe.py
```

Run from the isolated `independent-run` directory only; the script writes JSON and marker files beside itself.