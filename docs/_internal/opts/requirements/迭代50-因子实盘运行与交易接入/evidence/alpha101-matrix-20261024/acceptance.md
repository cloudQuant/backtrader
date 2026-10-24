# Alpha101 full live-cohort matrix evidence

The accepted synthetic integration matrix covers all 101 Alpha formulas at evaluation lengths T320, T640, and T1280. At every length, the six lanes are batch native runnext, batch native runonce, batch build runnext, batch build runonce, live native runnext, and live build runnext. The eighteen matrix segments all passed. Each JUnit file records one test, zero failures, zero errors, and zero skips. The aggregate records all 101 distinct IDs at each length, with no missing, unexpected, or duplicate IDs.

The harness checks production factor nodes and strategy-facing outputs against the independent Alpha101 reference, including values and reasons, and requires meaningful finite witnesses. The live lane uses the real BtApiFeed, LiveBarCohort, and ordinary Cerebro delivery path. This is local synthetic evidence; it does not establish provider or account acceptance.

The archive contains the exact final aggregate, starting source pin map, run metadata, memory decision, all eighteen result JSON files, JUnit XML files and bounded logs, plus the exact matrix runner, integration test, and live cohort harness. Tracked core dependencies are represented by their exact hashes in the source pin maps and are not duplicated in the archive. The only untracked pinned Python sources are:
- .codex-tmp/iteration50_alpha101_matrix_runner.py (matrix orchestration source)
- tests/integration/test_live_alpha101_matrix.py (integration test)
- tests/test_utils/alpha101_live_cohort_harness.py (fixture and live cohort harness)

The original run metadata records root-supplied dev HEAD 99f1b3d265ba5cfa9cddaffc6e3cee55ec25f65c, binding commit 1425e3401, and operators commit 99f1b3d26. The delivery-preparation HEAD was ac31ca500d609c0f81239dcdb8b29ce8a0bc28f3. These HEAD values differ; the matrix itself recorded 549 file-level source pins, and every pinned file matched the recorded start and end bytes and was rechecked byte-for-byte before packaging. This is a file-pin statement, not a same-HEAD claim.

The memory decision used a 1.5 safety factor and a 2 GiB system reserve; measured first-segment peak was 1122529280 bytes (1070.527 MiB), with safe concurrency set to 1. The accepted matrix ran its segments serially. Segment timings and peak RSS below are diagnostics only and are not a performance acceptance result.

| Evaluation length | Batch | Elapsed seconds | Peak RSS MiB |
|---:|:---|---:|---:|
| 1280 | promoted_20 | 1074.157 | 1070.527 |
| 1280 | a | 440.000 | 775.996 |
| 1280 | b | 1248.063 | 1051.488 |
| 1280 | c | 560.656 | 921.891 |
| 1280 | d | 818.437 | 923.422 |
| 1280 | e | 728.297 | 858.434 |
| 320 | promoted_20 | 395.515 | 600.559 |
| 320 | a | 180.218 | 459.711 |
| 320 | b | 444.187 | 591.613 |
| 320 | c | 228.500 | 529.219 |
| 320 | d | 329.375 | 536.945 |
| 320 | e | 242.375 | 481.242 |
| 640 | promoted_20 | 603.422 | 757.332 |
| 640 | a | 256.500 | 566.176 |
| 640 | b | 701.797 | 745.578 |
| 640 | c | 341.250 | 661.477 |
| 640 | d | 478.562 | 666.672 |
| 640 | e | 411.734 | 613.105 |

Aggregate hashes:
- aggregate.json: 7a1fe09bcd5c04fc055ca88f564a1c461c1c3301033cf1b59d30a28da01dcd0f
- source_pins_start.json: 81da9dcd56bb272eecb611763f1c209636a961b673c97c977f50aba73d53f607
- ZIP: b04a80fc3389b6fbfb87d5c16bec019e40ebbbdbfe09773c5dec00ddce4f158f (2206100 bytes)

The ZIP includes a compact diagnostic reconstruction for the earlier runpy-only aggregate. The original bytes and timestamp are unavailable because that output was overwritten by the correct direct-run aggregate. The reconstructed file is explicitly marked diagnostic-only and is not acceptance evidence; the direct-run aggregate above is the accepted result.

The archive includes SHA256SUMS.txt for each included payload file other than the checksum list itself.
