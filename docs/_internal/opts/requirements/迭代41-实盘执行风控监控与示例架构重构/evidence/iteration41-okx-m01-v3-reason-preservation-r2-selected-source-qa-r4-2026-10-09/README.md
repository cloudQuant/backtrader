# OKX M01 V3 R2 selected-source delivery

This packet materializes the complete public source closure used by the fixed M01 V3 route: 19 runtime source rows and the R2 source-fake test. `source-map.json` is the canonical V3 map object (`schema` plus the exact 19 `source_pins`); its SHA-256 is the value Root should bind as the source-map digest. `source-index.json` records every row’s byte count, hash, review provenance, and checkout status. `source.zip` contains the 19 runtime files plus the test.

## Frozen source set

- Canonical map body: 2,876 bytes, SHA-256 `43ea368c7acd2dddd88bac718e5f57cceb59ef27a2d0c6c22d5bcdf2f68d1da8`. The physical `source-map.json` is 2,877 bytes with exactly one terminal LF, as required by the reader. The deployment source-map digest is the physical file SHA-256 `db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3`; `source-index.json` records both digests.
- Source archive: 105,065 bytes, SHA-256 `fb319aa4b066a839dc8681d2ac30897374bece35d90bf29d6c26b28c40b7ee35`.
- Source index: 11,314 bytes. Its 19 runtime rows comprise 5 clean tracked, 4 modified tracked, and 10 untracked files. The R2 test is a separate 20th archive member.
- Working HEAD is `565cb93298a53703c47390a05eb23a1ff4985b09`; the earlier inventory checkpoint was `309fafdd0c43bd4b4d61ac3cc1c71ca6c80ea5f6`. The intervening accepted SimNow C01 commit did not change any of the 19 M01 runtime source bytes.

The 15 unchanged runtime rows inherit the reviewed R1 source candidate (`source.zip` SHA-256 `02f9605429a5e230dfe9f252a08f8d48af311f0b3833891676415bab8551cdde`, source map SHA-256 `de8b619925353364b950b2f8beb97ccb5c7d5862868ff9665d081ba8afb83cdd`). Four runtime rows use R2 direct-review bytes: V3 `issuer.py`, `current_reader.py`, and `entry.py`, plus `cases/M01/run.py`. The R2 review also directly pins the test. The R2 review record is `iteration41-okx-m01-reason-preservation-independent-review-r2-2026-10-09/review.json`, SHA-256 `38caf05f18e8c70997ac7fecc5acac510103b2feffa40976d1ce8166ac213ce7`.

`_certification/models.py` is pinned to the R1-reviewed 6,526-byte file (`f6db3e492fb8681bb156a577515b73e9966142e447f9d857ad4ec8a024389362`). The separate L04 `CaseResult.formal_proof` field/import hunk was removed by its owner before this source set was frozen; that hunk is not included in this map. The current file still differs from HEAD because it contains the inherited R1 model fields. Any later L04 change to shared files needs its own review and a new source-map digest.

The inherited R1 source closure includes `_certification/fixed_owner_routes.py` and the full `_certification/runner.py` because the runner imports that route registry. The tracked `config.py`, `models.py`, and `runner.py` worktree changes are R1-pinned source bytes; R2 adds no hunks to those files. Their existing native-order/route changes are outside the four direct R2 edits and must not be confused with the R2 first-error fix. The 10 untracked V2/V3 M01 implementation dependencies are part of the 19-row closure; a four-source-plus-test delivery that omits them is incomplete.

Clean tracked rows were selected from the exact clean checkout bytes after verifying Git reports them clean and `git hash-object --path=<path> <path>` equals each `HEAD:<path>` blob. This checkout has `core.autocrlf=true` and mixed physical LF/CRLF files, so the packet hashes the bytes read by the route. Root owns adding exact `-text` attributes for these source paths before committing, so future checkouts preserve the byte pins.

## Selected-source QA

The selected snapshot was built from these 19 exact runtime rows and the exact R2 test. The map body reserializes byte-for-byte with the pinned `current_reader._canonical` JSON shape, and the file has exactly the required terminal LF; its 19 keys match the pinned `SOURCE_MAP_RELATIVES`. The deployment digest hashes the complete LF-terminated file. All 20 ZIP members matched `source-index.json` by path, size, and SHA-256.

The isolated snapshot focus passed **4 tests**, with one existing pytest configuration warning (`asyncio_default_fixture_loop_scope` is unknown because plugin autoload is disabled). It exercised the source-pin binding test, both first-error-preservation parameter cases, and the release-failure custody case. The independent R2 review separately ran the complete source-fake file: 13 passed. Neither result is account, provider, native, protected-map, or formal M01 case acceptance.

The exact isolated command and condensed output are in `qa-command.txt`; the structured result and source-map/archive checks are in `source-qa-result.json`.

No private config, credentials, protected deployment map, provider, native API, or Windows API was read or invoked for this packet. No source code was edited while building the packet; this is a public-source snapshot and QA record only.
