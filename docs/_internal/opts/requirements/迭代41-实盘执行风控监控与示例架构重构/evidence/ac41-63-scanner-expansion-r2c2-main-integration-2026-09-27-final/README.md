# AC41-63 scanner expansion r2c2 — local main integration evidence

Date: 2026-09-27  
Disposition: **SCANNER_COVERAGE_LOCAL_ACCEPTED / NO_WRITE / LIVE_NO_GO**

This archive records the scanner/checklist coverage-only r2c2 change and its local main-tree integration regression checks. It does not establish writer closure, external-provider behavior, SDK/native isolation, CTP write acceptance, or live authorization. No production route or default write route is accepted by this evidence.

## Frozen author and independent QA

- Final author patch: `author/candidate-r2c2.patch`, SHA-256 `0222705fd2898c3cf2eded9f8bb7591d0a4a4ad6ace4577ed0450a1bc8788bd5`.
- Final author source manifest: `author/final-source-hashes.json`, SHA-256 `58dd6bc0301696ab41d8ce2663e1e8361707b95857e7ad0ae59fe1045f5345fd`.
- Independent QA report: `qa/r2c2-independent-qa-report.md`, SHA-256 `890bea15b2f8c43e18de42b2daaf158872eba3f284d91174a7f6d0a47de1b2ef`; disposition is scanner/checklist integration only.
- Historical r1 explicit `NEEDS_REVISION` report and checksums are retained under `history/`. The r2b preservation/review receipt and exact logs are also retained as historical evidence; r2b is not represented as final acceptance.

## Main integration results

Root applied the exact r2c2 patch to the four reviewed targets; their current hashes matched the independent QA target hashes before archival and the exact target snapshots are under `main/targets/`.

- Main three-file script focus: **14 passed, 0 failed, 1 existing pytest configuration warning** (`main/main-script-tests.junit.xml`).
- Verifier CLI: **445/445 PASS**; raw output is `main/main-verifier.log`.
- Ruff, py_compile, JSON parse and diffcheck: each exit code **0**; raw logs are preserved under `main/` (the zero-byte logs reflect clean commands).
- This main-tree pytest run was ordinary local pytest and is regression evidence only. It is not a network/SDK/native guard proof.

The enlarged inventory has 445 disposition rows. The 43 previously reviewed candidates remain 43; 402 additional IDs remain unreviewed. The official disposition data still marks all 445 as `REVIEW_REQUIRED / NOT_AVAILABLE`. Inventory completeness is static coverage only and does not establish that a writer is reachable or closed.

## Scope and safety limits

- **NO_WRITE / LIVE_NO_GO.** No production/default route changes or authorization are implied.
- The static scanner and verifier are coverage tools; they do not execute writer candidates or prove runtime reachability.
- The local integration run is not guarded SDK/native zero-I/O evidence.
- The author/QA patch and tests are frozen records. This archive copies exact selected payloads and four target snapshots; it deliberately excludes repository overlays, private runtime state/configuration, and unrelated temporary outputs.

## Reproduction references

See `author/replay.md`, `author/checks.md`, `qa/r2c2-independent-qa-report.md`, and the preserved raw logs/JUnit. The exact applied patch is included. `COPY-RECEIPT.json` records source and copied byte counts and SHA-256 values; `ARCHIVE-INDEX.json` and `SHA256SUMS.txt` bind the archive payload. `SCANNER-R2C2-EVIDENCE.zip` is CRC-checked.
