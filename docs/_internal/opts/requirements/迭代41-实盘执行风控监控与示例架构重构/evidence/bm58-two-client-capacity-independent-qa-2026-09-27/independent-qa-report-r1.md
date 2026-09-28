# BM58 two-client harness — independent QA (2026-09-27)

## Disposition

**FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED.** This verifies a small local SQLite/WAL benchmark harness only. It is not actor-server, Store, runtime, CTP, provider, SDK, native API, account, credential, network, deployment, or production-capacity acceptance. The explicit 30-minute profile was not run.

## Frozen source and author packet

The author raw ZIP is SHA-256 `9363d92ecdda7527a12feb5e7357793458047067f137f336a795c3859a948272` (`testzip=None`). I independently checked the author evidence manifest SHA `9426567739623296a95b78cd7c288a38f96764d0c7f38e4e1a45d26e88ac5adb` and all 16 declared payloads. The main-tree harness, QA copy, and ZIP member have the same SHA `b1f02883d706c6d5449c5483a9a67fc32dae99f903c16fd2738e5e1b278759b1`. The main-tree focused test, QA copy, and ZIP member agree at `20db109b2525bf507d20277c8674f6459b64a1a4da9f3c5383a858ffc8b2fabb`.

**Erratum retained, author evidence unmodified:** the author summary `.md` records test hash `20db109b2525bf507d20277c8674f6459b64a1a4da9f3c5383a858ffcb8f2fabb`; the correct hash is `...ffc8b2fabb`. The frozen main test file, machine evidence manifest, and ZIP payload all agree on the correct value.

The independent focused suite passed **4/4** on CPython 3.11.5 (plugin autoload disabled). Static AST review found only standard-library imports and no SDK, native, Backtrader runtime, socket, HTTP, or request client imports. The output fields `provider_dispatches`, `native_api_calls`, and `network_calls` are constants in the harness; they are not OS-level instrumentation. No provider or network attempt is made by the reviewed source.

## Independent runs and conservation

| Run | Planned / accepted / completed | Attempts / duplicates | Lost / incomplete / outstanding | Peak / configured bound | Backpressure | Result |
|---|---:|---:|---:|---:|---:|---|
| Default smoke, 10/s × 2 s | 20 / 20 / 20 | 22 / 2 (expected 2) | 0 / 0 / 0 | 1 / 256 | 0 events | PASS |
| Custom pressure, 40/s × 1 s, fake latency 100 ms, bound 1 | 40 / 40 / 40 | 40 / 0 | 0 / 0 / 0 | 1 / 1 | 39 events, 7.218 s aggregate wait, 3,104 polls | PASS |

For both runs, the raw SQLite state independently matches JSON: two client rows, all planned unique intents completed exactly once, `request_attempts = planned + duplicate attempts`, WAL mode, and zero outstanding. Fake completion calls equal completed intents. Pressure samples reconcile row-for-row and sum to reported wait/poll counts. The pressure run needed 4.675 seconds actual elapsed for a 1-second planned input window, with a 3.55-second extension beyond the planned end; this documents the harness's backpressure and drain behavior, not a 40/s throughput guarantee. Both result files retain `FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED`.

## Archive

The independent raw ZIP includes the complete author raw packet, the exact source/test copy, verification and audit scripts, full pytest output, and raw SQLite/CSV/JSON plus command logs for the independent default smoke and pressure run. `archive-verification.json` records archive SHA, each member size/hash, and `testzip=None`.
