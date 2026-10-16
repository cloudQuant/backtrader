# Iteration 10 SCN02 — 013 service/P5A write boundary

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`.

This focused test exercises the public `main()` entry in 013_1, 013_2, and
013_3 with `--live --backend service --allow-write`. Each entry must return
`BLOCKED/service_write_backend_unsupported` with
`write_grant_result=rejected_before_provider_io`, before case configuration,
SDK setup, or live handler dispatch. It proves the service observation facade
cannot be promoted into a P5A writer by a CLI flag.

This is a local entry-guard result only. It does not test or authorize direct
registered-SimNow writes, a P5A drill, a real provider/account, or a trade.
Existing per-case P5A admission requirements and research dispositions remain
unchanged; approved write acceptance is a separate venue acceptance item.

## Focused result

Command:

```text
C:/anaconda3/python.exe -m pytest -p no:asyncio -q tests/unit/test_scn02_013_p5a_service_write_guard.py
```

Result: **3 passed**, one existing `asyncio_default_fixture_loop_scope`
configuration warning, 21.26s, exit 0 on CPython 3.11.5. All three public
entry points returned the exact service-write refusal; the config/SDK/live
handler traps remained untouched and the configured path did not exist.
The test was run against Backtrader `dev` HEAD
`90dd225b6a431ece6bb71969281b2e91a49fee62`.

## Scope

- `tests/unit/test_scn02_013_p5a_service_write_guard.py`
- This record

Test pin: 1,957 bytes, SHA-256
`F4662296965C58ECBDC36FC46D410D094EEC8615948CB036DBFAEB479F08875E`.

No production source is changed. No provider, account, credential, or write
operation is invoked.
