# Execution paths and parallel schedule

- Source checkout: `D:\source_code\backtrader`, branch `dev`, HEAD `b2697f13b99461f52c79b48ecf3b18ec6de19972`.
- Primary interpreter: `D:\temp\iteration45-installed-20261022\Scripts\python.exe`, invoked with `-E -s`.
- Native path: one run per example using the copied external runner in `D:\temp\iteration45-copy-final-r4-b269-20261022\cases\025_factor_single\run.py` or `...\026_factor_multi\run.py`; each used `--no-charts` and a new output directory.
- Offline path: the r4/r5 harnesses were invoked with `--repo-root D:\source_code\backtrader`, `--dataset` snapshots from the new native outputs, and unique scenario output directories. The reports correctly identify `examples/backtest/025_factor_single/run.py` and `examples/backtest/026_factor_multi/run.py` in the checkout as offline CLI sources. All eight example copies still hash-identically to their source-checkout files.

025 used `scripts/iteration45_offline_reevaluation_acceptance_r4.py`, SHA-256 `07d4e2c3b7fe51b91a966fb6988fdb7c4fbb2e60eaa7a198db5addd319e69547`, with a 900-second per-scenario timeout. The aggregate scenario timestamp span was 91.492 seconds for the same-config and periods `(1, 10)` reevaluations.

026 used `scripts/iteration45_offline_reevaluation_acceptance_r5.py`, SHA-256 `e8362880d0f379f83edf24a9fe04826f9e063917c3d8d829730126f3724ac2af`, with 2,400 seconds per scenario and at most two workers. The scheduling-only r5 was reviewed before use; it preserves the r4 worker, runner CLI, timeout-as-failure, and acceptance validation. Same-config, periods `(1, 10)`, and `close_ma: 2` weight variant each used a unique scenario directory. The aggregate scenario timestamp span was 975.610 seconds. All three workers exited zero and passed their scenario checks; both aggregate reports report `PASS`.

## Resource observations

The native run-manifest timestamps give 53.388 seconds for 025 and 569.229 seconds for 026. For native 026, periodic live readings were approximately 0.94–1.06 GB for `WorkingSet64` and 2.39–2.63 GB for `PrivateBytes`. These are sampled instantaneous values; no complete sampling trace or post-exit `PeakWorkingSet64` reading was retained, so they are not an OS peak or a final CPU/memory total.

For the 026 offline workers, live `Process.PeakWorkingSet64` reads reported cumulative OS peaks of 1,356.3 MiB and 1,142.9 MiB for the two-worker phase, and 1,355.5 MiB for the weight-variant worker. The weight worker's contemporaneous `WorkingSet64` readings included 1,099.9, 1,023.4, 980.2, and 1,064.6 MiB at different polls. The former is the OS-reported high-water value as of each read; the latter are current-working-set samples. Reads were made while the processes were active, so no value is asserted as the final post-exit high-water mark or complete sampled maximum. All workers subsequently completed with exit zero. Terminal CPU totals were not captured and are not inferred from the last live samples.

These timings and memory readings describe only the fixed 20-target / 301-grid-bar synthetic workload. There was no performance threshold for this acceptance, and no large-pool or high-frequency performance pass is claimed.
