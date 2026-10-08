# M01 R24 R7 independent source review

**Decision:** GO_SOURCE_FAKE_ONLY. **Actual status:** ACTUAL_HOLD.

This review is bound to the exact helper and test hashes in `review.json`. It found no source blocker within the source/fake claim. The focused isolated QA passed 28 tests, with one existing pytest configuration warning, in 130.50 seconds (exit 0). The author separately reported 28/28 in 130.07 seconds.

The pinned runtime sources (19/19), declared test closure (45 unique paths), and sanitized source snapshot archive (45 indexed members) matched their declared sizes and SHA-256 digests. The archive was checked in memory; no files were extracted.

The cleanup path accepts missing `origin` only for the same-result R9 sidecar and R10 composer rows, comparing their exact producer path, role, digest, size, and bytes. All other rows require a nonempty origin. The production map reconstruction and canonical 154-row, 190-row parent, and 299-row extra-map checks remain in place.

The positive integration uses the actual pinned R23 producer, R14-to-R8 normalized result projection, R23 release callback, and pinned CUv2 generator, with fake API/CLI leaves. It verifies owner/source/callback/scope bindings and releases only after the checks pass; failed or uncertain paths retain references.

Coverage limit: `_fresh` leaves `_verify_loaded_modules` mocked even in the positive integration test. This note does not claim that verifier call is integration-tested. The full test remains source/fake only; it does not prove actual Root custody or cleanup, native/provider behavior, account behavior, or case acceptance.

Independent run: 28 passed, 0 failed, 0 skipped, exit 0, 130.50s; one existing unknown `asyncio_default_fixture_loop_scope` pytest warning. It used the designated isolated CPython with `PYTHONPATH` removed, plugin autoload disabled, explicit repository and QA site-packages, disabled asyncio/cacheprovider plugins, and a unique repository-local basetemp.
