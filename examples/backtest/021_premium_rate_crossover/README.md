# 021 — Convertible-bond premium-rate crossover

The example reads the public fixture `tests/datas/113013.csv` by default. Use
`--data-file` to select another CSV — an absolute path is used as given, a
relative one resolves against the project root — and `--output-dir` to choose
where the generated chart is saved. The tracked chart under `reports/reference/`
is a historical reference image; each run writes a fresh image under the
ignored `output/` directory by default.

```console
python examples/backtest/021_premium_rate_crossover/run.py --no-show
python examples/backtest/021_premium_rate_crossover/run.py --data-file D:/market-data/113013.csv --output-dir D:/results --no-show
```

A missing input reports BLOCKED and exits 2; supply an existing CSV using
`--data-file`. The default fixture is resolved only after arguments are parsed.
