# 027: Alpha101 #3 on real A-share daily bars

This example runs the production native Alpha003 factor over the observed daily panel in `tests/datas/a_stocks`:

```text
-correlation(rank(open), rank(volume), 10)
```

It uses `backtrader.research.alpha101.get_alpha(3)` → `Alpha003Native` by default. `--factor-mode build` selects the build method on that same `Alpha003Native` class through `FactorSpec(mode="build")`. There is no separate Build class. Both use the same factor strategy and Cerebro lifecycle. The old three-asset synthetic fixture and its handwritten `alpha003_strategy.py` duplicate have been removed.

From the repository root:

```powershell
python examples/backtest/027_alpha003_panel_acceptance/run.py --output-dir output/027-real
python examples/backtest/027_alpha003_panel_acceptance/run.py --factor-mode build --report --output-dir output/027-build
```

For this quick entry, `--factor-mode native|build` overrides `config.yaml`'s `factor_mode`, with `native` as the default. The engine remains runnext in both modes. The summary includes the actual mode, class, `factor_calculation="RAN"` and zero order counters. Use a new output directory for each run.

The current single-class refactor passed local source and installed-wheel checks; see the [Iteration49 implementation and acceptance record](../../../docs/_internal/opts/requirements/迭代49-因子单类双模式重构/实施与验收.md). The historical [Iteration48 acceptance record](../../../docs/_internal/opts/requirements/迭代48-Alpha101-build实现/验收结果.md) covers all 101 native/build formula pairs and this quick entry's pinned-wheel output/report comparison with 20 assets. The separate 500-asset comparison and small daily worker/resume checks remain recorded in Iteration47; they do not establish full-market throughput.

Add `--report` to write the HTML report, and `--report-language zh|en` to choose its default language (the HTML also has a 中文/EN switch). The runner evenly samples **500** symbols from the manifest by default; `--max-symbols 0` uses all 5,471 symbols, and `--data-dir` selects another panel with the same `_metadata/manifest.json` and per-symbol CSV layout. The calendar is the source-observed session union, prices are unadjusted, and missing rows are not filled. Alpha003 needs a complete 10-row window of cross-sectional ranks, so suspended or newly listed symbols produce NaN windows; the missing bar itself and the following lookback points are NaN.

Outputs:

- `factor_values.csv`: `time`, `asset`, `alpha003`.
- `summary.json`: status, factor identity, symbol/date/cell counts, finite values, elapsed time and report path.
- `factor_report_alpha003.html`: written with `--report`; a self-contained bilingual (中文/English) HTML report with interactive ECharts charts and IC, quantile-return, turnover and coverage tables.

For the full-market runner with date chunking, resume, and an independent full-panel oracle check, see [`run_daily.py`](run_daily.py) and [HANDOFF.md](HANDOFF.md). `run.py` is the quick real-data demonstration; `run_daily.py` is the longer full-market pipeline.

The daily runner also accepts `--factor-mode native|build`, defaults to native and does not read the quick YAML. The mode is part of its run identity and is passed to each worker. Resume requires the same mode, inputs, parameters and source identity; use a separate directory for another mode. Iteration47 checks actual workers and resume on a small multi-chunk fixture; the historical HANDOFF's unfinished full-market run remains separate evidence.

`025_factor_single` and `026_factor_multi` use the same real panel to demonstrate single-factor and multi-factor research with fincore evaluation.

The factor values are research output, not a trading signal or evidence of investment performance.
