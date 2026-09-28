# OKX public market shadow

This is a separate, code-registered Iteration 41 `simulation/shadow` runtime.
It requests depth five from public OKX swap order books for the fixed BTC/USDT
and ETH/USDT instruments for at most 30 seconds. It does not read account
state, accept credentials, submit or cancel orders, or create hypothetical
fills.

Run the commands below for the fixed, reviewed default (both symbols, requested
depth five, ten seconds), or copy `config.example.yaml` to the ignored
`config.yaml` first to make those parameters explicit:

```bash
bt-runtime bootstrap --strategy-dir examples/010_live_examples/runtime-okx-shadow
bt-runtime run --strategy-dir examples/010_live_examples/runtime-okx-shadow
```

The configuration is the source for mode, preset and parameters. The symbols
must be a non-empty subset of the two listed instruments and duration must be
an integer from 1 through 30 seconds; requested order-book depth is fixed at
five. Safe bootstrap writes the same code-owned default parameters shown in
the example. Python 3.11 was tested with CCXT 4.5.83 and aiohttp 3.14.3; install
that reviewed optional pair with `python -m pip install -e ".[okx-public-shadow]"`.
The runner rejects unreviewed CCXT/aiohttp versions before creating a provider
client. The CCXT client uses fixed public OKX defaults, disables environment
proxy discovery and receives no key, secret, passphrase, endpoint, or region
settings. Public market reads can use the network; execution writes and account
reads remain closed. A provider may return more levels than requested; the
observer checks at most the first five on each side and reports only observation
counts.

The report separates `run_deadline_read_cancellations` and
`run_deadline_watcher_cancellations` (normal bounded-window stops) from
`public_market_read_timeouts` (a read that reaches its transport timeout), with
startup and shutdown timeout counters reported separately.

The result reports client-side public read calls, observed book counts, and the
requested order-book limit. It invokes
`LiveMultiSymbolStrategy.notify_orderbook` on each validated snapshot, passing
only the first five levels per side. The callback adapter runs without
Cerebro, a broker, account access, or an order route; the report labels this as
`CALLBACK_OBSERVED`. The strategy's `next()` method does not calculate a signal
from order books, so this is callback observation only, not a strategy or
trading run. The result is not account, execution, fill, or profitability
evidence. The historical `live_mixbroker_okx_demo.py` command remains on the
separate local replay migration profile and does not start this observer
implicitly.
