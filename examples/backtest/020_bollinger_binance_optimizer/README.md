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
worker share. ZIP files and result files stay outside the source tree unless
the caller explicitly chooses another output path.
