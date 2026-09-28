# Iteration 41 Store sdk_api getter-only guard r0 — independent QA

## Disposition

**NO_MERGE as a security or write-authorization boundary.** The frozen getter focus passes with fake objects, but Python same-process reflection recovers the original raw API from the view's private slots descriptor and from `object.__getattribute__`. The probe then calls a fake `submit_order` and observes its in-memory counter. This is a Python object-model demonstration only; no real SDK, native module, provider, account, private configuration, network, or live write was used.

The ordinary getter hides underscore/dunder attributes, but the Store still has existing same-process access paths through `store._api` and `store._ensure_api_ready()`. The mechanical example also falls back to `_ensure_api_ready()` when `sdk_api is None`. The four allowlisted methods match the example's method calls; this review found no break to those intended calls. This candidate is not a process/security isolation boundary.

## Frozen input

- Author freeze: `D:\temp\iteration41-store-sdk-api-guard-only-20260927\freeze-r0`
- Manifest SHA-256: `68E78410E35C41C02843CE44D67D825E9AFA6E42566840E56565A3883323E91C`
- Patch SHA-256: `687AA34EEE0A94ED042ED5447883A11DA332338750DD9B6772221DB9AF4A5709`
- Candidate Store source SHA-256: `16EFA561A56465B1BD8165318F705EEA240A7A6D2E97CDE3B68286A41A778575`
- Added focus test SHA-256: `9643D7659E7B95E60560BB3990A13079233F5DCBA941A36AB0B73DD885449E6E`
- Source preimage SHA-256: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`
- Existing Store-test preimage SHA-256: `F7E1FA01AA383367F518C61A0AE30285DB2C8EEFF22B9CF75BA0E1C3D774F853`
- Patch `git apply --check` on the declared preimage: exit 0.

## Independent replay

The focused suite was run from the isolated copied candidate using CPython 3.11, `--noconftest -p no:asyncio`, with an import guard that rejects `bt_api_py`, `bt_api_ctp`, and `_ctp`.

Result: **5 passed, 0 failed**, with one existing pytest configuration warning (`asyncio_default_fixture_loop_scope`). JUnit SHA-256: `5BC54F47CB28E622FD001389EFBD478AFE119ABB1FA264ABFC17B98F89416881`.

The candidate cases cover the four allowed methods, ordinary attribute denial, CTP/gateway/forwarding/no-client handling, non-CTP identity compatibility, and Store-internal read-only metadata query. Two exploratory attempts to call managed `_ensure_api_ready()` without an injected client were blocked at the `bt_api_py` import before any SDK module loaded. A final unmanaged-CTP fake-factory probe verified the existing private fallback can return its raw fake API without importing the SDK.

Probe JSON SHA-256: `2F9E317738AC5BACE16CFD8AF9723AEDBD46A1B24B3CB0B972C35B57291AF974`.

See the [independent QA report](independent-qa/QA-REPORT.md), [QA manifest](independent-qa/independent-qa-manifest.json), [QA SHA list](independent-qa/SHA256SUMS.txt), [raw JUnit](independent-qa/focused.junit.xml), [introspection result](independent-qa/introspection-probe.json), [frozen patch](frozen-inputs/sdk-api-guard-r0.patch), and [frozen candidate source](frozen-inputs/btapistore.py).
