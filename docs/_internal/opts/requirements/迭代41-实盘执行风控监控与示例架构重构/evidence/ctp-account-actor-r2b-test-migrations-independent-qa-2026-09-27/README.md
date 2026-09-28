# r2b test-migration independent QA archive

Status: `SAFE_LOCAL_TEST_MIGRATION` for credential-safety tests; `SAFE_LOCAL_TEST_MIGRATION_WITH_COVERAGE_LIMIT` for the projection bridge. `NO_WRITE / FAKE_LOCAL_ONLY`.

The raw independent reports, author inputs/patches, source snapshots, JUnit results and logs are preserved under `raw-qa/`. The projection migration keeps adapter-level projection/replay checks and NON_CTP private queue primitive checks, but does not retain the former positive `BtApiStore`→adapter submit/cancel wiring assertion or the old raw-CTP-cancel queue/worker side-effect test. Those tests are narrowed to adapter/private queue contracts and a CTP constructor fail-closed check. Do not count the 18 migrated node IDs as complete business/Store integration acceptance.

The r2b/r2c Store candidates remain unmerged; the 258-failure r2b main-tree regression remains the merge blocker. No AccountActor or provider authority is established.

- [Independent report](raw-qa/REPORT.md)
- [Independent QA manifest](raw-qa/qa-manifest.json)
- [Raw QA payload ZIP](raw-qa.zip)
- [Archive index](archive-index.json)
