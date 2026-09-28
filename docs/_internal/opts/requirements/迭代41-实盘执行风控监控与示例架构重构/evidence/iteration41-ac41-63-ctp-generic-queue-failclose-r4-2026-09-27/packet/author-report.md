# AC41-63 Store generic CTP queue fail-close r4 author packet

Status: isolated candidate pending independent p3 review. This does not authorize CTP or live execution and does not claim writer closure. Active dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`; global posture remains `NO_WRITE / LIVE_NO_GO`.

## Why r4 follows r3

R3's exact-base broad Store/Runtime run had 13 failures (2724 passed, 43 skipped, 2 xfailed). Eight were caused by r3's new early rejection of typed managed CTP cancellation; one forwarding adapter assertion changed because the precheck ran before the established direct CTP legacy rejection; two budget kwargs tests exercised a private CTP sink passthrough contract; and two recovery-exit tests expected queue dispatch failure handling rather than generic CTP enqueue fail-close. R4 removes the new `_cancel_managed` precheck and restores that method byte-for-byte from the A028 preimage. It does not reopen CTP generic enqueue for recovery exits.

## R4 changes

- `_invoke_sdk_command` rejects generic CTP `submit` and `cancel` before looking up the API writer method.
- Generic CTP order and cancellation queues fail closed. Existing `market_data_only` local rejection behavior remains for ordinary submissions.
- `enqueue_order` reads `execution_role` before CTP denial. A recovery exit aborts/disarms before CTP rejection on both generic and managed-adapter-present early paths. It never uses `_ctp_execution_recovery_armed` as a generic CTP exception.
- `_cancel_managed` is copied byte-for-byte from A028; the typed managed cancel projection and existing positive tests remain intact.
- Two budget-capability tests use a `BINANCE` fake route; their kwargs assertions remain. A CTP sink negative asserts zero `async_make_order` lookups.
- The recovery test covers four fake combinations (`market_data_only` true/false × adapter absent/present). It traps the generic queue, checks zero queue calls and zero native inserts, and verifies disarm/reset before rejection.
- The original r3 12-case generic queue test (`3201896CBC984054BB8124CBBB1489A207DB349AE6CEB74CEB701DA08F21D29A`) is added as the fourth changed file. Its final cancellation case is adapted to assert typed adapter dispatch is reached, because r4 intentionally restores that path. It passes 12/12.

## Exact identities

Patch `37EA74FA86D600A5FFC47CBC9511C2215B10765EC791FA9DD6F65036EB867B00` targets Store `A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE` from A028 `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`. Test targets: iteration22 `64C1DDBC2A54322CEC9A0732C78760E684BA7A1E81DE14E4FF2D5AB5AC6833B3`, budget contract `7A77E0D9FE81230D44DB05F004D1299D997FA65B124ACA7CB228B3A024F2CE44`, and new queue contract `75342D9D710BB52C7492C9C2BC71B1094984A27F976D38196D6433B6D182CD74`. Full preimage/target sizes and hashes are in `manifest.json`.

## Verification

The candidate overlay module path is printed before collection. Seven affected Store modules plus the 12-case contract passed: 445 passed, 1 skipped. The only warning is the existing unknown pytest config option under `-p no:asyncio`. `py_compile` and project-config Ruff passed. A fresh exact-base `git -c core.autocrlf=false apply --check/apply` replay passed and all four target files matched byte-for-byte. Raw pytest/JUnit and the contract test receipt are included.

## Limits

The CTP classifier uses Store route/config snapshots. The SDK exchange snapshot can fall back to an injected API's `exchange_kwargs` at initialization; those are routing hints, not authorization. The `_invoke_sdk_command` guard covers only that generic fallback; `_execute_sdk_command`'s earlier typed managed branch is not closed. A stale non-CTP Store snapshot paired with an injected CTP-capable API remains a conditional generic-sink residual; independent r3 fake QA reproduced this case and r4 does not change that classifier. This patch does not prove every direct import, native call, or provider route closed. No real SDK/native import, provider, network, private config, credential, account, order, or cancel was used.
