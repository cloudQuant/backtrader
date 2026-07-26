# Live Examples and Network Tests

## Public OKX MixBroker demo

This example streams public ticker, five-level order-book, and one-minute bar
data from OKX. It never submits orders or loads credentials into the exchange
client.

```bash
pip install 'ccxt[pro]'
python examples/010_live_examples/live_mixbroker_okx_demo.py
```

These tests require **real network access** and external credentials.
They are excluded from the normal `pytest tests` run.

## Prerequisites

- SimNow CTP account credentials in `.env`:
  - `simnow_user_id`
  - `simnow_password`
- `bt_api_py` package installed or on `PYTHONPATH`

## Run manually

```bash

# From project root

pytest examples/010_live_examples -v

# Run only SimNow CTP tests

pytest examples/010_live_examples/test_simnow_ctp.py -v

# Run trade logger certification

pytest examples/010_live_examples/test_simnow_trade_logger_certification.py -v

# Run btapi placeholder tests

pytest examples/010_live_examples/btapi/ -v

```
