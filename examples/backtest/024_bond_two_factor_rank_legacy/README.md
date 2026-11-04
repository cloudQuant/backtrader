# 024 — Convertible-bond two-factor rank variant

`optimize_strategy.py` is a historical filename; this entry runs one
two-factor convertible-bond backtest and does not search a parameter grid. It
keeps the original strategy implementation because its tie handling, ranking
order, and expired-order behavior differ from the canonical strategy in
`001_multi_extend_data`. The implementations are intentionally separate so
organizing the examples does not silently change this variant's results.

Both inputs come from the repository data tree — `tests/datas/bond_index_000000.csv`
and `tests/datas/bond_merged_all_data.csv` — resolved root-relative by
`backtrader.utils.paths.data_path`. A missing fixture fails the run and names the
path; nothing is downloaded and no `BACKTRADER_DATA_DIR` lookup remains.

```console
python examples/backtest/024_bond_two_factor_rank_legacy/optimize_strategy.py
```

The run prints metrics to the console and does not write results into the
source directory. The input directory is read only.

This historical strategy looks ahead in loaded data to detect the end of a
feed, so its backtest has look-ahead bias. Its locally defined `fromdate` and
`todate` parameters are not passed to the feeds and therefore do not constrain
the run. End-of-feed errors are caught broadly; a successful exit does not
prove that all attempted closes were filled or cancellations succeeded.
