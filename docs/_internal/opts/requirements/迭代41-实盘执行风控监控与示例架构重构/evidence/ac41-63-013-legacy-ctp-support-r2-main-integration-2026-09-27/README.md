# AC41-63 013_1/013_2 legacy CTP support import/helper r2 — main integration

**Disposition:** `LOCAL_INERT_IMPORT_AND_LEGACY_HELPER_FAILCLOSE_ONLY / NO_WRITE / LIVE_NO_GO`. The official inventory rows remain `REVIEW_REQUIRED / NOT_AVAILABLE`.

The two support modules match the r2 patched source hashes exactly: 013_1 `E9BFE8EDD8854CEF1184082407BFE5EA2A81268923CBC7A27EB6EAC8F779BE50`; 013_2 `37706DCA228382509581CD76C4D6B938C40E58A5BF6A5F3D44E843C7BBEAECB7`. The persistent inert-import test is `900E5D663F7B829C2AC788655CB78B617583920265B72D9F87A6FC0E19E53575`. Candidate r2 removes the top-level `load_dotenv_if_available()` call and retains fail-closed legacy `create_live_store`/`create_live_broker` guards.

## Main-tree verification

The main lane passed **33 tests, 0 skipped, 0 failed**, with one existing pytest configuration warning. It runs `tests/unit/test_ctp_pair_examples.py` plus the persistent import guard. Ruff on the test file, isolated-output `py_compile`, and `git diff --check` passed. Source-wide Ruff exits 1 for four `SIM112` lower-case environment-alias findings in lines not touched by the r2 patch; the raw output is retained.

Independent r2 QA report SHA-256: `2494C1D1D9B1C6CFC13F08F81E7A8ABEF3E7A0642116081666F8A9EF61C52A67`. It verified the frozen patch/source hashes, two focused fake helper/import tests and 32 local replay regressions; its guards recorded zero `.env` reads, dotenv load/import calls, SDK/native loads, network calls, Store/Broker production constructors, or writes.

## Limits

This is local import/helper fail-close evidence, not writer closure or route authorization. `load_dotenv_if_available()` remains explicitly callable and reads its `.env` path if deliberately invoked. Pair strategy `_submit_market` methods remain usable with a custom broker composition; the patch only fences the paired legacy live factory helpers. No CTP SDK/native, credentials/private config, provider, network, account, order or cancel was used. `NO_WRITE / LIVE_NO_GO`; no SimNow or production acceptance.

## Contents and integrity

`r2-candidate/` preserves the exact candidate manifest/patch and author test/replay artifacts; `test-lineage/` preserves the persistent test's r1 test-only origin; `independent-qa/` retains the independent report/result and runner; `main-source/` contains the exact three integrated files; `main-run/` retains JUnit, stdout/stderr, exit codes, Ruff, compile, diffcheck and command metadata. The payload manifest and SHA sums bind copied files. See [ZIP-RECEIPT.json](ZIP-RECEIPT.json) for archive CRC and digest and [ARCHIVE-RECEIPT.json](ARCHIVE-RECEIPT.json) for outer hashes.
