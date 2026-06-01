# CTP MixBroker Examples

This folder contains two mixed-mode examples that keep one strategy implementation for both backtest and live. Only the YAML config changes.

Backtest:

```bash
python examples/ctp_mixbroker_examples/backtest/run.py --config single_symbol.yaml
python examples/ctp_mixbroker_examples/backtest/run.py --config pair_arbitrage.yaml
```

Live with SimNow:

```bash
python examples/ctp_mixbroker_examples/live/run.py --config single_symbol.yaml
python examples/ctp_mixbroker_examples/live/run.py --config pair_arbitrage.yaml
```

Environment:

```bash
SIMNOW_USER_ID=your_user
SIMNOW_PASSWORD=your_password
SIMNOW_ENV=auto
```

Notes:

- Backtest uses `MixBroker + MixedChannel`.
- Live uses `BtApiStore(provider="ctp") + BtApiBroker + BtApiFeed`.
- `SIMNOW_ENV=auto` probes the known SimNow fronts and picks the first one that logs in successfully.
- The single-symbol example combines live ticks with a short bar moving average.
- The pair example combines live ticks with a rolling fair-spread estimate built from completed bars.
- The live mixed-mode examples need a few aggregated bars before they can trade, so the initial warmup is expected.
