# AC41–63 independent writer-inventory QA archive

Status: **CANDIDATE_DISCOVERY_ONLY**. This archive records independent static inventory QA only; it does not prove writer closure, runtime reachability, or authorize a route.

- [Independent review](independent-review.md)
- [Machine receipt](independent-qa-receipt.json)
- [Raw QA/source ZIP](ac41-63-writer-inventory-independent-qa.raw.zip)
- [ZIP member index](archive-index.json)
- [Archive verification receipt](archive-receipt.json)
- [Frozen output diff](inventory-output-diff.json)
- [JUnit](pytest-junit.xml)
- [Source SHA manifest](source-manifest.json)
- [SHA-256 list](SHA256SUMS.txt)

The raw ZIP contains the sanitized isolated source snapshot, focused test/JUnit and CLI/Ruff/grammar logs, synthetic private/unclassified probes, and the frozen owner evidence. It excludes pytest/bytecode caches, synthetic fixture directories, and every file under `runtime-ctp-private`. ZIP contents were CRC-tested and each indexed file member was SHA-verified.
