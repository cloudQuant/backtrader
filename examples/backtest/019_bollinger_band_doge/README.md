# 019 — Bollinger Band DOGE train/test

This leaf contains the parameter search for the 2020–2024 training period and
the fixed 2025 out-of-sample evaluation. Both scripts read the shared,
read-only fixture at `examples/data/DOGEUSDT_15m_20200710_20260126.csv`.

Run from the repository root:

```console
python examples/backtest/019_bollinger_band_doge/bollinger_band_strategy_train.py
python examples/backtest/019_bollinger_band_doge/bollinger_band_strategy_test.py
```

Training performs a large multiprocessing parameter sweep. Training and test
results are written under this leaf's ignored `output/` directory, separated
into `training/` and `test/`. The source files and shared input CSV are not
modified by a run.
