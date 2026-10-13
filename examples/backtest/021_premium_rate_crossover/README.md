# 021 — Convertible-bond premium-rate crossover

The example reads the shared public fixture `examples/data/113013.csv` by
default. Use `--data-file` to select another CSV and `--output-dir` to choose
where the generated chart is saved. The tracked chart under `reports/reference/`
is a historical reference image; each run writes a fresh image under the
ignored `output/` directory by default.

```console
python examples/backtest/021_premium_rate_crossover/run.py --no-show
python examples/backtest/021_premium_rate_crossover/run.py --data-file D:/market-data/113013.csv --output-dir D:/results --no-show
```
