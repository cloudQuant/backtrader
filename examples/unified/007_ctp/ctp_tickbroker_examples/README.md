# CTP TickBroker Examples

This folder contains two high-frequency examples that keep the strategy code unchanged between backtest and live. You switch only the YAML config file.

Backtest:

```bash
python examples/ctp_tickbroker_examples/backtest/run.py --config single_symbol.yaml
python examples/ctp_tickbroker_examples/backtest/run.py --config pair_arbitrage.yaml
```

Live with SimNow:

```bash
python examples/ctp_tickbroker_examples/live/run.py --config single_symbol.yaml
python examples/ctp_tickbroker_examples/live/run.py --config pair_arbitrage.yaml
```

Environment:

```bash
SIMNOW_USER_ID=your_user
SIMNOW_PASSWORD=your_password
SIMNOW_ENV=auto
```

Notes:

- Backtest uses `TickBroker` with in-memory tick streams.
- Live uses `BtApiStore(provider="ctp") + BtApiBroker + BtApiFeed`.
- `SIMNOW_ENV=auto` probes the known SimNow fronts and picks the first one that logs in successfully.
- The single-symbol example is long-only and trades on tick momentum relative to a rolling tick mean.
- The pair example trades a short-`rb2605` / long-`hc2605` spread when the live spread deviates from its short rolling mean.
- `close_today` is used for the exit leg because the default symbols are SHFE contracts opened during the same session.
