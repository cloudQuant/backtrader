# 023 — Mixed tick/bar backtest

This example combines tick events and completed bar events in
`StreamingEventQueue`, then runs them through `MixBroker`. It generates a
small deterministic local fixture on each run, so it does not read from
`tests/datas/` or invoke a repository data-generation tool.

```console
python examples/backtest/023_mixed_mode_backtest/run.py
python examples/backtest/023_mixed_mode_backtest/run.py --output-dir D:/backtest-output/mixed-mode
```

The generated `tick_demo.csv` and `bar_demo.csv` live under this leaf's
ignored `output/` directory by default. This is a local synthetic backtest;
it does not connect to a market-data provider or place live orders.
