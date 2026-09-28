# Mechanical `sdk_api=None` fail-close main integration evidence

Status: **`NO_WRITE / LIVE_NO_GO`**. This is a narrow fake-only fail-closed regression; it does not activate a CTP/SimNow route, prove SDK/session behavior, or grant write authority.

The author source patch changes the `sdk_api is None` branch to `MechanicalBlocked("STORE_SDK_API_NOT_READY")`, preventing a private `_ensure_api_ready()` lazy startup fallback. The clean r2 tests-only patch adds fake boundary tests. Main worktree source and added test hashes exactly match the requested targets; guarded main JUnit is 29/29, guard events are `[]`, and Ruff passes.

- [Author source patch](author/source/candidate.patch) — SHA-256 `299cd0215a8636f25c7e3b74f70cd05c30372059efc1150e9bb96a47f668b70c`
- [Clean r2 test patch](author/tests-r2/tests-only.patch) — SHA-256 `5db64e45c19c63f060786740242b081998ed079e2e4d7086b4c7a99201e453f7`
- [Source candidate report](author/source/report.md) and [independent source QA report](independent/source/report.md)
- [Clean r2 test freeze report](author/tests-r2/REPORT.md) and [independent test-patch QA report](independent/test-patch/report-r1.md)
- [Main 29-test JUnit](main/29-test-junit.xml), [empty guard events](main/guard-events.json), and [Ruff result](main/ruff.txt)
- [Exact target identities](main/target-identities.json) and [EOL normalization note](eol-normalization.md)
- [Payload manifest](payload-manifest.json), [evidence ZIP](QA-EVIDENCE.zip), and [copy receipt](COPY-RECEIPT.json)

The independent test-patch report validates the canonical patch bytes and 29-test combined focus; it marks an earlier r1 directory `NO_MERGE` because that directory also held a stale, unmanifested replay. The clean r2 freeze preserved the same canonical patch without that stale replay. The current main-tree JUnit/guard/Ruff are separately preserved. Source and test evidence remain fake-only; no SDK/native, credentials, private config, provider, network, or orders were used.
