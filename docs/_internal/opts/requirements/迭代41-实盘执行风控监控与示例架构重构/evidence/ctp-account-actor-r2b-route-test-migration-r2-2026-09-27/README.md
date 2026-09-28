# BtApiStore route-test migration R2 evidence

**SAFE_LOCAL_TEST_MIGRATION / NO_WRITE** — isolated fake-only QA; no CTP/provider/SDK/network/account/order writes.

- Independent QA report: independent-qa/REPORT.md
- Author README: README-r2.md
- R2 test-only patch: route-test-migration-r2.patch
- Author manifest: artifact-manifest-r2.json, SHA-256 BC6575878AB6C0CA1053DD0E7325C67371FB9FC209D937C8A600CAE6503745F9
- Independent replay JUnit: independent-qa/pytest.junit.xml
- R1 superseded note: lineage/R1-SUPERSEDED.md
- Evidence manifest: evidence-manifest.json; hash is in evidence-manifest.sha256
- Raw evidence ZIP: r2b-route-test-migration-r2-evidence.zip; SHA-256 is in COPY-RECEIPT.json

R2 supersedes R1's dropped store.start() lifecycle assertion. This archive does not authorize Store production changes or CTP route use.
