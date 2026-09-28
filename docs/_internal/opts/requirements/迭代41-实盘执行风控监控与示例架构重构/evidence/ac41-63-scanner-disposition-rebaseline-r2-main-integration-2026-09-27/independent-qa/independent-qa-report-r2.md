# Independent QA — AC41-63 writer-inventory rebaseline r2

**Verdict: `SAFE_TO_APPLY_SCANNER_COVERAGE_ONLY`.** This validates scanner/disposition coverage integrity only. All 460 active rows remain `REVIEW_REQUIRED / NOT_AVAILABLE`; this is not writer closure, live-route approval, or provider acceptance.

## Frozen package identity

- Package: `D:\temp\iteration41-writer-inventory-disposition-rebaseline-460-r2-20260927`
- Patch: `writer-inventory-dispositions-460-r2.patch`, SHA-256 `D5DE326F61EDE3D4776392C158587B89A7098B38274C8B6C0E7AB7B0BB0D319D`
- Package manifest: `package-manifest.json`, SHA-256 `6F5A6AF33456AA0DA0A3A2A0F65C42AB5EFCF40EA371A601932D26C5591C7BBA`
- `SHA256SUMS.txt`: SHA-256 `E4DC489D4DF037CDCA1D892DC61EA44CD9381A53C41952B1A588CEAB038B93A4`; all 23 newline-delimited records and all manifest payload hashes matched.
- Rebaseline patch manifest: `rebaseline-patch-manifest.json`, SHA-256 `2A3F0D6C0EE4197298277CAF9E72C82113C3FCD88E514B7FF3B2BFF9BD78ACC2`.

## Exact-base replay and current scan

The patch passed `git -c core.autocrlf=false apply --whitespace=error --check` against the unchanged main checkout. Main preimages matched the manifest:

- verifier `633AD4749EAEBF54E8A6BE257A6DBBE1900326992122EEDD5C161B3485EE42E1`
- verifier tests `E1E9A96A040AC510B4BB48A13195651D71199D9C4B7071083EB617B14F3B3F49`
- inventory JSON `FACBBC93067D77A317E3A0ABDE5EF89BC77BD53E4A4EB18722B51124E3E20780`
- disposition JSON `E6ECE21E16AF6C6A6220431DD0C2669D81206A136B500DFD5214CA766818E841` (manifest value: `E6ECE21E16AF6C6A6220431DD0C2669D81206A136B500DFD5214CA766818E841`)

An independent scratch replay at `D:\temp\ac41-63-writer-rebaseline-independent-qa-20260927\full-current-source-replay-r2` produced all four target hashes exactly:

- verifier `8508BF4E394BFB77EA369710B3A37AA1F6FA987DF4484BFEA413CA4ACC97CA53`
- verifier tests `4CE31FE03CF0671FD573157E27DBF3E8D35266B6FBACE96A830CF8F0F8A73824`
- inventory JSON `D81C98A73E32B8D2CFB39034FCC1DCEAD7EA5434CDF38C8ADC30AB6B47A60710`
- disposition JSON `B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426`

A fresh read-only collector run against current main produced 363 writer + 97 dynamic candidates across 355 files, with 0 parse errors and 0 unclassified paths. Its semantic counts, scanned paths, writer records, dynamic records, scope, historical scopes and coverage fields exactly matched the frozen candidate inventory (JSON byte hashes differ because generation metadata changes).

## Verification

In the isolated exact-replay tree:

- `python -m pytest -p no:asyncio tests/unit/scripts/test_verify_iteration41_writer_dispositions.py -q --tb=short` — **6 passed**.
- Verifier CLI — **PASS**, 460 discovered/460 dispositions, six historical tombstones, 460 review-required records.
- `py_compile` — pass.
- Ruff with repository `pyproject.toml` — pass.
- Additional actual-460-row probes: valid control passes; omitted/null preservation, simultaneous removal of preservation/history/lineage, missing lineage, null arrays and object members in each baseline/previous/tombstone/G6 ID array all return `REJECTED` with reason codes and no exceptions. Raw script/output: `r2_preservation_probe.py`, `r2-preservation-probes.json`.

The r1 defect is fixed: preservation data is mandatory for expanded/tombstone inventories, and typed ID lists are checked before set operations. The prior fail-open/runtype-error cases no longer reproduce.

## Formatting/tool limitation

The installed Black reports version `0.0`; repository-configured `black --check` cannot run because this Black rejects configured target `py312`. Fallback Black with line length 100 and target `py311` reports formatting in both base and candidate files. Comparing baseline and candidate Black diffs shows those hunks are pre-existing unchanged formatting; none of the r2-added/modified regions are flagged. Ruff and compilation pass. This is not a claim that the repository-wide Black check is clean.

No main files were modified. Main source and inventory files were accessed read-only for hashing and collection; no provider, credentials, network, SDK, or live route was accessed. The patch is suitable only for scanner coverage/disposition bookkeeping.

