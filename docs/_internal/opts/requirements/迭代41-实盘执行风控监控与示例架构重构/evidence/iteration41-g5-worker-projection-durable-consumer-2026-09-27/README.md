# G5 durable target-projection consumer follow-on

**Status: `TYPED_DURABLE_CONSUMER_ONLY / BLOCKED / G5 NOT ACCEPTED`.** The
candidate is offline and fake-only. It did not modify the production Store,
runtime registry, default route, private configuration, credentials, SDK
installation, or any real account. Managed CTP writes remain closed.

This archive preserves a new isolated follow-on to the earlier worker handoff.
It adapts the V21 durable target-projection / one-use-consumption shape to the
frozen author candidate Store schema 6. It stops at a durable typed consumer:
the reviewed SDK source has no trusted native order-query producer or current
SDK-owned readback adapter. `_RejectCtpOrderTargetProjectionVerifier` remains
the default, and caller mappings are rejected.

## Frozen artifact identities

- Author candidate source: `D:\temp\iteration41-g5-worker-projection-durable-20260927-candidate`
- Author candidate ZIP: [candidate.zip](candidate.zip), SHA-256
  `C75CBA6ADCF7DB95E420D0D4CFAFAC39E7179EB6DB985CCE5096A4C49237D268`
- Candidate output manifest: [output-manifest.json](output-manifest.json),
  SHA-256 `5DDB3CA53BFF3D61D287846A5FEEAA8814FA9D211DA109DD05F527C534351FBF`
- Frozen input manifest: [frozen-input-manifest.json](frozen-input-manifest.json),
  SHA-256 `79BAB5C0C0E136B722EF5F55C74F93ABA2920F138A629B9AB8B4506D29003827`
- Durable-consumer delta patch: [candidate.patch](candidate.patch), SHA-256
  `A64175BE7CA4C855C7CFFDFEE727463962FF00DEF4FDC1CA4B18E2839B5C95A6`
- Candidate README: [author-candidate-README.md](author-candidate-README.md)
- V21 source audit: [v21-projection-contract-audit.md](v21-projection-contract-audit.md)

The manifest hashes 116 candidate outputs. The ZIP has 117 members: those 116
outputs plus the manifest itself. [candidate-zip-crc-check.json](candidate-zip-crc-check.json)
records a successful CRC scan, exact member-set comparison, and zero
per-output SHA mismatches. [copy-hash-verification.json](copy-hash-verification.json)
records 21 detached file copies; all source and archived SHA-256 values match.
The complete canonical evidence folder is indexed by
[archive-manifest.json](archive-manifest.json), with its detached
[SHA-256 file](archive-manifest.sha256).

## Test evidence

The tests were rerun against the frozen candidate source on Python 3.11.5 with
`PYTHONDONTWRITEBYTECODE=1` and pytest's cache provider disabled. Raw logs,
JUnit XML, and hashes are retained in
[test-rerun-evidence.json](test-rerun-evidence.json).

| Run | Result |
| --- | --- |
| Candidate focus | 26 passed, 0 failed |
| Frozen SDK suite with candidate source first | 53 passed, 4 failed |
| Same SDK suite with untouched frozen SDK source | 57 passed, 0 failed |

The four candidate-source failures are preserved in
[sdk-candidate-tests.log](sdk-candidate-tests.log) and
[sdk-candidate-junit.xml](sdk-candidate-junit.xml):

1. `test_v4_execution_store_migrates_to_command_outbox_v5` expects schema 5;
   this candidate adds schema 6.
2. `test_cancel_command_binds_orderref_exchange_system_order_and_session_ids`
   uses a legacy CANCEL fixture without the required typed target projection
   and candidate-issued ActionRef.
3. `test_v2_execution_store_adds_nullable_cumulative_commission_column` expects
   schema 5 rather than 6.
4. `test_v3_execution_store_adds_ctp_order_identity_reservations` expects
   schema 5 rather than 6.

The untouched-source comparison passes all 57 tests; it is a baseline only and
does not establish acceptance of the candidate.

## Contract and limits

- The candidate persists an exact typed verifier result in the same SQLite
  Store, hashes and reads that row through a Store-instance-scoped handle, and
  consumes it once with the CANCEL command. Durable hash/readback proves stored
  byte consistency, not native evidence origin.
- Positive paths inject test-only synthetic evidence and a test-only verifier.
  Projection readback itself is not monkeypatched. There is no concrete native
  query verifier/producer in the audited V21 source; the default verifier
  rejects and no production projection can be issued through the default path.
- The candidate OrderRef/ActionRef seeds remain caller-supplied, unverified
  assertions. Its only accepted ActionRef issuer is its own
  `CtpUnifiedOrderActionAuthority`. V21 has a separate per-account ActionRef
  allocator starting at 1; the candidate does not import or mix it.
- The V21 worker `stage_prepared_dispatch` has no `action_identity` keyword.
  Candidate schema 6 and the V21 schema 21 are not a pinned compatible Store
  pair. `session_generation_id` does not prove OS process generation or native
  connection ownership.
- Projection expiry is checked again after claim before the synchronous fake
  sender. The candidate uses local monotonic time, not a trusted native query
  clock, and rejects awaitable senders because no guarded async send-entry
  fence exists. Claimed crash/uncertain outcomes remain UNKNOWN with zero
  replay in the fake cases.
- Candidate changed files pass Ruff `E4,E7,E9,F,I` and `py_compile`. The broad
  Ruff scan also reports import-formatting errors in untouched frozen
  `cancellation.py` and `facade.py`; see the retained raw scope log.
- Frozen-input integrity reports 27 non-cache manifest entries matching. The
  archived input manifest also lists 23 interpreter-generated `__pycache__`
  entries, which the integrity check excludes because imports can mutate or
  remove bytecode.

No real SDK, session, provider, account, order, cancel, live runner, or default
route was exercised. **G5 remains NOT ACCEPTED.**

## Raw runs and static checks

- [Candidate focus log](focus-tests.log), [JUnit](focus-junit.xml),
  [exit code](focus-tests.exit)
- [Candidate-source frozen SDK log](sdk-candidate-tests.log),
  [JUnit](sdk-candidate-junit.xml), [exit code](sdk-candidate-tests.exit)
- [Untouched-source baseline log](sdk-frozen-source-tests.log),
  [JUnit](sdk-frozen-source-junit.xml), [exit code](sdk-frozen-source-tests.exit)
- [Author-run logs](author-focus-tests.log),
  [author SDK candidate run](author-sdk-candidate-tests.log),
  [author SDK baseline](author-sdk-frozen-source-tests.log)
- [Changed-file Ruff](author-ruff-changed-files.log),
  [full-scope Ruff result](author-ruff-full-scope.log),
  [py_compile](author-pycompile.log),
  [patch apply check](author-patch-apply-check.log),
  [frozen-input integrity](author-frozen-input-integrity.log)
