# Iteration 41 combined isolated patch replay

**Disposition: `COMBINED_MAIN_MERGE_REJECTED / NO_WRITE`.** This is test/evidence from an isolated exact-source candidate only. No production Store source, default route, private configuration, real SDK, account, or network was used. During the isolated run, formal 013_3 r2 was present only in the candidate. After G1 formal QA reported `SAFE_TO_APPLY_LOCAL_REPLAY_ONLY`, the root coordinator separately applied that replay-only patch to the main working tree; see [main-tree chronology](MAIN-TREE-CHRONOLOGY.md).

## Result

Patches 1–4 replayed on a selective 3,905-file exact-source copy. The candidate broad Store/Runtime JUnit records 252 failures; a same-source baseline records 14, so the exact nodeid comparison reports 238 candidate-only failures, 14 retained, and zero baseline-only. The console summary differs from JUnit by one failure/pass; both original outputs are preserved. All 238 candidate-only failures report `BtApiStoreError: external account actor unavailable`. This combination is rejected for main merge.

The formal 013_3 r2 focus, applied to the isolated candidate before the separate root-owned main-tree application, passed 3/3 under the startup SDK guard. The focus had no SDK import attempts and loaded no SDK module; broad suite guards denied 95 baseline and 44 candidate optional SDK import attempts, with no SDK modules loaded. The broad suite was run before patch 5 and was not repeated afterward. The Store file still hashes to the unchanged base SHA `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`; Store r2b/r2c remain unmerged.

## Files and verification

- [Full report and exact patch/test/guard facts](integration-report.json)
- [All failed nodeids and exact baseline/candidate difference](failure-nodeid-diff.json)
- [Combined five-patch delta](combined-five-patch-delta.patch), SHA-256 `51182BAC574C27B5E22F2E289232E2ABE21EFE7833EAB8A4714586B0E7F2ABAD`
- [Evidence ZIP](iteration41-isolated-composition-evidence.zip), SHA-256 `F1966D18808E414ADF1B49ED6667E3056C3313F9EBD6E1581F5CF3DFE2CE6A96`; all 36 entries and ZIP CRC verified
- [Canonical copy receipt](COPY-RECEIPT.json)
- [Copied source manifest](BASE-COPY-MANIFEST.json); `.env` and the protected `runtime-ctp-private` subtree were excluded
- [Original README stored inside the evidence ZIP](ARCHIVED-ZIP-README.md)
- Original ordered patch inputs: [patch 1](inputs/01-r2b-main-base.patch), [patch 2](inputs/02-r2c-store-safety.patch), [patch 3](inputs/03-route-test-migration-r2.patch), [patch 4](inputs/04-query-evidence-test-seam-r2.patch), [patch 5](inputs/05-0133-local-replay-r2.patch)
- Raw baseline and candidate JUnit/log/environment/import-guard files are alongside this README (`stores-runtime-*-run1.*`); 013_3 guarded focus files are `focus-0133-formal-r2.*`.

Patch 1–3 strict apply checks failed on mixed EOL context and passed with whitespace-tolerant checks; patch 4–5 passed strict checks. No hunk was manually resolved. Store bytes after patches 1–2 differ from the author candidate by line endings only: both LF-normalized hashes are `53CD937A7202990DF883FA071C210D31573F11DF83937C05880ABB3CBC50E90B`. The final combined delta passes `git apply --check --ignore-whitespace --whitespace=nowarn` against the same-source baseline.

**Limitations:** candidate actor wiring is unresolved; I22 migration was not applied (its r1 independent QA was `PARTIAL / NEEDS_REVISION`); patch 5 is local replay-only evidence; no native/provider/account operation, real SDK pin, default CTP write, or G5 acceptance is established.
