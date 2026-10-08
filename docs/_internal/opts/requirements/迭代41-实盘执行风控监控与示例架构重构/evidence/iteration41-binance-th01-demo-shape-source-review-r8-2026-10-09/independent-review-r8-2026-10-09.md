# Independent R8 source review

Date: 2026-10-09  
Verdict: `GO_SOURCE_FAKE_ONLY`

This review covers the frozen R8 parent-pipe EOF repair. No Root entry, provider, private input, real pipe, or native/WinAPI path was invoked by the reviewer. The verdict supports sourcefake review only; it does not establish a provider request or TH01 acceptance.

## Frozen inputs

| File | Bytes | SHA-256 |
|---|---:|---|
| `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |
| `scripts/run_binance_th01_demo_shape_probe_r1.py` | 30,321 | `0d6ac6b48540b9fdaf8274d2e303d34e22d095b25ce92bddca23e88281f131ce` |
| `tests/unit/live_certification/test_binance_th01_root_protected_owner_r1.py` | 34,903 | `68c822eebcb91f418ce308e8a1db010c399029f09e6b0a8040a66acf71d30790` |
| `tests/unit/live_certification/test_binance_th01_root_readonly.py` | 13,392 | `88a7dc001e68cbb484498711e81ecee3dd072d0b274ba811d9df9d0127f4cf83` |
| `evidence/iteration41-binance-th01-demo-shape-source-review-r8-2026-10-09.md` | 5,970 | `511452d758e7cadda09d31edcba9b54a94e00eda212379add35744e859c7cd6a` |

## Review findings

- The owner change from preserved R7 is narrow: it imports `multiprocessing.connection.wait` and uses a 100 ms bounded wait after reading the first frame and closing the worker. Readiness is followed by `recv()`; only `EOFError` proves a single frame followed by EOF. A second frame is rejected. Empty readiness, wait errors, and non-EOF read errors fail closed.
- The new fake sets `FakeConnection.poll()` to raise synthetic `OSError(winerror=109)` after the writer closes and buffered frames are consumed. Its wait leaf independently reports the connection ready without calling `poll()`, and tests assert the wait hook ran. The old `parent.poll(0.1)` implementation would therefore fail the valid-frame case, making this a distinguishing regression test.
- Negative cases cover no readiness, a second frame, a wait error, a receive error, malformed/out-of-window frames, and uncertain worker cleanup. The fake GET test uses synthetic HTTPS/process/pipe leaves and the actual worker/parent functions; it runs the worker inline and does not test OS-spawn behavior.
- Diff against the preserved R7 bytes shows the acceptance change is confined to the EOF readiness primitive and corresponding fake regressions. The launcher changes only its pinned owner hash. Existing frame/query-time, route, cleanup, account schema, pagination, no-truncation, and TH01 readiness gates remain unchanged.
- Root's public R7 repro demonstrates `poll()`'s WinError 109 behavior and bounded-wait/EOF behavior, but its own record says it does not prove the exact earlier private runtime exception. This review does not strengthen that attribution.

## Verification

The specified isolated sourcefake focus passed:

```text
python -m pytest -p no:asyncio tests/unit/live_certification/test_binance_th01_root_protected_owner_r1.py::test_fixed_get_parent_accepts_bounded_frame_and_preserves_cleanup_failures tests/unit/live_certification/test_binance_th01_root_protected_owner_r1.py::test_fixed_get_worker_and_parent_emit_only_closed_transport_diagnostics -q --tb=short
```

Result: `2 passed`, with one existing pytest configuration warning for `asyncio_default_fixture_loop_scope`. All four frozen source/test pins and the R8 packet hash matched before and after the test run. The Root-owned R8 pipe/acceptance gate remains a separate local transport check; no actual R8 provider invocation was performed by this review.
