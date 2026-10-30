# Binance penetration certification (three-file cases)

Every case directory is self-contained and directly runnable:

**Trading-mode status (legacy command):** The direct-mode commands below use
Binance demo credentials and the simulated environment. That external
simulated account is `paper` under the shared [trading-mode standard](../../../../docs/source/advanced/architecture/trading-modes_zh.md);
`live` means a production account. The existing `--live` flag is an old command
selector, not the Iteration 52 mode API, and is not automatically mapped to a
new mode. Iteration 52 covers `paper/live` use and acceptance; `replay/shadow`
are being inventoried for later ownership decisions.

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
C:/anaconda3/python.exe cases/C01/run.py --live --transport service          # C01 SDK account service
```

- Direct-mode credentials come from the checkout-root `.env` by NAME (`BINANCE_DEMO_API_KEY`,
  `BINANCE_DEMO_SECRET`); the client measures the server-time offset at connect.
  EM01 additionally supports an optional restricted-permission key via
  `BINANCE_DEMO_RESTRICTED_API_KEY` / `BINANCE_DEMO_RESTRICTED_SECRET` (not required).
- C01 can use the normal SDK account service with `--transport service`. Its
  `service_client` block and `service-client.example.yaml` show the client-side
  service binding; replace the example service/account references, endpoint,
  required account coverage, and three CURVE environment variable names with
  the values provisioned for that host.
  Service mode reads no direct Binance API credential variables.
- The Optional16 component-acceptance matrix and live gateway-capability check are retired;
  `../optional16/acceptance-matrix.json` is a historical record and is no longer refreshed.
  This retirement leaves the per-case 33-case entry defaults unchanged.
- Each run writes one JSON evidence file under `cases/<ID>/evidence/` (git-ignored) and
  prints a single-line summary; exit codes: 0 PASS, 1 FAIL, 2 BLOCKED, 3 UNKNOWN.
- `certlib/` is the small shared layer (env file reader, signed demo client, monitor
  recorder, local validation rules, uniform runner).  The 33-case live results and the
  archived evidence are bound in the r21 tracker under
  `docs/_internal/opts/requirements/迭代41-.../evidence/`.

Higher-risk cases (real orders) require the explicit `--allow-write` / `--allow-dangerous`
grants on every invocation; nothing in this suite touches production endpoints.
