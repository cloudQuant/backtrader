# Independent QA packet — G5/V21 cross-package fake contract r0

**Result: PASS for LOCAL_FAKE_ONLY cross-contract checks; NO_AUTHORITY / NO_WRITE / LIVE_NO_GO / NO_MERGE.**

- [Full QA report](REPORT.md)
- Frozen inputs:
  - [Patch](packet/G5-V21-CURRENT-CONTRACT.patch)
  - [Candidate manifest.json](packet/candidate-manifest.json)
  - [Source manifest](packet/SOURCE-MANIFEST.json)
  - [Preimage/target manifest](packet/PREIMAGE-TARGET-MANIFEST.json)
  - [G5/V21 interface note](packet/CURRENT-G5-V21-INTERFACE.md)
  - [Limitations](packet/LIMITATIONS.md)
- [Independent full JUnit](artifacts/independent-full-junit.xml) — 275 passed, 2 skipped
- [Independent focused JUnit](artifacts/independent-focused-junit.xml) — 4 passed
- [Guard events](artifacts/guard-events-full.json)
- [Replay validation](artifacts/replay-validation.txt)
- [Source identity comparison](artifacts/source-identity.txt)
- [Ruff validation](artifacts/ruff-validation.txt)
- [SHA-256 inventory](SHA256SUMS.txt)

Patch SHA-256: AC5F984B6B49EC5E6EB5C99DD31F7E0B8D0A3548B68B8263D629AD71FCDC2B3A.
The 404EC9E4… hash is for PREIMAGE-TARGET-MANIFEST.json; the candidate manifest.json is 15C37A6C….

