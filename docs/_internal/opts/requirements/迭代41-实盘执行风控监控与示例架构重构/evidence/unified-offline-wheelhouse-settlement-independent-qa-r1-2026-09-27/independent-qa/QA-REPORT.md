# Independent QA — unified offline wheelhouse / settlement probe R1

Disposition: **`FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED`**.

## Frozen input verification

Candidate: `D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1`.

- Candidate file manifest: SHA-256 `cc356f2238cf1d57d076e8a87152cb4e42d48d9f179ca12212238dcd0009f491`; independently checked all **150/150** declared files for size and SHA-256.
- Candidate archive: `unified-offline-wheelhouse-settlement-evidence-r1.zip`, SHA-256 `c140d4c3ac902d4cd5fe51320285467c15d9be2b58b98d11d8ddcb355aaf568b`; **151** ZIP entries (150 declared payload files plus the candidate manifest), no duplicate names, CRC passed, payload bytes matched the manifest.
- Requirements lock: SHA-256 `856971d73bec6b6951fa3c5bb88ee6fefe1e716ab21d3b9712ed251d2e2c1bcd`; 52 exact version/hash lines.
- Wheelhouse manifest: SHA-256 `1b89cc1096e4d52145faa404da8a47a56e2779ed1b6b54d59e01f27980cb9fdc`; all **52/52** local wheel files matched recorded size/SHA, metadata version, CRC and lock line.

## Independent offline install

Created a new disposable CPython 3.11.5 venv at `D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927\venv`; `include-system-site-packages = false`. The separate QA audit used only stdlib and did not import `bt_api_ctp`, `_ctp`, any provider, or private runtime config.

The hash-locked install used `--no-index --find-links <candidate wheelhouse> --require-hashes -r requirements-hashes.txt`. The pip report listed 52 distributions; every selected origin was a candidate-local `file:///D:/temp/.../wheelhouse/...` URL and every selected archive SHA matched the lock. Four coordinated root wheels (`bt_api_base`, `bt_api_ctp`, `bt_api_execution`, `bt_api_py`) were then reinstalled by exact local wheel path with `--no-index --no-deps --force-reinstall`, to establish PEP 610 direct URL provenance. Their `direct_url.json` URLs and archive hashes matched the selected local wheelhouse files.

The independent audit compared installed wheel RECORD rows, file sizes/hashes and payload bytes against all 52 wheels. It checked **13,147** installed RECORD rows with no errors. `pip check` returned `No broken requirements found.` The audit process had no `bt_api_ctp` or `_ctp` entries in `sys.modules`. An opaque CTP `.pyd` exists in the installed artifact, but it was not loaded or called.

## Version/source checks

- Final CTP wheel is uniquely named `bt_api_ctp-2.0.4+g4r2.settlement.probe.20260927-cp311-cp311-win_amd64.whl`, SHA-256 `857b06c914cfc4f58bc04a77f11b77ad5dc3c47dc2be4d9d18b8e2fc805b264d`. Both independent build copies and the selected wheel have the same SHA-256.
- The previous same-version collision is retained only as diagnostic evidence: original G4 bytes `00e0c0c56574f60013115ee6010e531f72a8c811780f27dfcba3249cdafb5384`; old settlement overlay bytes `76dadbce12b5ac469b5b791af65c9195fa848cc76fa9e762d7c17932bef45baf`. Neither artifact nor its old version/hash is in the final wheelhouse or lock.
- Clean `bt_api_base` checkout `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f` was clean at inspection. The wheel and source have **104/104** matching Python files byte-for-byte. This candidate did not perform a separate base-wheel A/B rebuild.
- The parent wheel's `core-reference` extra requires `bt_api_binance>=2.0.0`; no `bt_api_binance` wheel is in the lock. This is not a full `core-reference` extra wheelhouse. A passing `pip check` does not validate an unselected extra.

## Settlement evidence limits

The clean G4-r2 source lineage's `client.py` SHA is `C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF`; its settlement query method contains the native request-filter/readback arguments. The CTP settlement response row exposes `ConfirmDate`, not `TradingDay`. The candidate's fake helper compares `ConfirmDate` with the separate sealed query-source TradingDay. That equality is a candidate check, not independent proof that those two dates are interchangeable in live CTP semantics.

The settlement helper is not wired into `backtrader_runtime/ctp_simnow_native_readiness.py`; the current readiness result reports MD/TD readiness flags and does not consume settlement-specific source/callback evidence. Therefore this wheelhouse/install evidence does not establish settlement readiness or authorize a route. The report preserves the source distinction: the old missing-filter claim applied to dirty `D:\bt_api_py` lineage, while the clean G4-r2 source-a `client.py` already has filter readback.

## Boundary

No SDK/native import or call, CTP provider, account, private configuration, credentials, network operation, default pin or main production route was used or changed. The wheel install is offline packaging evidence only. The CTP artifact is a local CPython 3.11 Windows probe build, not a trusted release pin. Settlement evidence remains fake-only and unintegrated.

**Conclusion: `FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED`.**

Additional static check: the selected CTP wheel's `bt_api_ctp/ctp/client.py` SHA-256 is exactly the clean G4-r2 source value `c217be3e...14e6ff`; the packaged method at 8021–8051 supplies `request_filter_field` and `request_intent_filters`, while `_execute_query` calls `_read_native_query_filter_items` before dispatch. The selected wheel's settlement helper SHA matches the frozen overlay source-manifest entry and its code compares row `ConfirmDate` with `scope.trading_day`, optionally checking a row `TradingDay` only if present. This remains source/byte evidence; no SDK import occurred.

Reviewer harness note: two initial QA-only static assertions used the wrong field/function names and produced false failures; a third source-readback assertion used the wrong getter names. Each was corrected after direct frozen-manifest/source inspection; all original outputs and corrected passing reruns are retained under `logs/` and `evidence/`. These were QA harness errors, not candidate failures.

Reviewer harness note: initial assertions used an obsolete manifest key/function name, a non-normalized distribution key, and wrong getter names. They were corrected after direct frozen-source inspection, with all corrected checks passing. Initial stdout/exit logs are retained. The first static-audit JSON was overwritten before it was copied; its error output is retained in the initial log, but that JSON itself is not. These were reviewer-tool errors, not candidate failures.
