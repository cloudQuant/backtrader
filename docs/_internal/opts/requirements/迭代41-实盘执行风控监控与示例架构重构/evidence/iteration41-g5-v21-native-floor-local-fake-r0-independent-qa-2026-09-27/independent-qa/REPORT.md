# Independent QA — G5/V21 ActionRef native-floor r0

## Verdict

**SAFE_LOCAL_FAKE / NO_MERGE.** The isolated patch is internally consistent for local fake-only contract testing and retains fail-closed behavior when trusted native ActionRef floor authority is absent. It does not provide external authority and is not evidence that G5/V21 dual-ledger reconciliation or live order acceptance is solved. Do not merge it as a production/live enablement.

## Frozen identity and exact replay

Candidate: `D:\temp\iteration41-g5-v21-actionref-nativefloor-candidate-r0-20260927`

- `manifest.json` SHA-256: `15C37A6CC5503127C63D6987B9DE0FD71A48181FC33DFF5A4E52F57A8FC5D129`
- `SOURCE-MANIFEST.json` SHA-256: `B3A614D62B2A4CF1B0DBDFEFEE463015157DEE38BF4C9C5119C64EF2D71D6D24`
- `PREIMAGE-TARGET-MANIFEST.json` SHA-256: `66326D21B91C30C0049560D3C29286E92EBFCBE7CDECBA5F4BBB2E45AA208E71`
- Patch `ACTIONREF-NATIVEFLOOR.patch` SHA-256: `D09D0C7F8376696907E0DF37EC97A9D923450273B96F3557586389DF4BEBA66F`

The independent replay used the frozen r3 source snapshot at
`D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927`, with a separate disposable replay checkout under
`D:\temp\iteration41-g5-v21-actionref-nativefloor-independent-qa-20260927\replay`.
All five preimage rows matched their declared SHA-256 values. Patch `git apply --check -p1` and apply both succeeded with `core.autocrlf=false`; all five resulting target hashes matched the target manifest:

| File | Replayed target SHA-256 |
|---|---|
| `src/bt_api_execution/store.py` | `eb4c1b14e3f042f737950bc27e7bd6750f30753c2f4f93695c282eae8587dea6` |
| `tests/test_ctp_dispatch_commands.py` | `8968fccef247a5e74ee250d261936c29f0ccd4799182304011891e40b07f2820` |
| `tests/test_ctp_callback_source_bridge.py` | `88cd49b360e2a306300404829e114ffc9a3b2871a4efd7aaee354b67ec800cb5` |
| `tests/test_ctp_callback_session_router.py` | `e1c8b80ee2ab782a2af2f9f0039530df482862a30dac640d535e872e89e761f9` |
| `tests/_fake_native_action_ref_floor.py` | `b0d928788ed3fcc476b3a27ecd75b08dd3a6452987c7df389b91c234205c8c0c` |

**Manifest caveat:** the candidate's legacy `manifest.json` has a stale preimage digest row for `src/bt_api_execution/store.py` (`75b01d…`); the actual frozen preimage is `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`. The SOURCE-MANIFEST and file-level preimage/target manifest contain the matching snapshot hashes, and exact patch replay was verified against those bytes. This bookkeeping defect should be corrected in any successor package.

## Contracts reviewed

- The Store constructor has no native-floor source/snapshot/verifier injection parameter. Passing such an unsupported parameter is rejected, and the snapshot is not exported from the package API.
- The Store's default trusted-floor seam raises `ContractValidationError` (“trusted external CTP native ActionRef floor authority is unavailable”). An ordinary OrderRef seed proof and fake target-projection verifier did not unlock staging: the operation failed closed and created no command.
- Caller-created arbitrary Python subclassing/monkeypatching of the protected method can replace that seam for local fake tests. This is not an external trust boundary. The test helper does this on an individual Store instance; package runtime/CLI/Store factory does not wire it in. The candidate must remain explicitly LOCAL_FAKE_ONLY.
- High-water gaps are intentionally allowed by the plan. A counter ahead of visible allocation rows is a burned high-water mark, remains monotonic, and is never recycled: after ref 38, a burned counter value 39 caused the next ref to be 40. This is not treated as a defect.
- Actual contradictions fail closed: counter below allocation history; counter missing while allocation history exists; or exact replay with its ActionRef allocation map missing/mismatched. A counter downgrade was blocked by its trigger.
- ActionRef is range-checked as signed int32 (1 through 2,147,483,647); exhaustion rejects. Caller-prepared cancel input cannot supply the native ActionRef. The Store allocates it.
- Counter advancement, command insertion, immutable ActionRef allocation mapping, and target-projection consumption are in one transaction. Injected failure after staging rolled all of them back; retry started at ref 1.
- Exact identical retries return the same command/ref after immutable-field and allocation checks; changed intent conflicts. Allocation and replay paths validate the mapping.
- The local SQLite allocator handles its own transaction/concurrency domain. It does not establish an account-wide external writer epoch or coordination with the G5 ledger/native counter.

## Independent tests and environment guard

The frozen candidate's author JUnit reported 271 passed and 2 skipped. A fresh independent guarded run against the exact replay also reported **271 passed, 2 skipped, 0 failures/errors**.

- Independent JUnit: `D:\temp\iteration41-g5-v21-actionref-nativefloor-independent-qa-20260927\artifacts\independent-corrected-junit.xml`
- JUnit SHA-256: `B1B589D1CEC65C2040F8D4D2F16BD39DCFF472395CDB6A55B0DC33B1761CCEE8`
- Output: `D:\temp\iteration41-g5-v21-actionref-nativefloor-independent-qa-20260927\suite-corrected-output.txt`
- Adversarial history probes: `D:\temp\iteration41-g5-v21-actionref-nativefloor-independent-qa-20260927\history-probes-output.txt`
- Ruff check passed for all five changed files; `ruff format --check` passed for the fake floor helper.

The guard blocked two optional `bt_api_ctp` import attempts before loading any SDK; those correspond to the two skipped optional tests. Windows asyncio created 18 local socketpair self-pipes, allowed as loopback IPC; no external socket operation was allowed or observed. No provider/API SDK was loaded and no external network, credentials, native library, or account was used.

## Remaining blockers and scope

There is no trusted native MaxOrderActionRef floor source or verifier, authenticated durable remote Actor, account-wide writer fence/epoch, coordinated migration/fencing of the legacy G5 and V21 ledgers, or accepted reconciliation evidence in this candidate. The source does not register a live runtime route. Caller-supplied seed/watermark hashes are not authority. This package cannot claim G5/V21 dual-ledger resolution, live dispatch safety, or F14/G5 acceptance.

No main-tree files, real SDK/native/provider paths, private configuration, or account data were modified or accessed. All replay, tests, and probes were confined to the named temp QA directory.

