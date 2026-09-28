# R9 Windows inert custodian: author evidence (G1 closed)

**Classification:** author-side prototype / negative evidence only. This archive is not independent QA, a service deployment, or G1 acceptance. No production/default-preflight files were changed for this archive.

## Frozen candidate

- Isolated source: `D:\temp\iteration41-g1-r9-prestarted-inert-custodian-20260927`
- Candidate manifest SHA-256: `98a8110a5c99e960d052c18d57c9aaedf3bd43fa61dc3271a8b7235a0280da81`
- Candidate receipt SHA-256: `833939ba976f9ea6474ca9c67e4b33a1cdf91022c6003816c8c00ceb004a0709`
- Final trials SHA-256: `c848ab2f51360399a399a16a441e66821eb3368ee36bdd44c17d2018dbd50dc7`
- Preserved first meaningful failed trial SHA-256: `e2addd9c7f16f6fe3a3c83ded4034b9eb4ff447e4340c0731e9e0914147485f1`
- Raw ZIP: `r9_candidate_raw.zip` (ZIP_STORED); ZIP SHA-256: `2055fb8329a06d80abe8fc52ae2d2fec25674686300defe96192faf3a4e44f3a`
- Per-entry index: `r9_candidate_entries.json`; SHA-256: `1957b0bdc47c26903de96eed6a8c08bb4d25613d56d495de2c3add2198852665`; 19 frozen candidate files are individually hashed. The index is inside the ZIP and is externally bound by the archive receipt.
- Candidate manifest listed 15 payloads; copied payload hashes and all copied source bytes were checked. ZIP CRC and per-entry SHA checks passed.

## Deadline findings

All request trials use D=1200 ms. The final frozen run records:

| Scenario | Deadline tick | Caller return tick | Lateness | Result |
| --- | ---: | ---: | ---: | --- |
| P05: pending 2 MiB broker write | 223810700 | 223810703 | 3 ms | `CALLER_RETURN_LATE` |
| Popen-before wrapper stall | 223814403 | 223814406 | 3 ms | `CALLER_RETURN_LATE` |
| Popen-after wrapper stall | 223816028 | 223816031 | 3 ms | `CALLER_RETURN_LATE` |

P05 fails the hard caller-return deadline even though the caller stack only publishes a preexisting shared-memory ticket and polls; it does not perform pipe writes or request-time process/pipe setup. The broker still owned the pending OVERLAPPED/event/buffer after the late response, then canceled and consumed completion (`ERROR_OPERATION_ABORTED` 995) and exited with its Job empty. The caller-death trial also shows the broker surviving caller Job termination and completing cancellation. This is partial custody evidence; later cleanup does not repair the caller deadline.

## Exact scope and limits

- **P02/P03:** deterministic Python Popen wrapper blocks immediately before child creation and after a real inert child exists but before Popen returns. The prestarted worker Job terminated and became empty; post-create active count was two. These are wrapper probes, not hangs inside `CreateProcessW`.
- **P07:** real pending overlapped pipe write and cancellation; the 100 ms delay is a user-mode hold after the event before `GetOverlappedResult`, not delayed kernel completion.
- **P14:** absent. No blocked `TerminateJobObject`, `QueryInformationJobObject`, `CancelIoEx`, or `CloseHandle` was injected.
- **Outer Job:** active process count was 5; after termination it was 0; all five recorded process handles signaled. This does not prove a dedicated service reaper survives or returns the caller by D when that reaper wedges.
- No SCM service was installed. Supervisor launch and synchronous prewarm setup precede request D, so this does not prove a whole-command/startup deadline. No CTP/native/provider, credentials, private configuration, network route, or default preflight was used.
- R8 samples remain distinct: frozen admission-sync trial D=1200 ms / decision=1218 ms / caller API did not return; the older replay observation was 1234 ms.

**Disposition: G1 CLOSED.**
