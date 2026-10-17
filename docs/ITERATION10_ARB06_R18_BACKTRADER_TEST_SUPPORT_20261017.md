# ARB06 R18 Backtrader execution support

This packet preserves the exact Backtrader-side test module and the separate seed fixture used by the R18 local synthetic run. The archived test copy is stored outside `pytest.ini`'s `testpaths = tests`; it is not a test-suite addition and must not be run from this archive path. The canonical, untracked `tests/integration/test_arb06_group_roll_exit_cerebro.py` is a different 84,305-byte source (`e090e6675c7c97c1b539291b795ccceb03f9fa934d4b8c39933b591012fb30c09`) and was not the R18 executed test.

## Exact Backtrader-side inputs

| Stored path | Bytes | SHA-256 | R18 role |
| --- | ---: | --- | --- |
| `test_support/arb06_r18_bt_support/executed/tests/integration/test_arb06_group_roll_exit_cerebro_start_diagnostic.py` | 84,327 | `040e036e3166e0a07a31ebc434b24639bd6dcbff5aad3625aba4f99804e999d4` | Exact test source pinned by the R18 spec; its bytes originated in the R17 flat-account-path overlay. |
| `test_support/arb06_r18_bt_support/seed/test_arb03_dim05_group_partial_fill_service.py` | 97,160 | `2f06291dbed35bc56f54d6e502c001fd3316f9408cf4a0fab615acaff03a033e` | Separate seed source loaded by `test_arb06_cerebro_account_monitor` through `BT_API_ARB06_PARTIAL_GROUP_FIXTURE`. |

The seed file above is distinct from the SDK test-support file with the same basename. The SDK copy is the R9 DIM05 helper (101,321 bytes, `d9e516f3b8cbc3cdde4f7e477c3526109603ff0c3a1b01f58be2df9086787887`); it serves the test's `_DIM05_SOURCE_FILENAME` import and must remain at the SDK support root.

## SDK dependency binding

The R18 run pinned SDK HEAD `33bdcb17c57d8e16c82a53e691ae09d2df820d9e` and Backtrader HEAD `6b25ee94ffec14cfad4b511eb6370eba38521c10`. The accepted SDK roll-exit mount fix is committed at `122fe59f8459e5f1182d492bb1da9a38f058f127`; the four byte-exact test-support files are committed at `4ce27fba10a3422683bc4cfd9e364443f422d07a` under `test_support/arb06_r18_sdk_support/`:

- `integration/_dim05_roll_exit_risk_host_fixture_diagnostic.py`: 38,220 bytes, `ec2eddf64ce3f17db39e24e4ab2f8cd1d8dadf8cf624d6fcab087ce269a20a94`.
- `integration/test_arb03_dim05_group_partial_fill_service.py`: 101,321 bytes, `d9e516f3b8cbc3cdde4f7e477c3526109603ff0c3a1b01f58be2df9086787887`.
- `integration/test_service_execution_group_local_process.py`: 61,209 bytes, `b9f60ce8cf29dcdd798672f4ad501abe6dc2346c7ffedf327376c83d90cd574b`.
- `unit/_service_group_provider_fixtures.py`: 9,484 bytes, `9bcf021649104243a2b16a93ef159ceca8cacce6ffad9c22afd94eed4ee3b1e2`.

For a separately authorized reproduction, materialize the archived test bytes at the focused overlay's `tests/integration/test_arb06_group_roll_exit_cerebro_start_diagnostic.py` path, set `BT_API_PY_TESTS_ROOT` to the SDK checkout's `test_support/arb06_r18_sdk_support` directory, and set `BT_API_ARB06_PARTIAL_GROUP_FIXTURE` to this packet's `seed/test_arb03_dim05_group_partial_fill_service.py`. Preserve the remaining source pins and fixed source roots from the R18 spec; use a fresh output directory. This is a path recipe only; no run was performed to create this packet.

## R18 evidence boundary

The exact selector was `tests/integration/test_arb06_group_roll_exit_cerebro_start_diagnostic.py::test_arb06_two_strategy_cerebro_roll_exit_preserves_peer_account_allocation`. The referenced run used `D:/temp/arb06-group-roll-exit-cerebro-abe0-4f3-fixed-r18-query-diagnostic-20261017/host-spec-r18.json` (SHA-256 `6e9dd1724df7571ac097b21221b647fd1d35a62461e02e9dfeb45232537323a0`, 900 source pins) and passed once in 19.60 seconds with three known warnings. `host-output-r18/result.json` is 768 bytes, SHA-256 `e0f2a577a7bee049b777cf28ada6e1a845edfd9e1766a94d48fb42da382d026a`; it records `source_count=900`, unchanged sources, and unchanged SDK/Backtrader HEADs. `stdout.log` is 1,770 bytes, SHA-256 `c5d88e8d4285bb4f93e3647594d21b4e332aaefa374a81298c0305546582f954`. `startup-diagnostic.json` is 605 bytes, SHA-256 `652ee57dac0f016bc586ba528dd9dc12b2f8f4bcab1a6ba6e645233479f948e9`; its cleanup projection reports all hosts closed and joined with no cleanup errors. The run observed one Risk CLOSE provider call, zero remaining source-strategy closable exposure, and the peer strategy's `0.75` allocation preserved.

The durable aggregate group snapshot remained `PAIRED` at revision 18. This does not establish aggregate group closure, real-venue behavior, or formal ARB06 acceptance. The R17 intermittent initial-query `UNKNOWN` remains unexplained; R18 did not resolve that failure. The executed test uses the diagnostic Risk fixture preserved in the SDK support commit, not the distinct canonical fixture. No tests or Hosts were run while creating this packet.