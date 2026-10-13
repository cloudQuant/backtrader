# 022 — CryptoHFTData SMA crossover

This example fetches historical trades through the optional `cryptohftdata`
SDK. The request is read-only and bounded by `--from-date` / `--to-date`, but
it contacts the configured data provider. Running without `--run` makes no
request. Before a request, the entry checks that the optional SDK is installed
and that the variable named by `--api-key-env` is set; it never prints the key.

Install the optional extra and set the key in the process environment, then
explicitly opt in:

```powershell
python -m pip install "backtrader[cryptohftdata]"
$env:CRYPTOHFTDATA_API_KEY = '<your-provider-key>'
python examples/backtest/022_cryptohftdata_sma/run.py --run --from-date 2026-07-01 --to-date 2026-07-02
```

The example does not load `.env`, store the key in a file, or write result
files. If the SDK or key is unavailable, it exits with a clear blocked status
before making a provider request.
