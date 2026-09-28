# Independent QA: r4 CTP generic queue fail-close candidate

Verdict: **PASS for the narrow isolated fake-only contract tested here.** This is not a writer-closure or authorization conclusion, and it does not accept the r4 candidate for production/SimNow execution.

## Frozen packet and replay identity

- Packet: `D:\temp\ac41-63-store-generic-queue-failclose-r4-compat-20260927`
- Packet manifest SHA-256: `6EBB6B381D371E429C54FBAF1D884E1FBABF254FDCECE7A0E6F035A1AB462FB6`
- Packet `SHA256SUMS.txt` SHA-256: `27B5C8232AD7A330B214616AD40AD53B2B20229F6F3A5E1BC0D62DBF68D36701`; all 534 listed entries verified with zero mismatch.
- Patch SHA-256: `37EA74FA86D600A5FFC47CBC9511C2215B10765EC791FA9DD6F65036EB867B00`
- Exact Store preimage A028: `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`
- Replayed Store target: `A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE`
- Iteration22 test: `30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D` → `64C1DDBC2A54322CEC9A0732C78760E684BA7A1E81DE14E4FF2D5AB5AC6833B3`
- Budget test: `F1C63AABB57D3C6B5F291C86083441E1CE196DA75CC4EA458841D1DCF022407D` → `7A77E0D9FE81230D44DB05F004D1299D997FA65B124ACA7CB228B3A024F2CE44`
- Added queue contract test was absent at base; replay target SHA-256 `75342D9D710BB52C7492C9C2BC71B1094984A27F976D38196D6433B6D182CD74`.

Strict `git -c core.autocrlf=false apply --check` and apply succeeded in a fresh QA copy. All four replayed paths match the frozen target hashes. Candidate `py_compile` and project-config Ruff both pass.

## Independent focused tests

All test runs used the exact replayed candidate module, an inert `bt_api_py` stub where a test imports its capability type, CTP SDK/native import tripwires, and a network guard allowing only local loopback needed by the asyncio harness. No CTP/provider imports, non-loopback network, credentials, private config, real SDK, native CTP runtime, or provider calls were used.

- R4 standalone contract: **12 passed**. Covers generic CTP submit/cancel and queue rejection for direct, gateway, suffixed `CTP___` gateway, forwarding, and btapi snapshot routes; checks zero API/writer descriptor lookups, preserves read-only CTP query, MDO local rejection, and BINANCE generic positive.
- Recovery-exit parameterization: **4 passed** across `market_data_only` true/false × managed adapter absent/present. The enqueue aborts/disarms before rejection; fakes observe no generic queue/native insert.
- Budget and sink lookup contracts: **3 passed**. Budget passthrough remains available on BINANCE; absent budget is omitted; CTP rejects before accessing the writer method.
- Original r3 generic contract: **11 passed, 1 intentionally deselected**. The deselected test asserted r3's rejected typed managed-cancel behavior, which r4 intentionally restores to the A028 contract.
- Managed-cancel/forwarding compatibility nodes: **10 passed**, covering legacy forwarding fail-close, projected submit/cancel, restart and recovered binding, projection failure, typed adapter cancel, full-order forwarding, and no retry through a direct provider path.

There were two superseded harness-only attempts: one overblocked Windows' `user32` timezone setup through a generic native-loader trap; another blocked asyncio's local loopback self-pipe. Neither ran product assertions to completion. The corrected import/network guard above passed. Final guard logs show only the inert SDK stub and, for asyncio tests, local `127.0.0.1` ephemeral loopback; no blocked provider import or non-loopback attempt.

## Compatibility and remaining limits

R4 preserves `_cancel_managed` byte-for-byte from A028; the parent independently compared its full source span. Generic CTP enqueue remains rejected, including the `CTP___suffix` route. Recovery-exit CTP paths disarm before that rejection. The two budget positives now use a non-CTP route, with a separate CTP zero-lookup negative. These resolve the r3 failure classes identified by the parent without restoring a generic CTP write exception.

The historical r3 broad main-tree run remains **13 failed / 2,724 passed / 43 skipped / 2 xfailed**; this QA does not erase that result. After r4 integration, the parent reported a current main-tree broad run of **2,740 passed / 43 skipped / 2 xfailed / 0 failed**; this QA did not independently rerun that broad suite. The author packet reports 445 passed / 1 skipped on its affected-module suite; that count was not independently repeated here.

Route classification uses snapshots, including `_sdk_exchanges` that may fall back to injected API `exchange_kwargs`; these are routing hints, not authorization. A stale non-CTP Store snapshot paired with a CTP-capable injected API remains a conditional generic sink residual. The guard applies to `_invoke_sdk_command` fallback only; the earlier typed managed `_execute_sdk_command` branch is not globally closed by this patch. Official writer dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`; posture remains `NO_WRITE / LIVE_NO_GO`.



