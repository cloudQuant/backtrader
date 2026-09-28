# BM58 two-client harness — independent QA (2026-09-27, r2)

## Disposition

**FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED.** This verifies a small local SQLite/WAL benchmark harness only. It is not actor-server, Store, runtime, CTP, provider, SDK, native API, account, credential, network, deployment, or production-capacity acceptance. The explicit 30-minute profile was not run.

## Frozen source and author packet

The author raw ZIP is SHA-256 `9363d92ecdda7527a12feb5e7357793458047067f137f336a795c3859a948272` (`testzip=None`). I independently checked the author evidence manifest SHA `9426567739623296a95b78cd7c288a38f96764d0c7f38e4e1a45d26e88ac5adb` and all 16 declared payloads. The main-tree harness, QA copy, and ZIP member have the same SHA `b1f02883d706c6d5449c5483a9a67fc32dae99f903c16fd2738e5e1b278759b1`. The main-tree focused test, QA copy, and ZIP member agree at `20db109b2525bf507d20277c8674f6459b64a1a4da9f3c5383a858ffc8b2fabb`.

**Erratum retained, author evidence unmodified:** the author summary `.md` records test hash `20db109b2525bf507d20277c8674f6459b64a1a4da9f3c5383a858ffcb8f2fabb`; the correct hash is `...ffc8b2fabb`. The frozen main test file, machine evidence manifest, and ZIP payload all agree on the correct value.

The independent focused suite passed **4/4** on CPython 3.11.5 (plugin autoload disabled). Static AST review found only standard-library imports and no SDK, native, Backtrader runtime, socket, HTTP, or request client imports. The output fields `provider_dispatches`, `native_api_calls`, and `network_calls` are constants in the harness; they are not OS-level instrumentation. No provider or network attempt is made by the reviewed source.

## Independent runs and conservation

| Run | Planned / accepted / completed | Attempts / duplicates | Lost / incomplete / outstanding | Peak / configured bound | Backpressure | Elapsed / extension | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Default smoke, 10/s × 2 s | 20 / 20 / 20 | 22 / 2 (expected 2) | 0 / 0 / 0 | 1 / 256 | 0 events | 1.925 s / 0 s | PASS |
| Pressure run A, 40/s × 1 s, fake latency 100 ms, bound 1 | 40 / 40 / 40 | 40 / 0 | 0 / 0 / 0 | 1 / 1 | 39 events, 8.375 s wait, 3,158 polls | 4.956 s / 3.831 s | PASS |
| Pressure run B, same settings | 40 / 40 / 40 | 40 / 0 | 0 / 0 / 0 | 1 / 1 | 39 events, 7.218 s wait, 3,104 polls | 4.675 s / 3.550 s | PASS |

For each run, raw SQLite state independently matches JSON: two client rows, all planned unique intents completed exactly once, `request_attempts = planned + duplicate attempts`, WAL mode, and zero outstanding. Fake completion calls equal completed intents. The pressure samples reconcile row-for-row and sum to each run's reported wait/poll counts. Run A and B are separate executions; their wait and elapsed totals vary with local process scheduling. Both show that the configured one-second input was accepted/completed over multiple seconds, so neither establishes 40/s sustained throughput. Both result files retain `FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED`.

**Timing reconciliation:** the earlier progress message's 8.375 s is pressure run A (`pressure-40x1-actual`); the first archive/report's 7.218 s is pressure run B (`pressure-40x1-final`). They are not contradictory measurements of one run. Revision r2 retains both raw run directories and the previous r1 packet/report/receipt; the author evidence was not changed. The initial run's result JSON, SQLite, and CSV are preserved; the compact console summary is derived from that result because the first invocation was not redirected to a separate shell log.

## Archive

The r2 independent raw ZIP includes the complete author raw packet, exact source/test copy, verification and audit scripts, full focused pytest output, raw SQLite/CSV/JSON and command/log records for both pressure runs and the default smoke, plus the prior r1 packet and r1 report/receipt/index. `archive-verification.json` records archive SHA, each member size/hash, and `testzip=None`.
