# Iteration 41 — Store `sdk_api=None` r1 main integration evidence

**Disposition:** `STORE_PUBLIC_GETTER_FAIL_CLOSE_LOCAL_ACCEPTED / NO_WRITE / LIVE_NO_GO`. This archive records a narrow Store API fail-close integration. It is not an SDK/provider trust review, authorization acceptance, or trading admission. The complete code has not received author SDK review.

## Integrated source identity

The main-tree source copies in [`main-tree/`](main-tree/) match the integrated targets:

- `backtrader/stores/btapistore.py`: SHA-256 `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`
- `tests/unit/stores/test_btapistore_sdk_api_none.py`: SHA-256 `477225A7668DD10FE26A532EF49AAF018FE8FF4187C5446C42AD7D97A2AFD7D6`
- `examples/ctp_options_simnow_mechanical_operator.py`: SHA-256 `549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F`
- Mechanical boundary test: SHA-256 `3F462651E3CC5F66B990B495BE2BFC50913BB60E11D17D28F02F215E67998783`

The getter returns `None` for CTP sessions, gateways, and forwarding routes; it preserves the original object for non-CTP direct routes. Store-owned read-only query behavior remains exercised with fake API data. The p4 mechanical source fails closed with `STORE_SDK_API_NOT_READY` when the CTP getter returns `None`, instead of calling the private lazy-connect fallback.

## Evidence

- Main guarded focus: [JUnit](main-tree/guarded-focus.junit.xml) reports 38 tests, 0 failures, 0 skips; [guard results](main-tree/guard-results.json) are `[]`. It covers the 9 Store getter tests, 2 mechanical-boundary tests, and 27 mechanical-cycle tests. No optional SDK/native import or network guard fired.
- Main Store/Runtime broad regression: [JUnit](main-tree/store-runtime-broad.junit.xml), [stdout log](main-tree/store-runtime-broad.log), and [exit code](main-tree/store-runtime-broad.exit) record 2,725 passed, 43 skipped, 2 xfailed, 0 failed (one existing pytest configuration warning). The JUnit represents xfails within its 45 skipped cases. This broad run is regression evidence only; it is not native, SDK, provider, account, or live-trading acceptance.
- [Ruff](main-tree/ruff-check.log) and [diff check](main-tree/diff-check.log) passed on the five target source/test files.
- The author’s isolated [r1+p4 composition manifest](author/composition/manifest.json) and guarded 12-test [JUnit](author/composition/fake-only-guarded.junit.xml)/[log](author/composition/fake-only-guarded.log) are preserved. The early broad run in `author/composition/superseded-invalid/` is explicitly excluded: its optional SDK import guard had not yet been added.
- Independent re-run and the real-`BtApiStore`-with-fake-API composition probe are in [the QA report](independent-qa/QA-REPORT.md), [JUnit](independent-qa/independent-final.junit.xml), [log](independent-qa/independent-final.log), and [exit code](independent-qa/independent-final.exit). Result: 14 passed with one existing pytest configuration warning. The integration probe observed `STORE_SDK_API_NOT_READY`, zero `_ensure_api_ready` calls, no fake connection, and zero fake writes.
- The earlier proxy implementation remains rejected: [r0 independent QA](../iteration41-store-sdk-api-guard-r0-independent-qa-2026-09-27/README.md) records same-process introspection retrieving the raw client from its proxy. R1 removes that proxy and directly returns `None`; it does not prevent same-process access to private `store._api` or `_ensure_api_ready`.

## Limits

This is a Python public-API convention and fail-close change, not an isolation boundary. Existing same-process code can still use private attributes or construct SDK objects independently. The broad test result does not prove SDK source identity, native behavior, credentials, account authorization, provider state, or production readiness. Default writes and live routes remain closed.

## Files

- [r1 author manifest](author/r1/manifest.json), [r1 patch](author/r1/sdk-api-none-r1.patch), and frozen candidate Store/test copies
- [p4 manifest](author/p4/manifest.json), [source patch](author/p4/source.patch), and [test patch](author/p4/tests.patch)
- [r0 rejected proxy report and probe](r0-proxy-reference/QA-REPORT.md)
- [archive manifest](archive-manifest.json) and [SHA-256 inventory](SHA256SUMS.txt)
