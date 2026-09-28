# `_ensure_api_ready()` lazy-connect audit

Date: 2026-09-27  
Verdict: **`NO_MERGE_PATCH / BLOCKED_BY_SHARED_I22_LIFECYCLE`**

## Finding

The Store's public `sdk_api` property returns `None` for CTP, gateway, and forwarding routes, but that does not stop lazy connection. On a cold fake-backed Store, `get_balance(force=True)`, `get_symbol_info()`, and `start()` reach `_ensure_api_ready()` and call fake `connect()`. The CTP gateway and forwarding `start()` paths do the same. The fake path records zero order/cancel writes.

A CTP deny in shared `start()` or `_ensure_api_ready()` would also block the current Store-owned typed read-only lifecycle used by I22 and the bounded metadata-probe tests. An exception for that in-process probe still permits Store-owned native startup in the same process, so it does not resolve the lifecycle containment issue. No patch was created.

## I22 dependency and impact

The [013_3 runner](../../../../../../../examples/013_3_sa_midfreq_simnow/run.py) builds the route as `provider="btapi"`, `backend="direct"`, with CTP `exchange_kwargs` and `market_data_only=True`. Its API diagnostic calls `store.start()` before CTP snapshots; its later run path also calls `store.start()` before read-only verification and query helpers.

`run_bounded_read_only_metadata_probe()` requires SDK mode and a Store-owned client, calls `self.start()`, then reads typed instrument and funding contracts through the same `_ensure_api_ready()` path. The [I21 test file](../../../../../../../tests/unit/stores/test_btapistore_iteration21.py) has 14 bounded-probe test functions, including the owned-client lifecycle, fail-closed results, timeout, and shutdown cases. These tests were inspected, not run.

The [013_3 README](../../../../../../../examples/013_3_sa_midfreq_simnow/README.md) still says ordinary CTP native preflight is fail-closed pending a bounded Windows Job supervisor and independent acceptance. The source/test dependency does not establish a currently accepted real CTP route; status remains `NO_WRITE / LIVE_NO_GO`.

## Fake-only evidence

The [probe](probe.py) verifies the Store source SHA-256 before import, imports the repository source, blocks optional SDK/native imports and socket connection, then injects inert fake clients. The [JSON output](fake-callpath-repro.json) records:

- `get_balance(force=True)`, `get_symbol_info()`, direct `start()`, gateway `start()`, forwarding `start()`, and an example-shaped `btapi`/direct CTP flow all reached fake connection/query methods.
- Public `sdk_api` was `None` on each CTP/gateway/forwarding case.
- Optional import guard: `[]`; network guard: `[]`; fake order/cancel writes: `0`.

The [guard and test status log](guard-and-test-status.log) records that no pytest or broad Store/Runtime suite was run. Default `api=None` vendor construction and actual native/provider behavior were statically traced only; this archive contains no copied source tree or private config.

See [manifest](manifest.json) and [SHA-256 inventory](SHA256SUMS.txt) for frozen hashes. The audit added only this evidence directory; it did not edit shared evidence README or Store source.