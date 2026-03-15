# Live Network Tests

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
pytest examples/live_tests -v

# Run only SimNow CTP tests
pytest examples/live_tests/test_simnow_ctp.py -v

# Run trade logger certification
pytest examples/live_tests/test_simnow_trade_logger_certification.py -v

# Run btapi placeholder tests
pytest examples/live_tests/btapi/ -v
```
