# 027: Alpha101 #3 on real A-share daily bars

This example runs the production native Alpha003 factor over the observed daily panel in `tests/datas/a_stocks`:

```text
-correlation(rank(open), rank(volume), 10)
```

It uses `backtrader.research.alpha101.get_alpha(3)` → `Alpha003Native`, so the formula is the library implementation, not a copy inside the example. The old three-asset synthetic fixture and its handwritten `alpha003_strategy.py` duplicate have been removed.

From the repository root:

```powershell
python examples/backtest/027_alpha003_panel_acceptance/run.py --output-dir output/027-real
```

Add `--report` to write the HTML report, and `--report-language zh|en` to choose its default language (the HTML also has a 中文/EN switch). The runner evenly samples **500** symbols from the manifest by default; `--max-symbols 0` uses all 5,471 symbols, and `--data-dir` selects another panel with the same `_metadata/manifest.json` and per-symbol CSV layout. The calendar is the source-observed session union, prices are unadjusted, and missing rows are not filled. Alpha003 needs a complete 10-row window of cross-sectional ranks, so suspended or newly listed symbols produce NaN windows and a reason in the dataset availability table.

Outputs:

- `factor_values.csv`: `time`, `asset`, `alpha003`.
- `summary.json`: status, factor identity, symbol/date/cell counts, finite values, elapsed time and report path.
- `factor_report_alpha003.html`: written with `--report`; a self-contained bilingual (中文/English) HTML report with interactive ECharts charts and IC, quantile-return, turnover and coverage tables.

For the full-market runner with date chunking, resume, and an independent full-panel oracle check, see [`run_daily.py`](run_daily.py) and [HANDOFF.md](HANDOFF.md). `run.py` is the quick real-data demonstration; `run_daily.py` is the longer full-market pipeline.

`025_factor_single` and `026_factor_multi` use the same real panel to demonstrate single-factor and multi-factor research with fincore evaluation.

The factor values are research output, not a trading signal or evidence of investment performance.
