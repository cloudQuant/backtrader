# G6-S TD settlement evidence consumer candidate

This is an isolated source candidate copied from the main Backtrader runtime.
It does not modify the main checkout, default runtime registration, SDK, or any
production pin.

## Contract

`backtrader_runtime/ctp_simnow_td_trading_readiness.py` now accepts a typed
`CtpSettlementEvidenceVerifier` injection. No verifier is installed by
default; omission or a different SDK source-manifest digest rejects before a
settlement query. A successful verifier must return the exact SDK
`CtpSettlementConfirmationEvidence` nominal type and its `as_public_dict()`
must accept the SDK's internal seal. The consumer rechecks the exact evidence
schema, digest, filters, request ID, account identity digests, generation,
trading day, `ConfirmDate`, terminal status, single-row count, and both UTC and
monotonic expiry. Only then may this candidate return
`td_trading_ready=True`. The result carries the evidence, callback-history,
and SDK-manifest digests.

The accepted source-manifest contract is the local G4-r2 SDK candidate
`settlement-source-manifest.json`, SHA-256
`DA9D20D35D0B5680267F1A95C5B7FFF54F25E9F57F0DFDA270B55EB7F251EBE9`. Its
settlement evidence source is
`src/bt_api_ctp/containers/ctp/ctp_native_query_certificate.py`, SHA-256
`53333798198177DD675F96478D8D7D2D0445E2E41459E54D4F021BDD32FA3282`.
The injected verifier must be the future code-owned adapter that actually
calls that builder against the current client's sealed query history. The
digest attribute and Python injection are not an OS trust boundary and do not
independently prove the verifier's implementation or installed SDK bytes.
The SDK history digest is based on its in-process sealed query source; this
consumer adds no durable callback inbox or cross-process signature.

The main consumer compares the SDK evidence to its independently validated
selected TD front pair, account, day, and current connection generation. The
SDK evidence itself does not contain front addresses. A CTP settlement row
with only native `ConfirmDate` and no `TradingDay` is supported when the date
matches the current day; the fake test exercises that shape.

## Verification

Run from this candidate root with Python 3.11.5:

```powershell
$env:PYTHONPATH='D:\temp\iteration41-g6s-main-td-settlement-candidate-20260927'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest --noconftest tests\unit\runtime\test_ctp_simnow_td_trading_readiness.py -q --tb=short
```

The tests use only fake client/evidence objects and a stubbed connector.
They make no native, provider, network, or credential calls. The SDK candidate
has not completed independent QA. This consumer candidate is not G6-S
acceptance, not an installed-wheel test, and does not open a default route.
