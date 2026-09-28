# G5/V21 offline ActionRef cutover validator r1

**Disposition: `LOCAL_TYPED_CONTRACT_ONLY / NO_AUTHORITY / NOT_A_MIGRATION_TOOL / NO_WRITE / LIVE_NO_GO`.** This archive contains a pure in-memory consistency validator for explicitly supplied legacy-G5 and V21 snapshot projections. It does not read a database or runtime state, allocate or rewrite references, authenticate snapshot sources, authorize an account, or enable a trading route.

## Contents

- [Corrected r1 manifest](candidate/candidate-manifest-r1-corrected.json) — SHA-256 `39f4922be5ed43bc021b0813ae84ef0e99fa2b8c5c2e0352b6a3a595502bffd9`.
- [Patch](candidate/offline-actionref-cutover-consistency-r1.patch) and four exact target payloads: [validator](candidate/src/offline_cutover_validator.py), [tests](candidate/tests/test_offline_cutover_validator.py), [candidate contract](candidate/docs/CANDIDATE.md), and [limitations](candidate/docs/LIMITATIONS.md).
- [Author JUnit](candidate/author-r1-junit.xml), independent [QA report](independent-qa/qa-report.md), [QA receipt](independent-qa/qa-receipt.json), and supporting replay/JUnit records.
- [Provenance correction addendum](provenance/PROVENANCE-CORRECTION.md) and independent corrected-pointer [receipt](provenance/correction-receipt.json).

## Verification

The independent QA replay reported 28/28 tests and the selected adversarial set reported 5/5. The corrected-manifest recheck confirmed r0 HEAD `103facd51aebf2e47cccb2d22640dec091d23030`; the previous `213574e` pointer was absent. Only the manifest provenance fields changed, and no tests or formatter were rerun for that metadata-only correction. Exact hashes and archive-relative file links are indexed in [ARTIFACT-MANIFEST.json](ARTIFACT-MANIFEST.json).

The matching caller-supplied snapshot boundary label is unauthenticated. The source snapshots may be incomplete or non-simultaneous; legacy state and V21 correlations require separately validated joins; no authenticated native high-water floor, old-writer fence, external account-wide epoch, deployed historical exporter, or real account migration evidence is present. This artifact cannot be wired into a runtime, used for migration, or treated as account authority.

No shared `AGENTS.md`, inventory, acceptance matrix, shared evidence index/README, or main-tree code was changed by this archive operation.