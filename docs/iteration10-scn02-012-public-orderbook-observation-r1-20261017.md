# Iteration 10 SCN02 012 public orderbook observation

Repository: Backtrader `dev`, based on `5dbb9b3b1be1b58cae2f32945699697ad988a077`. This round adds read-only observation entrypoints to examples 012_1 and 012_2, their candidate manifests and guidance, one shared cross-exchange observer, and a focused synthetic-host integration test. The shared SDK snapshot used for the focused run is `bt_api_py` commit `943b615e498d09d3ef4110e714cc552abe7be52a`; its observation helper and typed orderbook proxy dependencies were already committed in Backtrader (`7cda685` and `b69cf008c`).

With both explicit venue service configs, each example calls the shared observation path and reports independent typed orderbook snapshots. Missing or partial config returns a blocked result before opening a session. The observation path does not enable writes, trading, or cross-venue execution alignment. The focused host test uses two SDK clients and four local synthetic Gateway processes (account-session worker and market hub for each venue), checks key/depth/sequence and identity bindings, and verifies normal close and process cleanup. No real account, external provider, or venue network was used. The proxy's maximum-age check is a provider-observed/header-time heuristic, not a trusted clock or execution-freshness qualification.

The 012_2 selector ran once through the existing focused QA runner:

`C:\anaconda3\python.exe .codex-tmp\iteration10-focused-qa.py .codex-tmp\scn02-012-2-focused-host-r1.json`

The selected node passed (1 passed, Python/pytest exit 0, 21.75 seconds); stderr was empty and one existing Quandl deprecation warning was reported. Source count was 1,408 and remained unchanged. The result is `D:\temp\scn02-012-2-root-frozen-host-r2-20261017\host-run-012_2-r1\result.json` (529 bytes, SHA-256 `1bdf06c02f33603d31397303d797b3400c97f51f631d950beac41aa2cd4348e4`); JUnit is 469 bytes, SHA-256 `6b0fa2faf9e1a4a903cc380d54372c592cb83807bd08d837607f1ba8ead86515`. The lifecycle receipt records four ready children, four close acknowledgements, exit code 0 for each, normal joins, no forced cleanup, and no remaining owned PIDs.

The 012_1 selector's earlier result is retained at `D:\temp\scn02-012-1-root-frozen-host-r1-20261017\host-run-012_1-r1`. Its JUnit reports one pass and its lifecycle receipt reports four normal synthetic-host closes. The outer PowerShell wrapper used a reserved `$PID` variable and failed; the focused Python exit was not observed. This limitation is preserved as an exit-observation gap, not rewritten as a test failure or a verified Python exit.

The two results establish only local synthetic service observation and lifecycle behavior for these selectors. They do not establish real-account/provider acceptance, external venue availability, trusted cross-venue clock alignment, or write-path acceptance. Commit: this record and the eight selected source/test paths are delivered together; see the containing Git commit in the round handoff.

The accepted acktrader_runtime/cross_exchange_orderbook_observation.py pin retains one extra blank line at EOF (line 383). This is the sole git diff --cached --check whitespace exception; the reviewed source bytes were preserved.
