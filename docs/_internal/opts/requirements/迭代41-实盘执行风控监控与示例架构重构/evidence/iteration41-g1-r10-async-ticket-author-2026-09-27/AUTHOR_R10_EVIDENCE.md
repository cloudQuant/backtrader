# R10 Windows inert asynchronous-ticket evidence (author archive)

**Disposition: AUTHOR EVIDENCE ONLY · G1 CLOSED · ordinary CTP preflight CLOSED.** This archive does not authorize or integrate a production route.

## Frozen identity and archive contents

- Candidate: `R10 Windows inert one-shot asynchronous ticket API + prestarted broker/reaper`.
- Source: `D:\temp\iteration41-g1-r10-async-ticket-inert-20260927`.
- Candidate manifest SHA-256: `da1252e1e25c20530a9cce358c35a1a90f0729dc7f60da85fe2600dd8790f6c3`.
- Candidate receipt SHA-256: `deb34cbe0584710fa41f6623f0febcec0a2a2a71c5ff15e0c54f2fbf39c877c7`.
- Final trials SHA-256: `ba4ab18e585ff66a3af956b17fc84426ec055d4f5f6ae4916ed40fe2651894d5`.
- First-run trials SHA-256: `32bca66edba15ae73a7cf8777ecafcaabcd346df4326e69c39c49a44ae781040`.
- Frozen R10 C++ source SHA-256: `4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3`.
- Raw archive: `r10_candidate_raw.zip`; its overall SHA-256 is recorded in `ARCHIVE_RECEIPT.json` and `SHA256SUMS.txt`.
- `ARCHIVE_INDEX.json` records the per-file hashes for each ZIP member. The ZIP contains the full 23-file frozen manifest payload, the candidate manifest/receipt and their original sidecars, this author page, and the index. ZIP CRCs and member hashes were checked after creation.

## What was observed

The final frozen manifest reports 9/9 candidate assertions passing and no failed checks. Those assertions cover the inert single-slot mailbox, pre-READY/BUSY/POISONED responses, late CAS unable to upgrade UNKNOWN, broker survival after caller death with pending overlapped I/O, Python `Popen` wrapper stalls before/after child creation, and an outer Job tree termination probe. This is prototype evidence, not acceptance.

In final P05, request budget was 1200 ms and D tick was `225406450`. Submit returned ticket `170630686140425` in an observed `0.1 µs`; the ticket became UNKNOWN at tick `225406453`, observed **D+3 ms**. Pending overlapped I/O was still owned at UNKNOWN; cancellation later completed with error 995. The subsequent inert late-success CAS saw state 3 (UNKNOWN), and final state remained 3. Caller-death trial likewise killed the caller while I/O was pending; the separate broker survived, observed caller death, and retained ownership through completion.

**The 0.1 µs figure measures only the submit/mailbox-publication operation. It is not an end-to-end command latency or a hard deadline result. UNKNOWN at D+3 ms is one measured observation, not a Windows scheduling guarantee.** The broker must be scheduled to perform that transition.

The compiler input and outputs are preserved: `r10_build.bat`, `r10_custodian.cpp`, `r10_custodian.obj`, `r10_custodian.exe`, and `r10_build.log`, with SHA-256 values in the archive index. The recorded MSVC command is `cl /nologo /std:c++17 /EHsc /O2 /W4 /Fe:r10_custodian.exe r10_custodian.cpp`; the final trial record reports compiler exit code 0. The build log contains the compiler's short source-name output; the binary/object are included unchanged.

## First harness failure retained

The first full run is preserved in `r10_trials_initial.json`, together with `first_run_failure/` source, runner, helper, object, executable, batch file, and build log. Its sole failed assertion was a harness key mismatch: the initial runner looked up `submit_result`, while the emitted trial field was `caller_submit_result`. The recorded result already contained submit result 0 and the later final rerun corrected the assertion. The initial failure remains in this archive rather than being overwritten or dropped.

## Limits that keep G1 closed

- P02/P03 are Python `Popen` wrapper stalls around child creation; they are **not** injected hangs inside the true `CreateProcessW` syscall.
- P07 is a user-mode 100 ms completion-consume hold after the event, not a delayed kernel completion test.
- P14 (blocking/failing termination, Job query, cancellation, or handle close) was not tested; a higher custodian for a wedged broker/reaper is unproven.
- Launcher and synchronous prewarm/setup happen before request D. There is no SCM service and no whole-command/startup deadline proof.
- The asynchronous submit path uses a preallocated atomic slot and read-only poll in this prototype; it does not establish OS-level hard real-time return or scheduling guarantees.
- No CTP/native/provider integration, credentials, protected/private config, network, or default-route/preflight change was used.

**Conclusion: retain as local inert author evidence only. G1 and ordinary preflight remain closed.**
