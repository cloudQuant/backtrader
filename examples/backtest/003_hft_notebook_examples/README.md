# 003 — HFT notebook examples

`prepare_data.py` uses local Binance public-data ZIP files by default and never
requests the network unless `--download` is explicitly supplied. `--skip-download`
remains an explicit local-only option. Set `BINANCE_PUBLIC_DATA_DIR` or pass
`--binance-project-root`; its `data/` directory is the default source, while
`--binance-source-root` overrides it. Relative external paths are relative to
the current working directory. `--data-root` selects the prepared output directory
(default: this example's `data/` directory).

```console
python examples/backtest/003_hft_notebook_examples/prepare_data.py --binance-source-root /path/to/data --prepare-glft
python examples/backtest/003_hft_notebook_examples/run_backtrader.py --strategy glft_market_making --data-root /path/to/prepared
```

Missing source or prepared data exits 2 with a BLOCKED message. The comparison
and hftbacktest entrypoints also require a compatible optional `hftbacktest`
installation. Downloads and provider behavior are not exercised by local tests.
