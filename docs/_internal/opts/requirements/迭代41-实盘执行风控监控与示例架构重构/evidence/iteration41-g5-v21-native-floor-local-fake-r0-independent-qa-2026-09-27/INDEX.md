# V21 native ActionRef floor r0 — independent QA archive

**Disposition: SAFE_LOCAL_FAKE / NO_MERGE.** This archive records an isolated, fake-only candidate. It is not external native-floor authority, does not reconcile G5/V21 ledgers, and is not live/F14 acceptance.

## Author candidate

- [Patch](author-candidate/ACTIONREF-NATIVEFLOOR.patch)
- [Frozen candidate manifest](author-candidate/manifest.json)
- [Source manifest](author-candidate/SOURCE-MANIFEST.json)
- [Preimage/target manifest](author-candidate/PREIMAGE-TARGET-MANIFEST.json)
- [LOCAL_FAKE_ONLY boundary](author-candidate/LOCAL_FAKE_ONLY.md)
- [Author validation notes](author-candidate/VALIDATION.md)
- [Author JUnit](author-candidate/artifacts/nativefloor-r0-junit.xml)

## Independent QA

- [Independent report](independent-qa/REPORT.md)
- [Independent JUnit](independent-qa/artifacts/independent-corrected-junit.xml)
- [Guard events](independent-qa/guard-events-suite-corrected.json)
- [Guarded test output](independent-qa/suite-corrected-output.txt)
- [Adversarial history probes](independent-qa/history-probes-output.txt)
- [Ruff validation](independent-qa/ruff-validation.txt)
- [Manifest erratum](MANIFEST-ERRATUM.txt)
- [SHA-256 inventory](SHA256SUMS.txt)

Exact patch replay matched the five target hashes. Independent guarded tests: 271 passed, 2 skipped, no failures/errors. Ruff passed. The counter-ahead-of-visible-allocation case is an allowed burned high-water gap, not an inconsistency; actual counter/history contradictions failed closed. Default trusted floor authority remains unavailable. Caller-level Python monkeypatching remains a local fake-test seam only and is not a trust/security boundary.

The archive intentionally omits the full external source tree. All source, replay and test details remain bound by the patch and manifests.
