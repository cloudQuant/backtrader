# AC41-63 writer inventory disposition rebaseline R2 — main integration evidence

**Disposition: `SCANNER_COVERAGE_LOCAL_ACCEPTED / NO_WRITE / LIVE_NO_GO`.** This evidence is limited to static candidate-inventory and disposition-checklist integrity. It does not establish writer closure, route admission, provider/account trust, SDK/native behavior, or permission to write.

The R2 patch is integrated in main. The exact four changed-file SHA-256 values are recorded in `main-target-hashes.json` and match the frozen patch manifest. The author packet and independent QA report are preserved under `author-package/` and `independent-qa/`; current-main CLI and focused-test outputs are under `main-verification/`.

The current-tree verifier returned `PASS`: 460 discovered candidates / 460 checklist entries, six historical tombstones, all 460 active entries `REVIEW_REQUIRED / NOT_AVAILABLE`, and `reason_codes: []`. The result boundary is `STATIC_DISPOSITION_INTEGRITY_ONLY_NOT_LIVE_ADMISSION`; the CLI field named `live_route_count` is only a candidate row count and grants no route. The inventory comprises 363 writer candidates and 97 dynamic-execution candidates across 355 scanned files, with zero parse errors and zero unclassified paths.

The current-main focused verifier suite passed 6 tests (one existing pytest configuration warning). Ruff, `py_compile`, and `git diff --check` passed. Independent QA verdict: `SAFE_TO_APPLY_SCANNER_COVERAGE_ONLY`. The earlier R1 preservation/history validation defect is retained in the author packet chronology; R2 requires preservation/history/lineage data and rejects malformed ID lists.

No provider, SDK/native module, credentials, private configuration, network, or live route was accessed. All route/write statuses remain `NO_WRITE / LIVE_NO_GO`; all 460 candidate dispositions remain review-required.
