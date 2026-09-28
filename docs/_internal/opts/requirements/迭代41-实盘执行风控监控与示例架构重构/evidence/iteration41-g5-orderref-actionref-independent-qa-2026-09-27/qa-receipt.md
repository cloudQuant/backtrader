# Independent G5 OrderRef / ActionRef QA receipt

**QA disposition:** the frozen candidate’s tested offline/fake contract subset is independently reproducible. **G5 is not accepted.** The frozen candidate does not prove native OrderRef/ActionRef watermarks or external single-writer fencing, and its proposed Backtrader builder requires a worker API that is absent from the frozen/current worker contract. Main managed CTP writes remain hard rejected; this QA adds no runtime route or authorization.

## Frozen inputs and isolation

- Candidate: `D:\temp\iteration41-g5-order-authority-20260927-candidate`
- Independent execution copies and raw QA evidence: `D:\temp\iteration41-g5-order-authority-independent-qa-20260927`
- Frozen input manifest SHA-256: `79BAB5C0C0E136B722EF5F55C74F93ABA2920F138A629B9AB8B4506D29003827`; all 50 entries, sizes, and hashes verified.
- Candidate output manifest SHA-256: `6DB92F8FD9700EF9BC903C41FCAD0C34BD3012830370B37AFA50E37FAB11450F`; all 87 entries, sizes, and hashes verified; output manifest binds the expected input-manifest digest. The already archived author ZIP was byte-preserved and independently checked: ZIP SHA-256 `339A7029813AA31DDBAC72EC562255F463741F95A0FADEF652B14BD8B36D3B3A`, index SHA-256 `DDA1486D36129E398CA8A443322262580C51FFB57B20AD1B4AEE308C825CA9BE`, 111 members, `testzip()` clean, 111/111 member hashes match.
- 35 copied candidate files compared byte-for-byte with the frozen tree (including cache artifacts present); no mismatches. The 15 non-cache source, bridge, test, and patch files were included.
- All 8 frozen Backtrader source/test inputs compared byte-for-byte to the current checkout; all match. Current checkout HEAD was `ad2c142b9a8b42cede85886528c681abdfcb8096` (working tree has unrelated changes).
- Python 3.11.5 / pytest 8.0.0. No real SDK, native API, provider, account, credentials, or network used. Multiprocess work used only temporary local SQLite files, deleted after each run.

Machine-readable verification is in `evidence/frozen-verification.log` and `evidence/main-input-comparison.log`.

## Independent test results

| Focus | Independent result |
| --- | --- |
| Frozen candidate fake contract, two G5 test files | 14 passed (1.41s) |
| Frozen SDK dispatch/store focus (27 cached node IDs in two files) | 27 passed (2.00s) |
| Entire frozen SDK test directory | 57 passed (3.14s) |
| Exact four-file Backtrader focus with repository plugin defaults | Collection failed at installed `pytest-asyncio` `Package.obj` AttributeError; one existing unknown `asyncio_default_fixture_loop_scope` option warning |
| Same four-file focus with only `-p no:asyncio` | 49 passed, 47 skipped (5.46s in isolated copy; 4.18s in current checkout), one existing config warning |

Skip counts with the plugin disabled: 34 integration cases need reviewed local execution/CTP source candidates; 1 bridge source smoke needs `BT_API_EXECUTION_I9_SOURCE`; 12 parent request-builder cases need fixed I9 and parent source-only candidates on `PYTHONPATH`. The full original plugin error is preserved in `evidence/main-checkout-plugin-run.log`; the retry and skip breakdown are preserved in `evidence/main-checkout-no-asyncio-focus.log`, `evidence/independent-main-skip-reasons.log`, and the JUnit file.

The candidate README reports a historical **54 passed / 47 skipped**, but the original node selector and JUnit were not frozen. Re-running the exact four manifest-listed focus files independently produced **49 / 47** in both the isolated copy and current checkout. The five-test difference is not reproducible from retained evidence; this receipt does not infer its cause or relabel the 54/47 claim.

## Contract review

- One exact `SqliteExecutionStore` object backs the unified authority (`candidate/src/bt_api_execution/ctp_identity_authority.py:69-119`). Order identity mappings use that store’s transaction/lease path; legacy mapping imports are atomic and reject conflicts (`:164-267`).
- OrderRef allocation is 12 ASCII digits, transactionally floors against caller-supplied native and legacy maxima, and reads back the same reservation (`store.py:900-1040`, `ctp_identity_authority.py:269-297`). **The `CtpOrderRefSeedProof` is a caller assertion, not native MaxOrderRef provenance or authorization** (`store.py:900-916`). The digest does not establish who observed the legacy ledger.
- ActionRef rows bind account/day/scope, managed action and order IDs, runtime order ID, and OrderRef. The action table enforces an action identity primary key, account-wide native ActionRef uniqueness, and a same-store order reservation FK (`ctp_identity_authority.py:86-119`). Watermarks are keyed by account/day, while allocation scans the account-wide maximum; first allocation requires an explicit seed, and the signed CTP 32-bit maximum is enforced (`:367-491`). That legacy watermark is also caller supplied (`:33-38`, `:380-384`), so unobserved native ActionRef history remains unproven.
- Cancel staging forbids a caller-provided `OrderActionRef`, inserts the allocated ActionRef alongside the exact reserved OrderRef/target, and verifies stored payload/hash readback (`:493-540`). Fake tests also distinguish ActionRef from a synthetic RequestID.
- Claiming is a durable local claim, not provider dispatch. A typed receipt must echo immutable identity; account-wide `CLAIMED`/`UNKNOWN` rows fence another claim (`store.py:1456-1561`, `:1610-1735`). Prior-generation claimed-without-receipt rows recover as `UNKNOWN`, not replay (`:1737-1793`). The fake bridge dispatches only after durable readback of an exact `QUEUED` receipt and treats that as local queue admission, not provider acknowledgement (`backtrader_bridge/ctp_order_action_bridge.py:155-206`).
- Additional independent process-level check used eight synchronized spawned processes with distinct PIDs against one temporary SQLite DB. They allocated unique ActionRefs 43–50; all eight read back after reopen. An existing UNKNOWN command returned no claim in another process and still returned no claim after reopen. Raw result: `evidence/independent-multiprocess-check.json` and `.log`. This verifies serialized local allocation and UNKNOWN no-reclaim for that fixture; because the workers deliberately share the same owner ID, it does **not** prove OS-process identity or real-account single-writer exclusion. The store renews an unexpired lease with the same owner ID using the same fencing token (`store.py:3244-3275`).

## Worker compatibility negative

The proposed frozen G5 builder reserves ActionRef at line 708 and then calls `worker.stage_prepared_dispatch(..., action_identity=...)` at lines 726–730, wrapping any error as `I9 cancel staging/readback failed closed` at lines 750–752. The current in-repo `CtpI9SingleWorkerPort.stage_prepared_dispatch` contract takes only `(self, prepared)` (`backtrader/stores/ctp_i9_managed_dispatch.py:116-117`); no concrete compatible parent worker source is present in the frozen inputs. The isolated contract negative confirms `action_identity=` raises `TypeError` for the current port signature; an exact-signature spy records zero body calls. The durable ActionRef can therefore be consumed locally before this incompatibility is rejected; the candidate does not stage/send through that worker on this path. Full builder invocation remains unverified because the exact I9/parent source-only candidates were unavailable, matching the skips above. Raw check: `evidence/worker-action-identity-reject.json` and `.log`.

## Conclusion and limits

The local fake adapter passes its frozen tests and an added independent multiprocess uniqueness/reopen check. That is a bounded offline contract result only. Caller-supplied watermarks cannot prevent collision with native IDs not observed by the caller; no accepted native callback correlator/source proves those maxima, the process-level writer lease is not tied to OS identity, and the current worker does not accept the proposed extension. **No G5 acceptance, G6-S/G7-S acceptance, default-route change, or trading readiness follows from this QA.**

## Raw evidence index

- Frozen verification: `evidence/frozen-verification.log`
- Current-main input comparison: `evidence/main-input-comparison.log`
- Candidate fake tests: `evidence/independent-candidate-tests.log` / `.exit`
- SDK 27 focus and full suite: `evidence/independent-sdk-27-focus.log` / `.exit`; `evidence/independent-sdk-tests.log` / `.exit`
- Main pytest plugin failure and disabled-plugin rerun: `evidence/main-checkout-plugin-run.log` / `.exit`; `evidence/main-checkout-no-asyncio-focus.log` / `.exit`; `evidence/independent-main-junit.xml`; `evidence/independent-main-skip-reasons.log`
- Process test: `evidence/independent-multiprocess-check.json` / `.log`
- Worker incompatibility negative: `evidence/worker-action-identity-reject.json` / `.log`
- Exact QA rerun scripts: `verify_frozen.py`, `qa_main_input_compare.py`, `qa_multiprocess.py`, `qa_worker_action_identity.py`, `qa_author_archive_verify.py`



