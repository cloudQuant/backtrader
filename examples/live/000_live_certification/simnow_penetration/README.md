# SimNow penetration certification (three-file cases)

Every case directory is self-contained and directly runnable:

```
cases/<ID>/
  config.yaml        # scenario parameters, policy, credential env NAMES (no secrets)
  <ID>_strategy.py   # the case logic (read-only, write, or dangerous risk level)
  run.py             # entry point
```

Run one case:

```bash
C:/anaconda3/python.exe cases/<ID>/run.py                 # dry self-check (no network)
C:/anaconda3/python.exe cases/<ID>/run.py --live          # read-only cases
C:/anaconda3/python.exe cases/<ID>/run.py --live --allow-write              # write cases
C:/anaconda3/python.exe cases/<ID>/run.py --live --allow-write --allow-dangerous
```

- Credentials and front candidates are read by NAME from the checkout-root
  `.env` (`CTP_*`).  The SDK source is the dev tree at `BT_API_PY_ROOT`
  (default `D:/bt_api_py`); live runs need CPython 3.11 (`C:/anaconda3`).
- Write cases arm the session through the SDK's frozen-simulation direct
  admission before any order.  Orders use timestamp-unique OrderRefs;
  acceptance, cancel terminal state, and residuals are confirmed through the
  venue order query.  Every placed order is tracked and compensating-canceled
  if the case fails.
- Each run writes one JSON evidence file under `cases/<ID>/evidence/`
  (git-ignored) and prints a single-line summary; exit codes:
  0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.
- `certlib/` is the small shared layer: `.env` reader, CTP session
  (`ctp_client.py`: connect/query/arm/order/cancel/close), local validation
  rules (`validation.py`), the certification monitor recorder
  (`monitor.py`), and the uniform runner.

Higher-risk cases (real orders) require the explicit `--allow-write` /
`--allow-dangerous` grants on every invocation; nothing in this suite touches
production endpoints.
