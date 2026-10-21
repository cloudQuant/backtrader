# 025: Single-factor research

This example collects one native Backtrader factor, `close / SMA(close, 20)`, on a deterministic synthetic daily-session panel. It evaluates the saved panel with fincore through the public research adapter. The example does not place orders and does not treat a positive IC or return as a success condition.

From the repository root, run (the relative output path is resolved from this
example directory):

```powershell
python examples/backtest/025_factor_single/run.py --output-dir output/025-single
```

The runner creates 20 named assets on a UTC `synthetic-weekday-v1` calendar. The SHA-256 generator is versioned and seeded in `config.yaml`; its explicit `data_version` records the generator version and seed used for the bound feed values. It makes 20 warm-up bars, 260 research bars and 21 price-tail bars. Every bar has open, high, low, close and volume values. The 260-bar research period is split before evaluation into development bars 0–159 and validation bars 160–259. The factor direction is fixed at `+1` as a demonstration assumption.

The full research-period evaluation uses the price tail and has no structural horizon loss. Each named segment excludes its final `h + 1` eligible bars for a next-open-to-open horizon `h`, because the signal, entry bar and exit bar must all belong to that segment. Those expected losses stay in coverage denominators and are recorded as segment-boundary losses; the evaluation status is therefore `PARTIAL` when the configured segments are included. The runner accepts that status only when the reported boundary counts match the frozen segments, all other required outputs are present, and the loss rate remains below `max_loss`.

The output folder contains the versioned raw research dataset, fincore's CSV/JSON evaluation files, requested charts, and a run manifest with source versions, dataset identity, segment boundaries, result status, output hashes and Broker submit/cancel counts. The full label horizons are 1, 5 and 20 bars. `--no-charts` disables chart rendering while leaving the table export intact.

The runner's counting Broker records submit and cancel calls over the full Cerebro run and returns a failure if either count is nonzero. The dedicated native collection test checks this guard in both `runonce` and `runnext` modes; it does not run fincore.

The runner validates the emitted status and required signal/variant/group/
horizon/segment metrics, labels, coverage, stability and exported files. It does
not assert that an IC or return is positive. A completed run records
`SYNTHETIC_OFFLINE_FACTOR_RESEARCH_ONLY` and `NOT_CLAIMED`; it does not mean the
full iteration acceptance passed. Dedicated unit tests are independent
formula checks; the runner does not import a test oracle.

`diagnostics` is a predeclared optional result table, so it may be absent from
the evaluator result without waiving any required table, row, count, or segment
check. The versioned export still includes its fixed CSV/JSON schema entries,
which may contain a header-only CSV and an empty JSON array. Exit codes are 0
when all mandatory outputs pass (including a truthful `PARTIAL` result), 1 when
required outputs are missing or the result is `UNEVALUABLE`, 2 for invalid input
or a blocked prerequisite/dependency, and 3
for interruption or output I/O failure.

Saved datasets can be evaluated again without constructing Cerebro or indicators. For example:

```powershell
python examples/backtest/025_factor_single/run.py --dataset output/025-single/dataset --periods 1 10 --output-dir output/025-single-h1-h10 --no-charts
```

The dataset generator is duplicated inside this directory so the example can be copied and run independently. It does not read repository tests, neighboring examples or `examples/_support`. A copied-folder run under `BT_I43_COPY_STRICT=1` and a real installed-wheel run are separate acceptance checks; this source package does not claim those checks have passed.

The generated series are synthetic pipeline fixtures. They do not establish market performance, a profitable direction, or statistical significance.
