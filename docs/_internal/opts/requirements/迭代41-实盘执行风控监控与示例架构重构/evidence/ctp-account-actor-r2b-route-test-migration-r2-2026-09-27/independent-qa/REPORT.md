# R2b route-test migration R2 — independent QA

**Disposition: SAFE_LOCAL_TEST_MIGRATION / NO_WRITE.** This confirms only the local fake/offline test migration. No provider, SDK, network, account, order, or live write was exercised.

## Frozen inputs

- R2 patch SHA-256: 38A7615F760803D140DAB3546355CF20733D3B6A2410E210D456114EF1F2096A.
- Author manifest SHA-256: BC6575878AB6C0CA1053DD0E7325C67371FB9FC209D937C8A600CAE6503745F9; all 17 listed payload hashes match.
- r2b base patch SHA-256: 1A16AADB94EDB99924553D6472BF72DCB02BD04C7F994276816D91991A729F37.
- Four captured original test/support inputs match their recorded hashes. Applying the test-only patch to captured original tests reconstructs the exact two tested test-module hashes.
- R1 patch SHA-256: 93BD64374B156CBDE9A2D2F62793A736EBBDF015C5BA01F6D0C55032F1DC31B1. R1 is superseded.

## Replay and review

Author and independent isolated replays each report **35 passed, 0 failed, 0 errors, 0 skipped**. The independent command was C:\anaconda3\python.exe run_guarded_pytest_r2.py from a copied candidate tree, with provider-import and socket guards enabled; all guard arrays are empty. Raw stdout, stderr, exit code, JUnit, command, and guard summary are in this directory.

R2 restores store.start() and store.stop() in finally using a dedicated synchronous FakeSdk: its three async_* attributes are disabled for this test. Assertions cover _started, SDK and execution_config object identity, and zero configure_execution calls. This exercises synchronous Store lifecycle only; it does not cover the async command worker or a real SDK startup.

The provider="outer" sentinel is changed to supported provider="okx"; the test still checks that getdata(provider="explicit") and the explicit Store object are preserved. It no longer tests an unsupported arbitrary Store provider value, which is rejected by the current early route contract. Route-negative tests remain in the 35-case replay, including explicit/nested CTP rejection and caller-object/environment traps.

## Scope limit

NO_WRITE means no external/provider/order write occurred. Evidence files are archived here; no production source, tests, candidate, default route, or private configuration was changed.
