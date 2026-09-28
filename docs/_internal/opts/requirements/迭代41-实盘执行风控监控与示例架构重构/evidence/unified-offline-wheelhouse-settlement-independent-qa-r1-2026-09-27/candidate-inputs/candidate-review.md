# Unified parent, execution, base and CTP settlement wheelhouse — offline candidate

**Disposition: `FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED`.** This is disposable Windows CPython 3.11 packaging evidence. It does not change the main repository, default pins, runtime route, credentials, or operator configuration.

## What was built and installed

The local hash lock contains 52 wheels: `bt_api_py` parent, `bt_api_execution`, `bt_api_base`, the CTP settlement probe wheel, and 48 dependency wheels. A fresh CPython 3.11.5 venv installed all 52 with `PIP_NO_INDEX=1`, `--no-index --require-hashes`, and candidate-local `file://` inputs. The four root wheels were then reinstalled by exact local path for PEP 610 provenance. `pip check` reported no broken requirements. The static wheel/lock audit found 0 errors. Installed RECORD audit checked 13,147 rows with 0 errors; all four PEP 610 archive hashes equal the local wheel SHA-256 values. Neither `bt_api_ctp` nor `_ctp` appeared in the audit process `sys.modules`. The CTP wheel contains an opaque CPython 3.11 Windows `.pyd` and vendor DLL payload; none was imported, loaded, or called.

The CTP wheel was built twice from separate copies with local build isolation disabled, package indexes disabled, and `/Brepro`. Both builds produced byte-identical bytes:

- `bt_api_ctp-2.0.4+g4r2.settlement.probe.20260927-cp311-cp311-win_amd64.whl`
- SHA-256 `857B06C914CFC4F58BC04A77F11B77AD5DC3C47DC2BE4D9D18B8E2FC805B264D`

The parent and execution wheels are the independently frozen dual-build artifacts from the V23/R4/R3r3 probe. The selected `bt_api_base 0.15.4` wheel matched all 104 packaged Python files from a clean detached source checkout at `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f`; this candidate did not independently rebuild the base wheel twice.

## CTP source lineage and version identity

The clean G4 source-a `client.py` already contains settlement request-filter readback: `query_settlement_confirmation_result` at lines 8021–8051 supplies `request_filter_field` and `request_intent_filters` at 8049–8050; `_execute_query` at 7491–7547 reads native filter getters before sending. The source SHA-256 is `C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF`. The earlier missing-filter finding is confined to the separate dirty checkout `D:\bt_api_py` (`d3674e19` lineage), not this clean G4 source-a.

Against clean G4 source-a, the frozen settlement overlay changes these source files:

- `ctp_native_query_certificate.py`: `53333798198177DD675F96478D8D7D2D0445E2E41459E54D4F021BDD32FA3282`.
- `bt_api_ctp/__init__.py`: `246F5963130219D87C7773637C840B2B6FF5B99CE97DD2C0C1CEF670197DE505`.
- Adds fake settlement tests: `D8CE90248ACBF87EE8E05525E4102EB9D917AC7E13E42D2FEB2D0C3BC11B4E65`.

The **only non-frozen source change** for this wheel build is a `pyproject.toml` metadata version edit from `2.0.4+g4r2.probe.20260927` (base SHA `3D05CAC55229F870ACAE5D686BE71410A6A264445FD4CE8F1ADE413FE1C83951`) to the unique `2.0.4+g4r2.settlement.probe.20260927` (overlay SHA `CBD398F0F660C146F7C211E3906AC61F71FE092E02E9C84E4BA055823A329DF3`). The full 367-file pre-build input hash list is recorded in `ctp-source-diff.json` and tied to the frozen G4 and settlement manifests.

A previous overlay build accidentally retained the G4 probe version while changing wheel contents. That identity collision is preserved under `build-evidence/ctp-build/version-collision/` only: original G4 wheel SHA `00E0C0C56574F60013115EE6010E531F72A8C811780F27DFCBA3249CDAFB5384`; overlay A/B SHA `76DADBCE12B5AC469B5B791AF65C9195FA848CC76FA9E762D7C17932BEF45BAF`. Those artifacts are not in the wheelhouse or lock. The installed candidate uses the distinct version and wheel filename above.

## Acceptance limits and remaining blockers

The clean G4 source-a `client.py` filter contract is already present at lines 8021–8051: `_execute_query` at 7491–7547 reads the native request getters before send, and the settlement method supplies `request_filter_field` plus `request_intent_filters` at 8049–8050. Its `verify_settlement_confirmation` at 8062–86 checks completion/generation/account and accepts either row `TradingDay` or `ConfirmDate` equal to the expected day; lines 8108–15 then mark settlement readback verified and set `_ready=True`. The separate runtime native-readiness adapter at `backtrader_runtime/ctp_simnow_native_readiness.py:607–615` returns MD/TD readiness flags only. The frozen settlement source tests passed 48 fake-only tests. They do not establish server settlement, native source authenticity, live trading readiness, or authorization. The native CTP settlement-confirmation struct carries `ConfirmDate` but no `TradingDay`; the SDK session TradingDay is a separate sealed query-source fact. Callback history digest evidence is in-process evidence, not durable provider proof. Main readiness does not consume this settlement-specific source/callback evidence builder and presently trusts the SDK-promoted readiness result; the builder was not wired into readiness. The helper overlay cannot prove that `ConfirmDate` is the `TradingDay` or provide durable provider proof. The official configured 7x24 pair therefore remains exact-pair and zero-write whenever current settlement cannot be proved with exact native provenance; there is no time- or set-based fallback. G4/G6-S/G7-S and the default route remain closed.

The installed parent metadata declares broad lower-bound dependencies; this candidate's hash lock pins the selected closure only. The parent's optional `core-reference` extra also requires `bt_api_binance`, which is absent, so this is not a complete parent-extra wheelhouse. The CTP artifact is a local probe version for CPython 3.11 Windows x64, not a production pin. The main repo, protected config, and default pin were not edited. No credentials, native provider calls, or network access were used.

## Evidence files

See `candidate-receipt.json`, `wheelhouse-manifest.json`, `requirements-hashes.txt`, `wheelhouse-static-audit.json`, `install-evidence.json`, `installed-record-audit.json`, `pip-check.log`, `ctp-source-diff.json`, and `build-evidence/` for machine-readable inputs, hashes, build records, and the preserved version-collision diagnosis. An initial copied audit-script run used the prior candidate URL prefix and reported four PEP 610 path false positives; the original output is retained as `installed-record-audit-initial-path-check.*`. Updating only that expected path produced the recorded successful 13,147-row audit; archive hashes and PEP 610 wheel hashes were unchanged.

