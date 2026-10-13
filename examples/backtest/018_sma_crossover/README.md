# 018 — SMA crossover

A small, self-contained daily-bar example for the `MA_CrossOver` strategy.
The CSV under `data/` is a byte-identical copy of the repository's public
`tests/datas/2006-day-001.txt` fixture, so this example does not depend on the
test tree at runtime.

Run from the repository root or this directory:

```console
python examples/backtest/018_sma_crossover/run.py
```

The strategy periods, starting cash, and relative data path are in
`config.yaml`. An alternate configuration can be selected with `--config`.
The example runs only a local backtest and writes no files.
