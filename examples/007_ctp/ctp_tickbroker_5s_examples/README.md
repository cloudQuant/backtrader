# CTP TickBroker 5s Examples

This folder contains two 5-second bar examples for TickBroker-style 5s. The strategy code stays unchanged between backtest and live; you switch only the YAML config file.

Backtest:

```bash
python examples/ctp_tickbroker_5s_examples/backtest/run.py --config single_symbol.yaml
python examples/ctp_tickbroker_5s_examples/backtest/run.py --config pair_arbitrage.yaml
```

Live dry-run:

```bash
python examples/ctp_tickbroker_5s_examples/live/run.py --config single_symbol.yaml --dry-run
python examples/ctp_tickbroker_5s_examples/live/run.py --config pair_arbitrage.yaml --dry-run
```

Live with SimNow after the market resumes:

```bash
python examples/ctp_tickbroker_5s_examples/live/run.py --config single_symbol.yaml
python examples/ctp_tickbroker_5s_examples/live/run.py --config pair_arbitrage.yaml
```

Notes:

- The single-symbol strategy is a 5-second bar moving-average strategy.
- The pair strategy is a 5-second bar spread-arbitrage strategy on `rb2605` and `hc2605`.
- Backtest uses `TickBroker with synthetic ticks aggregated into 5-second bars inside the strategy`.
- Live uses `BtApiStore(provider="ctp") + BtApiBroker + BtApiFeed` with `TradeLogger` enabled.
