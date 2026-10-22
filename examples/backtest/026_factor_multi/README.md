# 026: Multi-factor research on real A-share daily bars

This example collects three native Backtrader factors on the same real daily panel as 025:

- `close / SMA(close, 20)`;
- `close / close[-20] - 1` using the native ROC indicator;
- KDJ.J with a 9-bar high/low range, 3-bar K smoothing and 3-bar D smoothing.

From the repository root:

```powershell
python examples/backtest/026_factor_multi/run.py --output-dir output/026-real
```

Like 025, the runner evenly samples **500** symbols from `tests/datas/a_stocks` by default; `--max-symbols 0` uses all 5,471, and `--data-dir` selects another panel with the same layout. The research calendar is the source-observed session union, prices are unadjusted, and missing rows are not filled.

The configured evaluation asks fincore for cross-sectional ranks, the fixed `equal_weight` combination, its leave-one-factor-out ablations, IC/Rank IC, quantiles, stability, correlation and common-pool comparisons. The output factor columns are `close_ma`, `kdj_j`, `roc` (the library's stable order), one row per grid time and symbol.

Outputs:

- `factor_values.csv`: `time`, `asset`, and the three factor columns.
- `evaluation/`: fincore's tables and chart, when the fincore factor-research API is installed.
- `summary.json`: status, symbol/date counts, evaluation identity and report paths.
- `factor_report_<factor>.html`: written with `--report`, one self-contained bilingual (中文/English) report per factor with interactive ECharts charts and IC, quantile-return, turnover and coverage tables.
- `panel/`: written only with `--save-panel`; the six CSV files (`factors`, `grid`, `prices_open`, `prices_close`, `universe`, `groups`) for an explicit offline re-evaluation.

Evaluation is optional. When fincore's research API is unavailable, `factor_values.csv` is still written, `EVALUATION SKIPPED` is printed, and the run exits 0 with `summary.json.status="PANEL_ONLY"`. Exit codes are 0 for written outputs, 1 for a failed or `UNEVALUABLE` evaluation, 2 for invalid or missing input, and 3 for an output I/O failure.

Useful flags: `--report`, `--report-language zh|en` (default `zh`; the HTML also has a 中文/EN switch), `--no-charts`, `--periods 1 5 20`, `--runnext`, `--save-panel`, and `--panel <saved-panel>` for offline re-evaluation without Cerebro. `--report` delegates to `fincore.report.factor.write_factor_report`, so it works even when the separate research-evaluation API is unavailable.

The output is a factor research result, not a trading strategy or evidence of investment performance.
