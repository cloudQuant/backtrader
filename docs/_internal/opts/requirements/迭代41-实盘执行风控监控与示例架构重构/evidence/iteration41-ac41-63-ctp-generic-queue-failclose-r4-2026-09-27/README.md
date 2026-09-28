# Iteration 41 AC41-63: Store generic CTP queue fail-close r4

This archive records the r4 local fail-close change after exact integration and a successful broad Store/Runtime run. It does not authorize CTP, SimNow, or production writes and does not establish universal writer closure. Official active writer dispositions remain REVIEW_REQUIRED / NOT_AVAILABLE; global posture remains NO_WRITE / LIVE_NO_GO.

## Frozen change

The exact-base r4 patch is in [packet/patch.diff](packet/patch.diff). It was authored against Store preimage A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D and targets A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE. Patch SHA-256: 37EA74FA86D600A5FFC47CBC9511C2215B10765EC791FA9DD6F65036EB867B00. Packet manifest SHA-256: 6EBB6B381D371E429C54FBAF1D884E1FBABF254FDCECE7A0E6F035A1AB462FB6.

The patch adds the generic CTP queue fail-close behavior and retains typed managed cancellation compatibility. The durable 12-case fake-only queue contract is [included](packet/test_ctp_generic_sdk_queue_failclose.py). The source package replay instructions, author report, and focused JUnit/log are in packet/.

## Independent and main-tree verification

Independent p3 QA verdict: [PASS_NARROW_ISOLATED_FAKE_ONLY_QA](independent-qa/qa-report.md). Report SHA-256: E0FBE9C3CB5A20C7F406B9DC138B35E4ECC1789C5057E820029934B502BA1E52. Narrow fake-only results were 12 queue-contract passes, 4 recovery-exit passes, 3 budget/sink-lookup passes, 11 original-contract passes with 1 intentionally deselected, and 10 managed-cancel/forwarding compatibility passes. py_compile, project Ruff, exact replay, and packet checks passed. The QA did not independently rerun the broad suite.

After exact integration, root reported the current main broad Store/Runtime suite at 2740 passed / 43 skipped / 2 xfailed / 0 failed in 115.52s, with one existing pytest configuration warning. Raw [pytest log](main-broad/pytest.log), [JUnit](main-broad/junit.xml), and [exit code](main-broad/exit.txt) are included.

The current static inventory is tracked at [live-execution-inventory-candidates.json](../live-execution-inventory-candidates.json) with SHA-256 03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456. It reports 460 candidates across 355 scanned files: 363 writer and 97 dynamic candidates, zero parse errors, verifier 460/460, six tombstones, and 15 scanner tests passing. The unchanged disposition checklist is [live-execution-writer-dispositions.json](../live-execution-writer-dispositions.json). This archive does not duplicate the inventory or change the disposition checklist.

## Limits

The route classifier uses snapshots; the SDK exchange snapshot can fall back to injected API exchange_kwargs. This data is routing metadata, not authorization. A stale non-CTP Store snapshot paired with a CTP-capable injected API remains a conditional generic sink residual. The guard covers _invoke_sdk_command fallback only; an earlier typed managed _execute_sdk_command branch is not globally closed by this patch.

The independent p3 fake-only runs used import tripwires and recorded no CTP/provider SDK or native import, provider I/O, or non-loopback network; the only loopback activity was an asyncio test-harness socketpair. The main broad suite is different: 18 existing tests call the optional_sdk helper for module bt_api_ctp.ctp.client. That helper uses importlib.import_module when the SDK distribution is installed, and the tests passed, so this broad run cannot support a blanket no-SDK-import claim. The broad result records test outcomes only; it provides no account/provider session/order evidence and had no G4 provenance guard. No private config or credentials were read. The historical r3 broad result of 13 failures remains in its separate archive; r4 does not erase that result.

## Archive integrity

[ARTIFACT-MANIFEST.json](ARTIFACT-MANIFEST.json) SHA-256: DB4AD3C005CFDD19C27D8356B332EA791F4F36020687EAE9F24FAA56793C6317. [SHA256SUMS.txt](SHA256SUMS.txt) covers every archive file except itself. All archive artifacts preserve their original source hashes; source paths and sizes are listed in the manifest.
