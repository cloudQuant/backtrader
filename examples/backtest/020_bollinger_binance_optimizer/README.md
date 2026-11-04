# 020 — Binance Bollinger/ATR optimizer

This optimizer reads Binance ZIP files from a caller-supplied directory. It
does not download data. Results go to this leaf's ignored `output/` directory
by default, independent of the input directory; `--output-dir` selects a
different destination.

```console
python examples/backtest/020_bollinger_binance_optimizer/optimize_bollinger_strategy.py --data-dir D:/market-data/binance
python examples/backtest/020_bollinger_binance_optimizer/optimize_bollinger_strategy.py --data-dir D:/market-data/binance --output-dir D:/results/bollinger
```

The parameter sweep can use multiple processes and is compute intensive. Use
`--no-multiprocessing` for a single-process run or `--cpu-usage` to set the
worker share. Input ZIP files stay in the supplied data directory. By default,
results are written under the example directory; use `--output-dir` to choose
a different destination.

Relative `--data-dir` and `--output-dir` paths are resolved from the current
working directory. A missing directory or one without ZIP files reports BLOCKED
and exits 2; supply a directory with the source files to continue. If every
parameter combination fails, the optimizer reports that no results are valid
and exits 1.
