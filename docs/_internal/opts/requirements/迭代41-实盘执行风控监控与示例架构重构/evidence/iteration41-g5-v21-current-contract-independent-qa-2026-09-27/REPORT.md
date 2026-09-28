# Independent QA — G6 G5/V21 current cross-package fake contract r0

## Disposition

**PASS for the isolated LOCAL_FAKE_ONLY cross-contract checks; NO_AUTHORITY / NO_WRITE / LIVE_NO_GO / NO_MERGE.** Exact patch replay and the requested fake behaviors passed. This does not show that the historical G5 dual allocator is the current active G5 adapter, nor that G5/V21 dual-ledger uniqueness is accepted.

## Frozen packet identity and label correction

Candidate: `D:\temp\iteration41-g5-v21-current-contract-candidate-r0-20260927`

The author message's `404EC9E4…` value belongs to `PREIMAGE-TARGET-MANIFEST.json`, not the top-level `manifest.json`. At the first QA read, and in the saved independent copies, the files were:

| File | SHA-256 | Bytes | Source LastWriteTimeUtc |
|---|---|---:|---|
| `manifest.json` | `15C37A6CC5503127C63D6987B9DE0FD71A48181FC33DFF5A4E52F57A8FC5D129` | 5,288 | 2026-09-26T16:07:41.9806284Z |
| `PREIMAGE-TARGET-MANIFEST.json` | `404EC9E4B21A0FBA776FFFAC2EBB4DE46BB25508340DC1214304D58FD66DFFD9` | 8,773 | 2026-09-27T12:10:23.4898987Z |
| `SOURCE-MANIFEST.json` | `B3A614D62B2A4CF1B0DBDFEFEE463015157DEE38BF4C9C5119C64EF2D71D6D24` | 5,299 | 2026-09-26T19:24:48.2143228Z |
| `G5-V21-CURRENT-CONTRACT.patch` | `AC5F984B6B49EC5E6EB5C99DD31F7E0B8D0A3548B68B8263D629AD71FCDC2B3A` | 276,877 | 2026-09-27T12:07:29.1350695Z |

The current frozen files matched the saved QA input copies byte-for-byte at the integrity recheck (2026-09-27 12:23:02 UTC); no candidate files were modified by QA. The first-read wall-clock event was not separately timestamped, so the table preserves the source file times and the original first-read hashes rather than inventing a read timestamp. The top-level manifest also carries an older stale Store preimage row; the source and preimage/target manifests bind the actual r3 Store preimage used below.

## Exact independent replay

I copied the named V21 r3 preimage to
`D:\temp\iteration41-g5-v21-current-contract-independent-qa-20260927\replay`
and copied only the frozen manifests and patch into its `packet` subdirectory. All 32 SOURCE-MANIFEST rows matched. All 10 changed-payload preimage rows matched (including expected-absent files); `git -c core.autocrlf=false apply --check -p1` and apply both passed. All 10 post-apply target SHA-256 values matched `PREIMAGE-TARGET-MANIFEST.json`.

Patch paths are confined to the copied `src/bt_api_execution` package and `tests/` (including test fixtures); no `backtrader_runtime` or repository default-route file is patched. The frozen packet declares `main_tree_changes: []`.

## Source identity finding

The historical separate G5 allocator and the current active runtime adapter are different source artifacts:

- Historical G5 candidate allocator, `D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py`: **28,615 bytes, SHA-256 `8E7ABDD2819F66B6EC3D5FF1D5A049FCBB91AE8E71327665EE925098D35F647D`**. It defines `CtpUnifiedOrderActionAuthority`, `reserve_cancel_action_identity`, `ctp_action_ref_watermarks`, and `ctp_action_identity_reservations`.
- Current active G5 runtime adapter, `backtrader_runtime/ctp_managed_action_authority.py`: **48,077 bytes, SHA-256 `7CAED2A83447173FF93755C5561713C2E2F8F410D21AE78E4A07CCCD3F681C66`**. It defines `CtpManagedActionAuthorityAdapter` and its action digest/verifier logic; it does not contain the old unified allocator class, reserve API, or tables.
- The test fixture `tests/fixtures/g5/ctp_managed_action_authority.py` is exactly the current adapter bytes (same `7CAED2…` hash). The fixture copies the current runtime candidate, session candidate, and inventory at hashes `765655CFBE1B4E92959D35B02D0C5D5C203E205816CBAFC50891238952D258DA`, `E80E23200ACFB2F3148D914EF5D6076DDD077F39240644DF53F4780147D4F2B6`, and `0EBC77EFD22E21B299E794E09C8CB879899B5DC4EFD3302E86D2D9C626B0F6CB`, respectively. The current main inventory has no registration reference to `ctp_managed_account_runtime_candidate`; the test fixture asserts the same.

Thus this candidate does **not** integrate the historical dual allocator into the current active adapter. Its new contract test feeds the current adapter's digest the V21 command and separately relies on V21's durable allocation-map gate. That is useful fake contract evidence, not evidence of a unified G5 allocator, a production account authority, or G5 acceptance.

## Requested fake behaviors

The exact replay's cross-contract test file passed **4/4**. The independent full package suite passed **275**, skipped **2**, failed **0**.

1. **Stage, committed mapping, restart:** with a per-Store synthetic floor of 37, the V21 fake Store stages a cancel with ActionRef 38, commits the command and allocation mapping in its SQLite transaction, checks the correlation/native payload split, closes, reopens a default Store, and confirms the mapping-backed command survives and yields the same G5 current-adapter digest. This uses a fabricated floor and local SQLite only.
2. **Mapping deleted, G5 digest still valid, sender fenced:** the test removes the allocation row after dropping the immutable-delete trigger on that test's temporary SQLite database. The current G5 adapter digest remains valid for the unchanged command. Worker dispatch calls V21 `claim_ctp_dispatch_command`; inside the claim transaction V21 checks the ActionRef allocation mapping before the READY→CLAIMED update. The call raises `DurableStoreError`, the command remains READY, and the fake sender's call list stays empty. The trigger drop and row deletion exist only in test code against pytest `tmp_path` SQLite files; they are not package/runtime behavior.
3. **Same-Store concurrency:** two threads stage cancels through the same Store and produce unique ActionRefs `[38, 39]`. Its later map-deletion probe again shows a digest alone does not replace V21's durable mapping check.

A separate default-Store probe found the constructor has no native-floor source parameter, rejects an unsupported source kwarg, and `_verified_ctp_native_action_ref_floor` raises “trusted external CTP native ActionRef floor authority is unavailable”. The fake helper monkeypatches only a Store instance inside tests. No default route consumes it.

## Guarded runs, Ruff, and temp scope

- Focused JUnit: **4 tests, 0 failures/errors/skips**, SHA-256 `FCE53BD7BF3B9797185BD48BFAD3DEFDB2A282BA127D948BA21DEE7E68D0D26E`.
- Independent full JUnit: **277 total, 275 passed, 2 skipped**, SHA-256 `4C57A7E70C0EFBBE0621F5B16EE2A66034445121E059163100E314AC3059EDD5`. The two skips are optional real-`bt_api_ctp` tests; the guard rejected both import attempts before the SDK loaded. Full guarded event log SHA-256: `8DC126A0418D9D6F13A8A7F99E25D580E14AFA90BABFEB1A566BF7A6A1B1125A`, containing those two blocked imports and 18 allowed Windows asyncio socketpair self-pipe events, with zero blocked external-network events.
- Ruff check passed for the Store, fake helper, dispatch/callback tests, and cross-contract test; Ruff format check passed for both new helper/test files.
- During initial exploratory pytest invocations, TEMP/TMP were not overridden, so pytest `tmp_path` used the Windows default `C:\Users\yunji\AppData\Local\Temp`. I did not clean or alter that OS-temp location. I then reran the focused and full suites with both `--basetemp` and TEMP/TMP under this QA directory; the observed fake SQLite databases are under `pytest-basetemp-r2` / `pytest-basetemp-full` here. No SDK/native/provider module loaded, no external network was used, and no account or private config was accessed.

## Limits

The old G5 collision repro remains separate historical evidence and is not upgraded by this test: the packet records that it did not stage a complete V21 cancel/allocation row. There is still no accepted authenticated native MaxOrderActionRef floor authority, cross-process account-wide writer fence, coordinated G5/V21 migration/reconciliation, provider route, or live sender acceptance. This QA makes no G5 or F14 acceptance claim.

