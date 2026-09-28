# AC41-63 013_1/013_2 legacy CTP support R4 — main integration

**Disposition:** `LOCAL_INERT_IMPORT_AND_HELPER_FAILCLOSE_ONLY / NO_WRITE / LIVE_NO_GO`. This is a narrow legacy helper boundary change. It does not establish writer closure, CTP/SimNow acceptance, account isolation, or permission to trade.

R4 preserves the R2 inert-import change and adds fail-close guards to the explicitly callable dotenv loader and the retired SimNow credential/route, Store, Broker, Feed, and Cerebro timeout helpers. The candidate patch is SHA-256 `FE67BF7D08004B4D36A0AF6FF461B49C0DE39F96490DAEA195234CE475DFE8C7`; its three postimage files match the integrated main tree.

## Main-tree verification

The safe guarded focus passed **32 tests with 1 test deselected**. The deselected test, `test_yaml_configs_match_strategy_defaults_and_runners`, is the only test in the earlier 33-test run that opened two untracked 013 `config.yaml` files through the generic config loader. The earlier 33-test result is marked **INVALID** and is not used as acceptance evidence. Its log hash is retained in `independent-qa/invalid-run-record/INVALID-33-focus.md`; the raw invalid-run log and JUnit are deliberately omitted from this archive.

The safe focus JUnit SHA-256 is `778FAD9EA2EF4C317D97E39043711B7BE375BA7B5401B6B1997DC07871488869`; the guarded sidecar SHA-256 is `407D0472E0E545089725F1E19305A0EBFA3C8A5F9B8C77C671E26FFEECDF030A` and contains an empty event list. Independent candidate replay passed the single guarded helper test. Ruff is clean for the persistent test; the two support modules retain only the four previously documented `SIM112` alias findings.

## Inventory and checklist

The R4 full collector inventory is SHA-256 `A959A3BC6284232EA90191F13ADC71A6931F5DFCBA6DB16E7AC72B1476B9D142`, with stdout SHA-256 `E8E8831CB3D456223B320A174B46EABC891F17BBD38EB843856A238831D25E2E`. The collector reports the same 460 IDs and order, 355 files, 363 writer candidates, and 97 dynamic candidates; only four line locators move from 491 to 495. The official verifier passes 460/460 with every row still `REVIEW_REQUIRED`; six historical tombstones remain. Scanner-contract JUnit reports 15/15 passing.

The tracked writer disposition checklist is intentionally unchanged at SHA-256 `B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426`. Its historical line 492 locator is preserved because the dispositions did not change; the refreshed source inventory records the shifted locations separately.

## Limits

The independent QA marked the initial 33-test output invalid because the test loaded untracked configuration files. The files' contents were not displayed or reviewed in the QA report or this archive. The archive stores only the invalid run's SHA-256 and sanitized reason. Generic `load_config` and `load_json_config` remain available for caller-selected backtest configuration files.

No real CTP SDK/native runtime, credentials, provider, network, account, order, or cancel was used. Candidate and main guarded runs are local fake/source-only evidence. See the [inventory rebaseline](inventory/rebaseline.md) and [independent QA report](independent-qa/report.md) for detailed scope and hashes. The [payload manifest](payload-manifest.json) lists and hashes archived files.