# V23 r3 G1 owner-binding independent QA review

Classification: **independent source-only QA passed; installation/release blocked**. This page reviews the frozen author candidate, not a production deployment.

## Reviewed source

- [V23 author candidate page](ctp-execution-v23-g1-native-owner-process-binding-author-candidate-2026-09-27.md)
- Frozen source: `D:\temp\iteration41_v23_g1_owner_binding_freeze_20260927-r3`
- `V23-SOURCE-MANIFEST.json` SHA-256: `f94b924e1e20fba6ccfe5bc028d88a0ad541022afb8e9c7a5f66a597687ab330`
- Independent copy verification: 44/44 payloads, 1,748,219 bytes; 12 V22 deltas (10 modified, 2 added, 0 removed) matched their source digests.
- Distribution metadata remains `bt_api_execution 0.2.0`; store schema 23.

## Independent tests and guard

- Focus: **20 passed**; generic zero-inflight claim, READY fail-closed behavior, V23 owner binding, and exact V20/V21 migration cases included.
- Full package: **322 passed, 2 skipped**, 0 failed. Both skips are optional TraderClient tests because `bt_api_ctp.ctp.client` is unavailable. One existing pytest-asyncio fixture-loop-scope warning was emitted.
- Before/after source hash maps were identical. Origins matched the independent V23 copy and exact V20/V21 store sources.
- Isolation: zero external network/DNS attempts; zero native SDK modules loaded; zero provider calls. The Windows asyncio loop used only local loopback IPC.

The first isolation-plugin attempt blocked asyncio's literal `127.0.0.1` self-pipe and failed at test setup. Its logs are retained. The corrected temporary guard allows loopback/AF_UNIX only and rejects external/DNS access; the corrected focused and full runs passed. No candidate source changed between runs.

## Static review

`CtpManagedSingleWorkerCandidate.dispatch_managed_command` returns a durable projection for an already claimed row and fails queued READY commands closed to UNKNOWN when no native-owner adapter exists; it never invokes the injected sender. The generic claim test obtains `CLAIMED` with `native_call_inflight=0`, passes the projection through the candidate consumer, and observes zero sender calls. READY fail-close is durable across reopen. An injected poison-write failure rolls back both command and family state before the sender boundary; retry then commits UNKNOWN/POISONED. V20 upgrades to schema 23; V21 claimed rows without process binding migrate to UNKNOWN/POISONED and cannot be cleared by generic recovery. Paths, line references, hashes, commands and raw outputs are in the receipt and archive.

The tests use `FakeNativeOwnerProcessAttestor`. That fixture proves local typed-binding/database behavior only; it is not an OS process/Job attestor and does not establish G1 or G5. The source is SOURCE-ONLY, and its V22 base is explicitly not G5 acceptance. Ruff formatting remains reported nonclean for 11 files; no formatting changes were made.

## Release blocker and evidence

The V23 manifest's `0.2.0` identity collides with an existing Execution package identity. Unique version allocation and coordinated pin migration are required before wheel installation or release acceptance. No wheel or default route was changed.

- [Machine-readable QA receipt](ctp-execution-v23-g1-owner-binding-independent-qa-2026-09-27.json)
- [Raw QA evidence ZIP](ctp-execution-v23-g1-owner-binding-independent-qa-2026-09-27.raw.zip) — SHA-256 `2f72dff009a57e28ee6a8d2bff681229a01b0fc80b94393b01dd897736bee3ec`
- [ZIP per-entry hash index](ctp-execution-v23-g1-owner-binding-independent-qa-2026-09-27.raw.zip.index.json) — SHA-256 `2488af448ed7c54111351e89c1b4d2f6d92e52f2d890476b96bb5140590c9a52`

The ZIP contains 37 evidence members.

See the [composite version/pin migration map](ctp-v23-composite-version-pin-migration-map-2026-09-27.md) for the read-only version cascade and exact main-repo gates. `ZipFile.testzip()` and round-trip per-member SHA-256/size checks passed. It contains manifests, source mapping, environment, static call graph, both JUnit/stdout/guard runs, preserved first-attempt logs, and runner/guard scripts; it is not a source-tree mirror.



