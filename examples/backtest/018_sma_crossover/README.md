# 018 — SMA crossover

A small daily-bar example for the `MA_CrossOver` strategy. Its input is the
repository's public `tests/datas/2006-day-001.txt` fixture, addressed
root-relative in `config.yaml` and resolved by
`backtrader.utils.paths.data_path`. Using this bundled fixture requires a
checkout; external files follow the path rules below.

Run from the repository root or this directory:

```console
python examples/backtest/018_sma_crossover/run.py
```

The strategy periods, starting cash, and `data_file` are in `config.yaml`.
An alternate configuration can be selected with `--config`. Absolute
`data_file` paths are used directly. Relative paths beginning with
`tests/datas/` refer to the project root; all other relative paths refer to the
directory containing the selected configuration file. The example does not
search other directories if a selected file is missing.

A missing configuration or data file reports `BLOCKED` and exits with code 2.
Supply an existing configuration or data file to continue. The example runs
only a local backtest and writes no files.
