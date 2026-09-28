# G1 R9/R10 independent evidence index — 2026-09-27

Scope: inert local Windows helpers only. No SDK/provider, credentials, network, CTP route, or production execution. **G1 remains CLOSED.**

## R9 native-boundary supplement

- Raw archive: [`iteration41-g1-r9-native-boundary-supplement-2026-09-27.raw.zip`](iteration41-g1-r9-native-boundary-supplement-independent-qa-2026-09-27/iteration41-g1-r9-native-boundary-supplement-2026-09-27.raw.zip)
- SHA-256: `1749958a94b19a641745480b8f1b3ea5674b5150260b47707337ae2ea4d141c3`; 59 ZIP members; ZIP integrity passed; all 56 manifest payloads rehashed.
- Readout: [`README.md`](iteration41-g1-r9-native-boundary-supplement-independent-qa-2026-09-27/README.md)
- Prior R9 QA provenance correction: [`r9-prior-qa-provenance-erratum.md`](iteration41-g1-r9-native-boundary-supplement-independent-qa-2026-09-27/r9-prior-qa-provenance-erratum.md). Earlier writable QA extraction had 9/19 differing payload files; old originals are untouched.
- Author R9 evidence is [`iteration41-g1-r9-windows-inert-custodian-author-2026-09-27`](iteration41-g1-r9-windows-inert-custodian-author-2026-09-27).

## R10 asynchronous ticket independent QA

- Independent report: [`independent-qa-report.md`](iteration41-g1-r10-async-ticket-independent-qa-2026-09-27/independent-qa-report.md)
- Raw archive: [`iteration41-g1-r10-independent-qa-2026-09-27.raw.zip`](iteration41-g1-r10-async-ticket-independent-qa-2026-09-27/iteration41-g1-r10-independent-qa-2026-09-27.raw.zip)
- SHA-256: `1e980039f85f95b4f778fe4b568f95eb90a984f4d36582e89e2f4f8393164d24`; 77 ZIP members; ZIP integrity, embedded bundle index/checksums, and 23 author payload hashes verified. Frozen-copy replay rebuilt and passed 9/9 checks.
- Late-intake negative: a separate QA-only source derivative called the otherwise unchanged `SubmitTicket` after D. It returned accepted (`0`) at D+65 ms, then became `UNKNOWN` at D+81 ms. The derivative, exact patch, executable, result and logs are preserved in the archive. This is a reproduced local prototype boundary flaw; author source and route are unchanged.
- Other limits: P02/P03 remain Popen wrapper stalls, P14 and SCM/startup D are untested, broker writer join is `INFINITE`, whole-command D is unproved. R10 does not establish G1 or G4 acceptance.
- Author R10 evidence is [`iteration41-g1-r10-async-ticket-author-2026-09-27`](iteration41-g1-r10-async-ticket-author-2026-09-27).

Machine-readable hashes and absolute paths: [`index JSON`](iteration41-g1-r9-r10-independent-evidence-index-2026-09-27.json).
