# Iteration 10 SCN01 contract overlay and pre-I/O backend guard

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`; source parent before this round: `1fc36641f50f11b877815f41892c0fda7428997c`.

This round records the SCN01 normal-entry boundary and unsupported-service preflight. Binance service selection now refuses cases without the implemented service backend before strategy import, `.env` access, Host creation, or provider activity. OKX/SimNow `gateway_zmq` selection has the same pre-I/O refusal and does not fall back to direct transport. Existing direct-entry compatibility remains intact. The candidate code and focused regressions are the six exact paths below.

## Acceptance evidence

The accepted author-focused run passed eight tests covering unsupported-service refusal, the existing Binance optional-backend fail-closed path, and OKX/SimNow unsupported-transport preflight. This is source/local-synthetic entry evidence only. The accepted run was not repeated for delivery. It establishes no provider, account, venue, or new formal-case result.

The separately reviewed SCN01 99-cell identity/evidence overlay is `D:/bt_api_py/docs/迭代计划/迭代10-可选组件与可配置通信/SCN01-99案例源码合同映射-20261017-身份证据状态覆盖.md`, 196,955 bytes, SHA-256 `9b80beb6699c5e444c7feced08c331ce447238514edb496c8f2180dcf89e0d43`. Static checks found 99 unique cells and 199/199 strategy/config source pins matching. Its formal count remains 44/68; the overlay is source-contract mapping, not provider acceptance. It separates trade-write follow-up evidence, session-control lifecycle evidence, and account-admin post-state/restore evidence. C01/L02 normal ServiceHost evidence remains local synthetic only.

No real venue request, provider/account read, credential use, or external action occurred in this round. No accepted tests were rerun.

## Exact code and test scope

| Path | Bytes | SHA-256 |
|---|---:|---|
| `examples/live/000_live_certification/binance_penetration/certlib/__init__.py` | 2,869 | `b049c842ccdd852a0cd894936c6ea1c7500c46e95dce827653fd7d561e6fd100` |
| `examples/live/000_live_certification/binance_penetration/certlib/runner.py` | 13,109 | `79bdf02e9650d663cd22976e864feb5004638449e9109f6ef29a27ef675d2ea5` |
| `examples/live/000_live_certification/okx_penetration/certlib/runner.py` | 10,319 | `e6f5aec4efd707a93c507266dec94c0c0db57ae6d51c3d045c773125b34685ac` |
| `examples/live/000_live_certification/simnow_penetration/certlib/runner.py` | 13,224 | `a9ebf18f4e7842826434e44a478da22f77394b06f228ed5e07c7175a9f82b5ae` |
| `tests/unit/test_scn01_binance_service_backend.py` | 34,539 | `13561218314039236a4bbed31cb2c8447b41bddc5496ef6ce4036993a7d0acc4` |
| `tests/unit/test_scn01_unsupported_backend_preflight.py` | 3,770 | `bdf6bf22087a8477efe5c480ec5a6eee0a23e08aa8d737661cb52c2dc646eb3e` |

Index was empty before staging. Unrelated existing worktree changes remain outside this scope.
