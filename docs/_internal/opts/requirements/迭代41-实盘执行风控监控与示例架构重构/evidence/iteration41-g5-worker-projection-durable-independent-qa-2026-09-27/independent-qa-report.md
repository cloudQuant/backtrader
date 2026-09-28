# G5 durable target projection candidate — independent QA

Date: 2026-09-27 (Windows, CPython 3.11.5). This review used disposable QA copies under `D:\temp\iteration41-g5-worker-projection-independent-qa-20260927`; the author-frozen tree and main source tree were read-only. No account, credentials, provider, SDK/native CTP module, or network was used. All behavioral runs were local fakes/offline.

## Disposition

**G5 remains BLOCKED / NOT_ACCEPTED.** The candidate demonstrates a durable typed-projection consumer and local fake boundaries, but does not include a trusted native query producer/verifier or authorize a worker handoff. The `V21` worker interface is not compatible with the G5 call shape; ActionRef ownership/cutover is not unified with V21; freshness is not checked at the actual sender/native-call boundary. No production/default route changed.

## Frozen input and independent replay

Author candidate root: `D:\temp\iteration41-g5-worker-projection-durable-20260927-candidate`.

- Frozen-input manifest SHA-256: `79bab5c0c0e136b722ef5f55c74f93aba2920f138a629b9ab8b4506d29003827`.
- Candidate output manifest SHA-256: `5ddb3ca53bff3d61d287846a5f5eea8814fa9d211da109dd05f527c534351fbf`.
- Candidate archive: `D:\temp\iteration41-g5-worker-projection-durable-20260927-candidate.zip`, SHA-256 `c75cba6adcf7db95e420d0d4cfafac39e7179eb6db985cce5096a4c49237d268`; 117 members, CRC `testzip` clean, indexed output member hashes matched.
- Delta patch SHA-256: `a64175be7ca4c855c7cffdfee727463962ff00def4fdc1ca4b18e2839b5c95a6`. `git apply --check` and apply succeeded in a separate copy of the preceding author candidate; all eight touched outputs matched candidate bytes after line-ending normalization (`evidence/patch-replay.log`). No patch was applied to main.
- Frozen inputs: 50 manifest entries; 27 non-cache inputs matched byte-for-byte. The remaining 23 entries were generated Python/tool cache artifacts, excluded as mutable runtime state. Candidate output manifest: 116 entries, all path/size/hash matches in the frozen candidate. The original candidate archive contains those 116 outputs plus its manifest.

## Test replay and four failures

The exact frozen SDK source and tests passed **57/57**. The candidate source against the same 57 frozen SDK tests passed **53** and failed **4** (`evidence/sdk-57-candidate-source.log`). Candidate focus passed **26/26**; the 8-case focused boundary run passed **8/8**. Full commands and exit codes are retained in the raw packet.

| Failure | Classification |
|---|---|
| `test_v4_execution_store_migrates_to_command_outbox_v5`, `test_v2_execution_store_adds_nullable_cumulative_commission_column`, `test_v3_execution_store_adds_ctp_order_identity_reservations` | Three stale schema-version assertions expect `5`; candidate declares `_SCHEMA_VERSION = 6` (`candidate/implementation/sdk/src/bt_api_execution/store.py:415`). A separate actual v5→v6 SQLite probe preserved one existing `READY` SUBMIT row and OrderRef `000000000013`, created projection/consumption tables, and reopened at schema 6 (`evidence/schema5_to_6_migration_probe.log`). This supports a version-expectation update for the tested v5 path; it is not broad migration qualification or proof for every historical schema. |
| `test_cancel_command_binds_orderref_exchange_system_order_and_session_ids` | Legacy fixture stages CANCEL without the newly required typed verified projection/authority. Candidate rejects at `store.py:1764-1766` with `CANCEL requires exact typed target and verified projection`. This is a deliberate fail-closed contract delta that requires fixture/caller migration; it remains a real red test and the old 57-test suite is not green. It should not be described as an unrelated non-CTP regression. |

The candidate focus does not override the 53/57 compatibility result. Existing contract consumers must migrate to typed projection and ActionRef inputs before this delta can be considered integrated.

## Boundary probes

- **Verifier / caller data:** default verifier rejects a caller-provided `dict` and writes zero projection rows. Caller mappings are not silently upgraded. The candidate accepts an injected verifier object; no trust registry/native producer establishes that verifier's authority. Therefore this proves only the default local fail-closed boundary, not trusted native evidence.
- **Tamper / reopen:** focused test drops the immutable-update trigger, changes projection payload, and observes readback reject the malformed hash/payload. Reopening the store does not revive the prior in-memory projection handle. This detects the tested edit; hashes/triggers are not protection from a same-database-owner who can rewrite schema and rows.
- **One use:** first fake CANCEL consumes a projection. A second command with a distinct action identity and reused projection is rejected (`IntentConflictError`); one consumption exists and no second command is created (`evidence/qa_adversarial_probe.log`).
- **TTL:** the regular worker path checks freshness after claim and before calling the sender. If already expired at that check, it leaves the sender uncalled and fences the result to `UNKNOWN` (focused test). But the additional fake-clock counterexample advances time inside a synchronous sender after the worker's check: a modeled SDK-call attempt occurs after expiry and the worker reports `COMPLETED`. There is no recheck at that actual-call boundary. The saved clock values/log are a local fake, not a real CTP send.
- **Awaitable sender nuance:** an `async def` sender is rejected before claim and is not entered by the focused test. A **synchronous wrapper that returns an awaitable is different**: candidate invokes the wrapper at `ctp_single_worker_candidate.py:753`, then checks the returned object at `754-760`, closes the coroutine body, and records `UNKNOWN`. The adversarial probe confirms `sender_entered=["sender-entered"]`, `sender_called=true`, and coroutine body did not execute. The wrapper itself has already run and could have performed side effects before returning; post-return `UNKNOWN` is **not** proof of zero native send.
- **ActionRef:** candidate's single local `CtpUnifiedOrderActionAuthority` reserves unique stable refs across restart/concurrency tests (the focused test assigned 42–49). Its `CtpActionRefSeedProof` contains a caller-supplied legacy watermark and explicitly is not trusted native proof (`ctp_identity_authority.py:33-39`). No native `MaxOrderActionRef` source/cutover is provided. Integrating a V21 allocator that starts independently risks two authorities until a single allocator and trustworthy cutover are specified.
- **V21 handoff:** the frozen V21 worker signature accepts `cancel_target_projection` but not `action_identity`; the exact keyword call raises `TypeError` before body execution. Probe confirmed `bt_api_ctp`, `bt_api_py`, `ctp`, and `ctypes` were not loaded (`evidence/v21_worker_interface_probe.log`). The probe input is bound to frozen root `D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927`: `SOURCE-MANIFEST.json` SHA-256 `b3a614d62b2a4cf1b0dbdfefee463015157dee38bf4c9c5119c64ef2d71d6d24`, Store SHA-256 `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`, and worker SHA-256 `5e378ee77ad5c6e640ad2eca0dacf154849e6fcfe0d04d73e9da6eb2554087b3`. These exact sources/manifests are included in the raw packet. The candidate README also identifies itself as schema 6 and does not implement V21 schema 21. This is an interface blocker, not a native/provider test.

## Harness note and limits

The first ad-hoc import of a test helper failed because the QA `importlib` harness did not register the module in `sys.modules` before executing a dataclass declaration. The failure is preserved in `qa_adversarial_probe-import-registration-failure.log`; the harness was corrected and rerun successfully, with the successful raw output preserved separately. This initial harness error is not counted as a candidate test failure.

Evidence supports **local fake/offline consumer behavior only**. It does not establish native query provenance, account/session authority, production ActionRef seed, full schema migration qualification, safe CTP sender-entry fence, V21 integration, or any G4/F14/production acceptance. G5 is **BLOCKED / NOT_ACCEPTED**.

## Raw evidence

The adjacent raw QA archive and `ARCHIVE-INDEX.json` bind this report, scripts, logs, exit files, SQLite probe states, candidate manifests/patch, and the original author candidate ZIP by SHA-256. The archive index records each member digest and ZIP `testzip` result.