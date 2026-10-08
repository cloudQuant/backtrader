# M01 canonical reader integration R1 independent review

Decision: `GO_SOURCE_FAKE_ONLY / ACTUAL_ROOT_BLOCKED`.

## Exact reviewed pins

- Canonical transformed reader: `examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py`, 68,215 bytes, SHA-256 `5a8fd479c999279d9efde625cac1938d794201f04e1beaa6f3663b267d7a7ebc`.
- Canonical entry: `examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py`, 5,952 bytes, SHA-256 `e0613b66fa54d5ea155da263d1e901e8ada78adf7d83a7e1c8dc5430ea440d1e`.
- Fixed case runner: `examples/000_live_certification/okx_penetration/cases/M01/run.py`, 1,992 bytes, SHA-256 `d498e32fcb573781a3eec25eff4c7ba98bfe2c8d4d94f9e5a9b078ab4074641e`.
- Integration test: `tests/unit/scripts/test_iteration41_okx_m01_reader_lifecycle_integration_r1.py`, 9,809 bytes, SHA-256 `21d43a5e8d1c517c2ffaa147c96f58343fb188432d4fae47717a5b68b6ec040d`.
- Source map: `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09/source-map.json`, 2,877 bytes, SHA-256 `07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3`.
- Source index: same directory, `source-index.json`, 9,970 bytes, SHA-256 `8cd0360bb9519daf785412a6176091d2ca0ff4471e2bf65aba011aeec3444564`.
- Public source archive: same directory, `source.zip`, 151,736 bytes, SHA-256 `337d8f48eed1de8e7f880d6c8a24cf41e3707649cd0b0c3be87cc0b0948d39b3`.

## Independent checks

The source map contains 19 unique runtime rows. Each current worktree file matches the map and source-index byte count and SHA-256. The source-index canonical map digest recomputes to `2647a75e29a0ae54c09d5f5c3626a377a50e6d2d8dac38f76162660fe76979ba`. The public source ZIP has 26 unique safe relative members; every indexed member size and hash matches the archive, with no extra or missing entries.

The test confirms the new map has the same 19-row key set as the transformed reader's `SOURCE_MAP_RELATIVES`, and differs from the prior R2 map only for `current_reader.py`, `entry.py`, and `cases/M01/run.py`. The entry pins the transformed reader; the runner pins the new entry and unchanged package initializer. The test also verifies the exact old public R2 archive/map pins and historical `b350e0d0…` reader bytes, re-runs the frozen R2 transform to the R7-pinned `5a8fd479…` output, and drives that transformed reader through the V2 supervisor using fake Win32 leaves. The result remains `SOURCE_FAKE_ONLY` and the current canonical reader file remains unchanged.

Independent QA used CPython 3.11.5 at `C:\anaconda3\python.exe`, `-I -B`, plugin autoload disabled, `PYTHONPATH` removed, `-c NUL`, `-p no:asyncio`, `-p no:cacheprovider`, and fresh basetemp `.codex-tmp/m01-reader-integration-r1-independent-20261009-a`. Pytest ran `tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py` and `tests/unit/scripts/test_iteration41_okx_m01_reader_lifecycle_integration_r1.py`. Result: 16 passed in 0.90 seconds, exit 0, no warnings.

## Scope limits

This review and QA cover public source, the identified public source archive, and fake leaves. They do not execute `cases/M01/run.py` or `entry.main`, access private configuration or deployment material, run a real Win32 Job/process, or establish account/provider behavior or a M01 result.

For any actual Root lifecycle-gate use, the R7 composition condition remains necessary: Root must freshly load all five guarded modules from exact held source bytes, capture the complete module/class/function/global state before the gate or untrusted code, and verify it after the call. The R7 gate does not itself validate arbitrary computed globals that changed before entry; this integration test supplies no Root pre/post baseline evidence.
