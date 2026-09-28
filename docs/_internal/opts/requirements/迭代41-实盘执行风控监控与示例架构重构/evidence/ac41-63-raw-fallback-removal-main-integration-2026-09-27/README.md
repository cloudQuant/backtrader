# AC41-63 raw fallback removal — main integration evidence

**Disposition: RAW_FALLBACK_REMOVAL_LOCAL_ACCEPTED / NO_WRITE / LIVE_NO_GO.**

This archive records the exact author patch, independent QA package, and root-owned main-tree regression results for the narrow AC41-63 removal of raw ReqOrderInsert / ReqOrderAction fallback paths. The independent QA verdict is SAFE_TO_APPLY_RAW_FALLBACK_REMOVAL_ONLY. That verdict and the main regression do not authorize a CTP write route.

## Main-tree identity and regression

At archive time, backtrader/stores/btapistore.py matched SHA-256 05268b4953a20fa0699639f7e05ee354a4bcafc4b47915dd4ba352b26276e0d9; tests/unit/stores/test_btapistore.py matched SHA-256 649137b29e68f231451c61144ffdc01a0ef80176f7005b0cb9c45e3b72b7a3a1.

- Focused Store file: 138 passed, 0 failed. JUnit attributes: 138 tests, 0 failures/errors/skips, 5.135 seconds.
- Full Store/Runtime lane: root-reported 2,641 passed, 43 skipped, 2 xfailed, 0 failed, with one existing pytest configuration warning. The retained raw JUnit reports 2,686 tests, 0 failures/errors, 45 skipped, 112.766 seconds; the 45 JUnit skips include the 43 console skips plus 2 xfails.
- Ruff, py_compile, and diffcheck each returned exit 0 per the root coordinator. Ruff says “All checks passed!”; the compile log is empty. Diffcheck contains only Git LF-to-CRLF warnings for AGENTS.md and backtrader/stores/btapistore.py.

The root did not retain main-run pytest stdout or exit-code sidecars. Test counts/exit status above are root-reported; the raw JUnit XML and tool logs are retained. The main run used ordinary local pytest with -p no:asyncio, without the independent QA's SDK/native/network guards. It is regression evidence, not a zero-I/O proof.

## Frozen inputs

| Artifact | SHA-256 |
|---|---|
| Author package ZIP | c9a2456d6fff2a1d5743f2402d423eb783720dff90cbe02164e83d27216e3e0b |
| Author manifest | ad48e4dd52404bcb97180aa7fd49f7312bc39dce1cabf3194d0288f39658226a |
| Source patch PATCH-GIT.diff | 2182f12a729afc39dfa6ba4c23bb4accd557f4dcda3138ef238cb039e52de291 |
| Test migration TEST-MIGRATION.diff | 43217ec36a412d68e91133ff9c2b640a47dc0ae49c1eac64abc0cb0b3bc39d7b |
| Independent QA ZIP | 679c066fc424937fa3b61189f91fe6c28aec1f2a6695c15f50be7ff070c63fa9 |
| Independent QA manifest | 27af73ad60b2b49f475ea273f40b5c4e2243197009d0f24fc3adfdebe74f5d36 |
| Independent QA receipt | 4a5c318c71da32d70699a7f0c5a4c48a71cedef518df2164602b21239eb1636a |

Both archived ZIPs passed ZipFile.testzip(); the author archive has 46 members and independent QA has 49. Exact patches, mixed-EOL byte replacement metadata, author snapshots, package manifests, reports, and QA receipt are copied alongside the ZIPs. COPY-RECEIPT.json records each source/archive path, byte count, and matching SHA-256.

## Limits

The reviewed change removes raw fallback calls only. _execution_gate_capability remains mutable same-process Python state, so it does not establish trusted authorization. No real provider acceptance, account operation, native SDK call, network access, or live order is authorized or claimed here. Keep NO_WRITE / LIVE_NO_GO.

## Evidence files

- Evidence manifest: [evidence-manifest.json](evidence-manifest.json)
- Main integration receipt: [main-integration-receipt.json](main-integration-receipt.json)
- Copy/hash and ZIP CRC receipt: [COPY-RECEIPT.json](COPY-RECEIPT.json)
- Author package: [R2-REV2-PACKAGE.zip](author/R2-REV2-PACKAGE.zip), [author report](author/R2-REV2-REPORT.md), [exact source patch](author/patches/PATCH-GIT.diff), [test migration patch](author/patches/TEST-MIGRATION.diff)
- Independent QA package: [QA-PACKAGE.zip](qa/QA-PACKAGE.zip), [QA receipt](qa/QA-RECEIPT.md)
- [Focused JUnit](main/junit/main-focused.junit.xml), [full Store/Runtime JUnit](main/junit/main-full-stores-runtime.junit.xml)
- [Ruff log](main/checks/main-ruff.log), [py_compile log](main/checks/main-pycompile.log), [diffcheck log](main/checks/main-diffcheck.log)
