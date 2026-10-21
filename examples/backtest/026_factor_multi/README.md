# 026: Multi-factor research

This example collects three native Backtrader factors on the same deterministic synthetic panel as 025:

- `close / SMA(close, 20)`;
- `close / close[-20] - 1` using the native ROC indicator;
- KDJ.J with a 9-bar high/low range, 3-bar simple-average K smoothing, 3-bar simple-average D smoothing, and `J = 3*K - 2*D`.

It ranks each base factor across the assets, then asks fincore to evaluate the fixed `equal_weight` combination and its three generated leave-one-factor-out ablations (`equal_weight::without::close_ma`, `equal_weight::without::roc`, and `equal_weight::without::kdj_j`). The configured comparison family names the three base factors and the full combination; the evaluator adds the generated ablations and evaluates them on one common eligible pool, without expanding that pool for an ablation. The output includes factor correlation, lag stability and the frozen development/validation segments. All directions are fixed at `+1` as demonstration assumptions. No positive IC or return is required, and a segment label does not make the validation period an independent out-of-sample study.

For this example, each factor exposes one panel output named `factor`; for KDJ that selected output contains J. KDJ still constructs native RSV and smoothed K/D child indicators. This is the example's uniform panel convention, not a limitation on `FactorIndicator`, which can expose multiple output lines.

From the repository root, run (relative output paths resolve from this example directory):

```powershell
python examples/backtest/026_factor_multi/run.py --output-dir output/026-multi
```

The SHA-256 generator is versioned and seeded in `config.yaml`; its explicit `data_version` records the generator version and seed used for the bound feed values. It creates 20 assets, 20 warm-up bars, 260 research bars and a 21-bar price tail on the UTC `synthetic-weekday-v1` calendar. Its OHLCV output is designed to match 025 value for value. The first 15 generated bars for each asset have zero high/low range; the factor returns missing values for those KDJ windows and becomes available after complete RSV/K/D windows recover. The dedicated test also has an independent known-answer fixture for that transition.

The full research-period evaluation uses the price tail and has no structural horizon loss. Each named development/validation segment excludes its final `h + 1` eligible bars for a next-open-to-open horizon `h`, because the signal, entry bar and exit bar must all belong to that segment. Those expected losses remain in coverage denominators and are marked as segment-boundary losses. The expected overall status is `PARTIAL`; the runner accepts it only when the reported boundary counts match the frozen segments, all other required outputs are present, and the loss rate remains below `max_loss`.

The runner only collects, evaluates, exports and checks required result coverage;
it has no embedded test oracle and does not require positive IC or returns. The
KDJ known-answer and generator-equality checks live in the dedicated unit tests.
Completed runs mark their evidence level as
`SYNTHETIC_OFFLINE_FACTOR_RESEARCH_ONLY` and `acceptance_status` as
`NOT_CLAIMED`; they are example results, not full iteration acceptance.

`diagnostics` is a predeclared optional result table, so it may be absent from
the evaluator result without waiving any required table, row, count, or segment
check. The versioned export still includes its fixed CSV/JSON schema entries,
which may contain a header-only CSV and an empty JSON array. Exit codes are 0
when all mandatory outputs pass (including a truthful `PARTIAL` result), 1 when
required outputs are missing or the result is `UNEVALUABLE`, 2 for invalid input
or a blocked prerequisite/dependency, and 3
for interruption or output I/O failure.

The counting Broker observes submit and cancel calls throughout Cerebro and the
runner fails if either count is nonzero. The dedicated native collection test
checks this guard in both `runonce` and `runnext` modes without running fincore.

The output folder contains the versioned raw research dataset, fincore's CSV/JSON evaluation files, requested charts, and a run manifest with source versions, dataset identity, fixed factor weights and directions, segment boundaries, result status, output hashes and Broker submit/cancel counts. The runner verifies the required signal/variant/group/horizon/segment axes, labels, common-pool comparisons and coverage artifacts; it does not treat successful computation as a performance claim. `--no-charts` disables chart rendering.

Saved datasets can be evaluated again without constructing Cerebro or indicators. For example:

```powershell
python examples/backtest/026_factor_multi/run.py --dataset output/026-multi/dataset --periods 1 10 --output-dir output/026-multi-h1-h10 --no-charts
```

The generator and factor declarations live in this directory so the example can be copied and run independently. It does not read repository tests, neighboring examples or `examples/_support`. A copied-folder run under `BT_I43_COPY_STRICT=1` and a real installed-wheel run are separate acceptance checks; this source package does not claim those checks have passed.

The generated series are synthetic pipeline fixtures. They do not establish market performance, a profitable direction, or statistical significance.
