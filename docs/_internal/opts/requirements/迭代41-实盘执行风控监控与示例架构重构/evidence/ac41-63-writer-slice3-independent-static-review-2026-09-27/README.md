# AC41-63 writer slice 3 r2 — independent static review archive

**Verdict:** `PASS_STATIC_AUDIT_SCOPE_ONLY`. This is limited to static audit of 43 of 389 indexed candidate IDs; 346 remain residual. All official dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`. `NO_WRITE / LIVE_NO_GO` remains in force.

The review checked 21 new IDs disjoint from the preceding 22, source hashes/locations, and 38 main-source plus 7 SDK source excerpts. The direct registered-simulation path is a conditional static finding only. No source code, default route, credentials, provider, SDK, network, account, order, or cancel was exercised or changed. This archive does not establish a real write or acceptance closure.

## Frozen inputs and independent QA

- Author ZIP: `author/slice3-r2-author.zip`, SHA-256 `4d90d2e1abda09c44dfeb4845526b7a07b12d617bab9952de60d360832b37000`; 11 members; `testzip()` clean.
- Independent QA ZIP: `qa-package/independent-qa.zip`, SHA-256 `a3a569254040d4a8d195f80762cad55d67d143edd5edd46be68e0ee0ec76f14a`; 8 members; `testzip()` clean.
- Independent receipt: `qa/QA-RECEIPT.md`, SHA-256 `0684063397ffb1cac4dd4a8d91b0bcd6cb2390c97930285ac5a2ad2fa3301442`.
- QA package manifest: `qa-package/QA-PACKAGE-MANIFEST.json`, SHA-256 `dcf0527ecfb17244ba79c07bb74d3517530944b1f94c848f4130c875277155fc`.
- Archive index with all 12 copied artifact hashes and source/copy CRC checks: `ARCHIVE-INDEX.json`, SHA-256 `1c1ae3be4396855033b5f4876896cfeb972cc9d662f939eb6b9a9a2ca5a7a1fe`.

The receipt, machine-readable verification, verification script/log/exit status, and QA package build script/log/exit status are retained under `qa/`. Copies were byte-compared to their source files. The source Store hash differs from the older frozen manifest because the separately reviewed r2 rev2 Store patch is already present in the shared main tree; see the receipt for exact hashes and limits.
