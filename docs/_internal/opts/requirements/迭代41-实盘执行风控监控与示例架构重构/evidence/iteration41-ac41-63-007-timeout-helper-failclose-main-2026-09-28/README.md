# AC41-63: 007 timeout-helper fail-close

**Disposition: LOCAL_OFFLINE_ONLY / NO_WRITE / LIVE_NO_GO.** This archive records the integrated fail-close for the retired `examples/007_ctp/ctp_example_support.py::run_cerebro_with_timeout` helper. It covers only that helper entry point.

## Change and frozen identities

- Frozen preimage source SHA-256: `1D80D22C431068D991955093C2778AC98F39A6BC36A90F6F427FA8665AA67B3B`.
- Integrated postimage source exact-byte SHA-256: `37536B9598E3EE2414DE2AF787EA1E15C8C52E42558E9679107DB4F3F34C273A`.
- Postimage source Git/LF-normalized SHA-256: `DA9636D5BF6E0194ED279BC18B8A27E07D018DA905FEA5487AC87A7C5BE81A78`.
- Patch SHA-256: `99AD01EC1433CCCF3E9D0ACA9764E630F31E53C4F1C7D156D0FBCFA39677157D`.
- Persistent focused test SHA-256: `C5F88209C110CABB57F71003CFF9B56C0DA4D54DB43B3675ECB7414840DE5EF3`.
- Independent QA receipt SHA-256: `0BE69E08F8D99139B793D50B992A0443C66974547B6BE510C29F5BD161DC5969`.

The helper now raises `legacy_direct_execution_not_supported` before inspecting the supplied Cerebro or timeout, constructing a timer, or calling `Cerebro.run()`. The public helper name and `threading` module attribute remain available. The exact preimage, postimage, patch, and persistent test are archived under [preimage](preimage/ctp_example_support.py), [postimage](postimage/ctp_example_support.py), [patch](patch/iteration41-007-timeout-helper.patch), and [tests](tests/test_iteration41_007_live_timeout_failclose.py).

## Fake-only baseline repro and independent QA

The [baseline probe](baseline/fake_probe.py) loads only the frozen support-module source with fake Cerebro and Timer collaborators. It demonstrates the preimage calling fake `run()` once and constructing/starting/cancelling the fake timer; the integrated candidate raises the retired-entrypoint error with zero fake Cerebro calls, zero timer calls, no `bt_api_py` import, and no socket/network attempts. Captured output and parsed counts are in [probe output](baseline/fake-probe-output.txt) and [probe result](baseline/fake-probe-result.json). The [independent QA receipt](qa/independent-qa-receipt.md) reports separate `core.autocrlf=true` Git replay and byte identity checks, Ruff pass, and its fake-only probe. Its custom 007 scope inventory before/after is also included.

No real provider, SDK, native session, credential, account, order, cancel, or network route was exercised.

## Main-workspace verification

The main guarded focus passed **7 tests** with `pytest_exit=0`, one existing Pytest configuration warning, targeted Ruff pass, and `git diff --check` pass. The JUnit report is [focus.xml](main-focus/focus.xml); [guard log](main-focus/guard-13068.json) has empty `events` and `native_modules_loaded`. The [summary](main-focus/result-summary.json) records the executor-reported exit and checks.

## Repository-wide static inventory

The official collector reported 355 files, 363 writer candidates, 97 dynamic candidates, and zero parse errors. Its complete ordered rows and locators matched the checked-in inventory. The official verifier exited 0 and passed 460/460; all 460 rows remain `REVIEW_REQUIRED`, with six historical tombstones. This is static disposition integrity only, not writer closure or live admission. See the [collector JSON](scanner/collector-inventory.json), [collector stdout](scanner/collector-stdout.txt), [verifier stdout](scanner/verifier-output.txt), [summary](scanner/result-summary.json), [inventory](scanner/current-inventory/live-execution-inventory-candidates.json), [dispositions](scanner/current-inventory/live-execution-writer-dispositions.json), and [scanner tools and scope](scanner/tools/collect_iteration41_writer_inventory.py).

## Residual scope

This closes only the retired 007 timeout helper. General Cerebro APIs still allow callers to invoke `run()` on manually assembled engines; public `BtApiStore`, `BtApiBroker`, and `BtApiFeed` construction paths also remain available. Other direct paths can reach Store/provider startup independently. This archive makes no whole-writer, account-wide isolation, or live-acceptance claim. CTP writes remain `NO_WRITE / LIVE_NO_GO`.

Tracked 007 source snapshots retain public sample endpoint literals from the repository; none were resolved, contacted, or validated as usable endpoints in this work.

## Integrity files

- [Artifact manifest](ARTIFACT-MANIFEST.json)
- [SHA-256 sums](SHA256SUMS.txt)
