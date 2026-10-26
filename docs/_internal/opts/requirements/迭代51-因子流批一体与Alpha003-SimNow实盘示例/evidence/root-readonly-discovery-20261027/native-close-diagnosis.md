# I51 native-close diagnosis — 2026-10-27

**Finding: the installed client’s normal stop path waits for Join before Release and does not issue an explicit native shutdown/logout request on that path.** The observed 20-second receipts are consistent with that control flow. This establishes a source-level close-contract gap for the observed wait; it does not prove that vendor Join can never return independently.

## Source trace

In the installed public `bt_api_ctp/ctp/client.py`, nonblocking MD and trader startup install a Python Join observer (`client.py:3026` and `9041`). The observer calls native `api.Join()` (`2761-2774`, `8785-8797`); only after Join returns does its `finally` path release the retained API (`2783-2786`, `8807-8810`).

Normal stop calls `_stop_native_session`. When Join is active/claimed, both MD and trader detach callbacks with `api.RegisterSpi(None)` and return without calling `Release` (`3051-3151`, especially `3128-3143`; `10533-10632`, especially `10609-10624`). The stop receipt then polls the Join tracker and observer thread until timeout (`374-506`); it does not submit another native close operation. The shared Release helper refuses Release while Join is claimed or the API remains retained (`603-677`, especially `632-650`), and invokes `api.Release()` only after that guard permits it (`651`). Neither stop path calls `ReqUserLogout`.

The exact public 6.7.7 headers supplied for review describe `Release` as deleting the API object, `Join` as waiting for the interface thread to end, and `RegisterSpi` as registering callbacks: `ThostFtdcMdApi.h:95,103,129` and `ThostFtdcTraderApi.h:520,528,560`. Both headers expose `ReqUserLogout` (`MdApi.h:160`, `TraderApi.h:594`), but the installed stop path does not call it, and the header contract reviewed here does not establish it as a native interface-thread shutdown substitute. The [SimNow CTPIIMini API manual](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf) likewise defines Join as waiting for interface-thread termination and Release as API-instance deletion; it does not supply an alternative sequence that resolves this source ordering.

Root supplied the finite observation for its single read-only attempt: MD readiness timed out after 20 seconds; both generation-1 receipts report `native_released=false`, `join_required=true`, `join_completed=false`, `thread_alive=true`, `timed_out=true`, with the exact saved APIs and Join trackers still pending. This matches the source path above. I did not inspect or operate the retained host.

## Conclusion and boundary

The installed public SDK source shows no supported normal API alternative that both triggers native shutdown and respects its own prohibition on Release during a claimed Join. `ReqUserLogout` is an exposed session-level API, but these sources do not show it terminating Join; do not treat it as a proven fix. The current evidence therefore supports a contract gap to resolve against a vendor-supported shutdown order, not a manual Release, repeated stop, or invented cleanup action. Preserve the retained clients/APIs and their receipts while that contract is unresolved.

This is a static source diagnosis supplemented by Root’s supplied result. No tests/imports, new provider operations, private inputs, or live-host actions were used. It does not establish provider dispatch/response absence, account outcome, or final native shutdown.
