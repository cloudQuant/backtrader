# I50 27b build functional adjudication (2026-10-27)

Decision: **PASS_FUNCTIONAL_LONGSTREAM_BUILD_ONLY** for the bounded build-mode functional slice. The runner original **FAIL / exit 3** is preserved.

The run completed its 100,000-grid, two-hour synthetic profile and met the listed functional, factor-oracle, recovery, journal, cleanup, and bounded-memory checks. Its only reported gate failures are the two durable-decision latency thresholds; execution-context.json explicitly marks performance thresholds nonblocking for this functional adjudication.

## Identity and original outcome

- Case: 27b-build; source revision: a69a494e7b26251703c130c2b9083f9ce196ef2c; mode/profile: build / representative-six; scenario: 27b.
- Runner SHA-256: 75ca8866f6adb7fb8fc2dd361107d7749170d2cb453ba4cff4754a334567c2db; launch wheel SHA-256 pin: bc33814b37ab44963ab9a964e689ee7c2665ed9a709b5bcbe0eb0bcd9770b7ee; selected package root: D:\temp\i5051c-20261025-r6\venv\Lib\site-packages.
- Result schema/status: 1 / FAIL; completion exit: 3; original stdout status: FAIL; stderr is empty.
- Run duration: 9150.843 s (minimum 7200 s; duration_seconds_met=True).
- Input-generation pin: c066ca821f2ecd79616fa3b649f392b2f7050c9cfd6ead3fa6524e8ef54a4b0c; 36 loaded Backtrader module pins match pre/post.

## Functional evidence

- Stream: 100000 evaluation grids + 316 warmup slots = 100316 slots; Strategy next ran 100316 times. Synthetic source returned 2006320 events across 20 started/registered/subscribed feeds. Maximum current member rows was 20; pending slots peaked at 1; gaps were 0, cohort frozen was False, and all 20 feeds ended at slot 100315.
- Oracle: 12000000 comparisons and finite outputs; each factor had 2,000,000 comparisons/finite values, at least two distinct finite values, and zero reason/unavailable failures. Rank/correlation reason failures: 0/0; tolerance: abs(actual-reference) <= 1e-12 + 1e-10*abs(reference).
- Recovery: disconnect/resume/barrier were observed at grid 50316; barrier timeout was False; generation stayed synthetic-generation-1; no feed/strategy/factor advance occurred while disconnected. Recovery took 47.0 ms.
- Broker: one BackBroker submit and cancel during idle; notifications were Submitted, Accepted, Canceled; final state was Canceled with zero fill, zero position, and zero execution intents. Report says this order lifecycle is not journaled by the no-op decision.
- Journal: 100000 no-op rows, cursor 100000, zero intents; WAL/FULL (synchronous=2). Close, passive checkpoint, reopen, readback match, journal finalization, and synthetic Store close all report success. Payload bytes: 81600752 / 536870912; settlement reserve stayed unused.
- Physical storage: sampled DB/WAL high-water {'database_bytes': 201678848, 'physical_bytes': 205918360, 'wal_bytes': 4239512}; 392 samples at 256-grid intervals. Physical DB/WAL capacity enforcement is False; this is observation, not a quota claim.
- Memory/capacity: process RSS growth 2134016 / 33554432 bytes; first/last windows each had 1,000 samples. Receipt window stayed full at 6,320, source rows at end were zero, pending slots at end were zero, line capacity did not grow after warmup, and factor diagnostics retained at most 64 samples. RSS is process-only and may miss transient peaks.

## Deferred timing and scope

- Preserved failures: durable_decision_p99_latency_exceeded_100ms and durable_decision_max_latency_exceeded_500ms. Observed p99 upper bound was 156.10000000000002 ms against 100.0 ms; maximum was 2156.0 ms against 500.0 ms. Runner remains FAIL/exit 3.
- This is one local installed synthetic build-mode slice (20 targets, six factors), not full AC50-27b/formal acceptance, an all-101 soak, full group rebuild, disk-write-failure test, account acceptance, or actual trading evidence. No native-mode artifact was opened, so no native/build parity claim is made.
- SQLite was not queried or opened as a database. Its original file is identified below by size and streaming SHA-256 only.

## Original artifact SHA-256 index

| File | Bytes | SHA-256 |
|---|---:|---|
| completion.json | 175 | 5b9a446baf8f2c3664e6ccee6a4e1233da2a70b6ed607b0cb90d0458500a94c7 |
| execution-context.json | 521 | 858bd2b95f2849c922f345948f81c5fd482469310b221356c1876c0f566fc72b |
| launch.json | 1091 | d2e4a34e35fd233e9aaa2d34316ef55ae95c29b06dda754f6f6a2505aedc1690 |
| result.decisions.sqlite3 | 201748480 | 8fd5709662b81c725ba784b3ae5081e76059b0d726d52e749762e07c5fded0e8 |
| result.json | 37857 | 93cd29640a6169a830eea6ea45bc71655ec7828d92096987eb0ce79b6a0d0cbd |
| stderr.bin | 0 | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| stdout.bin | 86 | 09430f5278d2bafb9e1a97ff174d6c2579ab056e4e28bc8740e6ef0fc65a91e0 |

Checklist SHA-256: ca155f0802ebcb2d4de9e9f7550fbd6bdce9af7ffce31ef55bcaa04f88f7f446 (7615 bytes).

Machine-readable assessment: D:\source_code\backtrader\.codex-tmp\i50_27b_build_adjudication_20261027.json. The JSON contains all 36 pre-run module pins; result reports pre_post_match=true and pre/post pin arrays are identical.
