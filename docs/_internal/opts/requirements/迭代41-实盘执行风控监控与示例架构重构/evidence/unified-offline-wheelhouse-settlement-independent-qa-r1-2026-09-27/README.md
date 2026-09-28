# Unified offline wheelhouse settlement R1 — independent QA archive

**Disposition: `FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED`.** This archive preserves the frozen wheelhouse candidate and independent offline install audit. No SDK/native module, provider, account, credentials, private configuration, network operation, or default route was used.

- [Independent QA report](independent-qa/QA-REPORT.md)
- [Independent QA receipt](independent-qa/QA-RECEIPT.json)
- [Archive index](ARCHIVE-INDEX.json)
- [SHA-256 listing](SHA256SUMS)
- Original frozen candidate archive: `unified-offline-wheelhouse-settlement-evidence-r1.zip`
- Independent raw QA packet: `independent-qa-r1-packet.zip`

The fresh CPython 3.11.5 venv installed 52 hash-locked local wheels with `--no-index --require-hashes`; all 52 wheel origins, four PEP 610 root hashes, 13,147 installed RECORD rows and `pip check` were independently verified. The R1 CTP wheel is a local probe artifact. Settlement evidence is not consumed by main readiness; this archive does not establish G1–G5 or release acceptance.
