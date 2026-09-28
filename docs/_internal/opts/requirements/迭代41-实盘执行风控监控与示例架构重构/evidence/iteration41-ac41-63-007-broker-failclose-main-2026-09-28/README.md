# AC41-63: 007 CTP broker-factory fail-close evidence

Status: parent-applied local working-tree integration with independent candidate QA and guarded main-checkout verification. This evidence is not a commit, release, writer-closure claim, or live-trading acceptance.

## Change

`examples/007_ctp/ctp_example_support.py:create_live_broker(store, config)` now raises the existing redacted `legacy_direct_execution_not_supported` error immediately. The helper does not inspect or invoke the supplied Store, config, or `BtApiBroker`. The module keeps the public `BtApiBroker` import as an explicit same-name re-export to satisfy Ruff without removing the symbol. The added fake-only test verifies those inputs are untouched.

Patch sequence:

1. [001-broker-fence.patch](patches/001-broker-fence.patch), SHA-256 `69E53657C4883E20A2D7B114FB477C55A6B9513157936FABD6FE80A59EAC659D`, frozen against the exact dirty-tree preimage recorded in the manifest.
2. [002-ruff-reexport.patch](patches/002-ruff-reexport.patch), SHA-256 `98E69582981CDA3530279A93D9341A8250096D302FF2E6B833FF29ED8804353A`, the one-line import alias follow-up.

Canonical final main source SHA-256: `9F0DFE02F156B820B1158A7E317C2EFCEEBD59301A141E242A30144BDBFC554E`.
New test SHA-256: `7A5B29774F42C791A4CBA56E3A68C2A92330E64021718673BCEFF5DCA1C0496A`.

## Verification

Independent isolated candidate QA replayed the frozen patch, checked normalized postimages, and passed **5 tests**, exit 0, with one existing Quandl deprecation warning. Its strict guard recorded zero provider/native import attempts or preloaded CTP modules, `.env` reads, `os.getenv` calls, or socket calls. Its receipt, raw output, and guard/config files are under `qa-independent/`.

The parent ran the integrated main-checkout focus with the copied r2 `sitecustomize` guard: **5 passed**, exit 0, with one existing `asyncio_default_fixture_loop_scope` pytest configuration warning. Main raw log SHA-256 `C39A3DEF407043B78A13785EE05D01C1CD484C571A0FEE503234548A245DE8D0`; JUnit SHA-256 `600A4B05ED6D8BD064F7E4A1F925A6850F95E5F98FF4D16B999C586F441405B1`; `main-run/46724.json` records empty `events` and `native_modules_loaded`. The parent also reports targeted Ruff and `git diff --check` passed. The exact `sitecustomize.py` guard used for this successful run is included at `main-run/sitecustomize.py`, SHA-256 `E9C96E4196A8AFF2D21377F7B557777C07066F6D16AC6E09672C07AA108DBFD9`.

Exact successful main command recorded by the parent:

```powershell
$env:PYTHONPATH='D:\temp\ac41-63-r2-root-guarded-store-20260927\guard;D:\source_code\backtrader'
$env:ITER41_GUARD_LOG_DIR='D:\temp\ac41-007-broker-main-20260928\guard-r3'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest -p no:rerunfailures -p no:hypothesispytest -p no:cacheprovider tests/unit/test_iteration41_007_live_broker_failclose.py tests/unit/test_ctp_example_support.py tests/unit/test_iteration41_legacy_ctp_support_inert_import.py -q --junitxml='D:\temp\ac41-007-broker-main-20260928\focused-r3-junit.xml'
```

An earlier main attempt used the overbroad QA `os.getenv` guard and failed at collection when unrelated `statsmodels → joblib → psutil` import read `PSUTIL_DEBUG`. That attempt is preserved as `main-run/invalid-qa-offline-guard-attempt.log` and its JUnit/exit sidecars. It is excluded from the test result and is not a source regression.

The final official collector JSON is [official-collector-final.json](inventory/official-collector-final.json), SHA-256 `D68D2E7A1E4700A93D1FED9565F72DAAE33C69D09A5BEE5A4EAF3431957FDF63`. Parent reports the ordered candidate IDs and locator lines are unchanged from the frozen inventory: 355 files scanned, 363 writer candidates, 97 dynamic candidates, and 460/460 verifier rows. This is inventory integrity evidence, not closure of those candidates.

## Residuals and route state

`add_live_feeds(cerebro, store, config)` remains a separate legacy caller-Store market-data/session route. It composes `BtApiFeed`; `BtApiFeed.start()` calls `store.start(data=self)`, registers the feed, may call `fetch_history(...)`, then subscribes (`backtrader/feeds/btapifeed.py:283-328`). This broker-helper patch does not close that path or prove provider/session behavior.

Other direct Store/Broker composition, arbitrary same-process callers, and account-wide writer paths remain outside this one-helper scope. No real provider, native SDK, network, credential, or order path was exercised. **Keep `NO_WRITE / LIVE_NO_GO`.** Do not claim writer closure, SimNow acceptance, or production acceptance.

## Evidence files

- `candidate/`: Git-normalized pre-alias candidate bytes, new fake test, original mixed-EOL diagnostic source, and unchanged legacy tests.
- `qa-independent/`: independent QA receipt, raw output, and strict offline guard/config.
- `main-run/`: final integrated source/test, parent main-run log/JUnit/exit, successful-run guard and event JSON, plus the excluded invalid harness attempt diagnostics.
- `inventory/`: final official collector JSON.
- `manifest.json`, `SHA256SUMS.txt`, and `SHA256SUMS.sha256`: provenance and integrity hashes.