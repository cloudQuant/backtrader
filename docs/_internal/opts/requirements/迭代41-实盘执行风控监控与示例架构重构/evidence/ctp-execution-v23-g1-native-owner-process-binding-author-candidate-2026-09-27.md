# V23 G1 native-owner process binding — author candidate evidence

**Status: author candidate only. Independent review is pending. This page does not claim G5 acceptance.**

## Frozen source

- Read-only source snapshot: `D:\temp\iteration41_v23_g1_owner_binding_freeze_20260927-r3`
- V23 source manifest SHA-256: `f94b924e1e20fba6ccfe5bc028d88a0ad541022afb8e9c7a5f66a597687ab330`
- Direct V22 candidate manifest SHA-256: `8244038ab975f30de6c0ba56c140f033ddd5b5ce5fb3cabc9e60abb7bf24066d`
- Underlying R3r3 + V21 composite SHA-256: `00577665667a33c9a7d62d331c0cad99b0b660790d0b475d0bd8c1b6caa6e2dd`
- Package metadata remains `bt_api_execution 0.2.0`; SQLite schema is 23.
- The V23 delta contains 12 source/test paths. Exact old/new file hashes and byte sizes are in the V23 manifest.

## Local source tests

- Focused owner-binding, dispatch, migration, callback-owner and handoff set: **186 passed, 2 skipped, 0 failed**.
- Full `bt_api_execution` package: **322 passed, 2 skipped, 0 failed**.
- Both skips are SDK integration tests because `bt_api_ctp.ctp.client` is absent; they are not passes. Both runs emitted one existing pytest-asyncio fixture-loop-scope deprecation warning.
- Ruff check on the changed files and Python compileall passed. `ruff format --check` reports 11 files would be reformatted; no whole-file rewrite was applied.

Tests cover immutable V23 process-owner binding and exact claim match; default no-attestor closure; forged/type-confused proof rejection; binding transaction rollback; missing binding blocks session claim; generic zero-inflight claim cannot call the candidate sender; V22 CLAIMED rows without OS binding migrate to UNKNOWN/POISONED and are not replayed; empty database versus malformed/partial schema; and owner epoch/restart fences.

## Dispatch and limitations

Within this isolated package, generic `claim_ctp_dispatch_command()` can persist `CLAIMED` with `native_call_inflight=0`, but the sole candidate sender consumer does not invoke the injected sender. A queued READY V2 command reaching the candidate without a native-owner adapter is atomically moved to `UNKNOWN` and poisons the owner/account family before the sender boundary. Rollback and reopen persistence are covered by local tests.

The default process attestor and process-exit verifier are `None`. Test-only fake injection is not an OS trust boundary; no production crash recovery/replay is available by default; only test-only injected fake verifier paths exist. Main-repository CTP API routes are outside this package snapshot; in particular `backtrader/stores/btapistore.py` retains separate raw `ReqOrderInsert`/`ReqOrderAction` methods. This candidate does not close those routes.

No wheel was built or installed. No native SDK, provider, account, credentials/private config, or network was used. The default path remains closed. **G5 remains closed.**

## Raw source and test bundle

- ZIP: [`ctp-execution-v23-g1-owner-binding-author-candidate-2026-09-27.raw.zip`](./ctp-execution-v23-g1-owner-binding-author-candidate-2026-09-27.raw.zip)
- ZIP SHA-256: `dcd3385cae0590196c99856ec41616483bb1b737a29b104805af42d7ed76e7f0`
- ZIP integrity: `testzip PASS`; all 56 indexed files matched their per-file SHA-256 and byte count.
- Bundle index: [`ctp-execution-v23-g1-owner-binding-author-candidate-2026-09-27.raw.zip.index.json`](./ctp-execution-v23-g1-owner-binding-author-candidate-2026-09-27.raw.zip.index.json) (SHA-256 `134c0d2c1c913fba847876158b96e4526eef15a96bf2635c6fd0cded5308a043`).
- Machine-readable author receipt: [`ctp-execution-v23-g1-native-owner-process-binding-author-candidate-2026-09-27.json`](./ctp-execution-v23-g1-native-owner-process-binding-author-candidate-2026-09-27.json).
