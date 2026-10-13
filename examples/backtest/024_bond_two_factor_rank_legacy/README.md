# 024 — Convertible-bond two-factor rank variant

`optimize_strategy.py` is a historical filename; this entry runs one
two-factor convertible-bond backtest and does not search a parameter grid. It
keeps the original strategy implementation because its tie handling, ranking
order, and expired-order behavior differ from the canonical strategy in
`001_multi_extend_data`. The implementations are intentionally separate so
organizing the examples does not silently change this variant's results.

The public index fixture is shared from `examples/data/bond_index_000000.csv`.
The larger `bond_merged_all_data.csv` must be supplied by the caller, either
beside this script or in a directory named by `BACKTRADER_DATA_DIR`:

```powershell
$env:BACKTRADER_DATA_DIR = 'D:\market-data\convertible-bonds'
python examples/backtest/024_bond_two_factor_rank_legacy/optimize_strategy.py
```

The run prints metrics to the console and does not write results into the
source directory. The input directory is read only.
