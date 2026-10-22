# 025: Single-factor research on real A-share daily bars

This example collects one native Backtrader factor, `close / SMA(close, 20)`, on the observed daily panel in `tests/datas/a_stocks`. It uses the real per-stock daily CSVs; there is no synthetic fixture and no order placement.

From the repository root:

```powershell
python examples/backtest/025_factor_single/run.py --output-dir output/025-real
```

By default the runner evenly samples **500** symbols from the manifest, which keeps an example run to about a minute while still covering the whole market. Use `--max-symbols 0` for all 5,471 symbols, or `--data-dir <dir>` to point at another panel with the same `_metadata/manifest.json` and per-symbol CSV layout.

The research calendar is `_metadata/observed_calendar.csv`: the union of sessions observed in the source, not a verified exchange calendar. The source timezone is `Asia/Shanghai`; prices are used as provided, without adjustment or forward filling. Missing stock/day rows remain absent and become NaN, so the first 19 bars of each symbol have an incomplete SMA window.

Outputs:

- `factor_values.csv`: `time`, `asset`, `close_ma` for every grid row and symbol.
- `evaluation/`: fincore's tables and chart, when the fincore factor-research API is installed.
- `summary.json`: status, symbol/date counts, evaluation identity and report path.
- `factor_report_close_ma.html`: written with `--report`; a self-contained bilingual (中文/English) report with interactive ECharts charts and IC, quantile-return, turnover and coverage tables.
- `panel/`: written only with `--save-panel`; the six CSV files (`factors`, `grid`, `prices_open`, `prices_close`, `universe`, `groups`) for an explicit offline re-evaluation.

Evaluation is optional: when the fincore research API is unavailable, the runner still writes `factor_values.csv`, prints `EVALUATION SKIPPED`, and exits 0 with `summary.json.status="PANEL_ONLY"`. Exit codes are 0 for written outputs, 1 for a failed or `UNEVALUABLE` evaluation, 2 for invalid or missing input, and 3 for an output I/O failure.

Useful flags: `--report`, `--report-language zh|en` (default `zh`; the HTML also has a 中文/EN switch), `--no-charts`, `--periods 1 5 20`, `--runnext`, `--save-panel`, and `--panel <saved-panel>` to re-evaluate without constructing Cerebro or factor indicators (the saved panel must be paired with the same `config.yaml`, which supplies the explicit window, directions and orders). `--report` delegates to `fincore.report.factor.write_factor_report`, so it works even when the separate research-evaluation API is unavailable.

The runner is intentionally thin: it loads the panel, assembles `ResearchSpec`/`FactorSpec`, runs `FactorStrategy`, and exports the factor panel. Exhaustive result validation belongs to the library and its tests, not to this example.

The output is a factor research result, not a trading strategy or evidence of investment performance.
