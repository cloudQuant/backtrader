# OKX penetration certification (three-file cases)

Every case directory is self-contained and directly runnable:

```
cases/<ID>/
  config.yaml        # scenario parameters, policy, credential env NAMES (no secrets)
  <ID>_strategy.py   # the case logic (READ / WRITE / DANGEROUS risk levels)
  run.py             # entry point
```

Run one case:

```bash
C:/anaconda3/python.exe cases/<ID>/run.py                # dry self-check (no network)
C:/anaconda3/python.exe cases/<ID>/run.py --live         # read-only cases
C:/anaconda3/python.exe cases/<ID>/run.py --live --allow-write             # write cases
C:/anaconda3/python.exe cases/<ID>/run.py --live --allow-write --allow-dangerous
```

- Credentials come from the checkout-root `.env` by NAME (`OKX_DEMO_API_KEY`,
  `OKX_DEMO_SECRET`, `OKX_DEMO_PASSPHRASE`); the client signs OKX v5 requests
  (HMAC-SHA256 base64) with the demo header `x-simulated-trading: 1` and compensates
  the server-time offset at connect.
- Optional components (also selectable per invocation): `--transport direct|gateway_zmq`,
  `--execution`, `--risk`, `--monitor` — see `../optional16/README.md`.  For risk notional
  on contracts, the case policy carries `quantity_multiplier` (BTC-USDT-SWAP: 0.01).
- Each run writes one JSON evidence file under `cases/<ID>/evidence/` (git-ignored) and
  prints a single-line summary; exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.
- `certlib/` is the small shared layer (env file reader, signed demo client, monitor
  recorder, local validation rules, uniform runner).  The 33-case live results and the
  archived evidence are bound in the r21 tracker under
  `docs/_internal/opts/requirements/迭代41-.../evidence/`.

Higher-risk cases (real orders) require the explicit `--allow-write` / `--allow-dangerous`
grants on every invocation; nothing in this suite touches production endpoints.
