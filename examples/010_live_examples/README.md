# Live Examples and Network Tests

## Iteration 41 boundary for retired SimNow tests

`test_simnow_ctp.py` and `test_simnow_trade_logger_certification.py` contain
historical direct account/order certification logic. They are not managed
sandbox tests and cannot be used as an Iteration 41 execution route. Direct
script invocation and pytest collection are fail-closed; all legacy flags,
including `--subprocess-case`, are rejected before a Backtrader or provider
import. The source remains for a later managed TestExecutionProfile migration.

The only registered CTP/SimNow-related route in this directory is a local,
zero-I/O `simulation/replay` migration report:

```bash
bt-runtime bootstrap --strategy-dir examples/010_live_examples/runtime
bt-runtime run --strategy-dir examples/010_live_examples/runtime
```

Use `bootstrap` for first-time setup. It creates the ignored, mandatory
schema-v4 `runtime/config.yaml` from the code-owned safe defaults; the tracked
`runtime/config.example.yaml` is for review and is not a manual setup step. A
missing file returns `CONFIG_REQUIRED`, and bootstrap preserves an existing
file by rejecting with `CONFIG_EXISTS`.

To inspect the config without running the local probe, use the offline doctor:

```bash
bt-runtime doctor --strategy-dir examples/010_live_examples/runtime
```

`doctor` performs no provider or network I/O. The result is
`LOCAL_REPLAY_ONLY`: it proves only the config gate and no-action probe, never a
CTP connection, SimNow account, order, cancel, fill, PnL, or managed/sandbox/live
admission.

## OKX MixBroker public data demo

The separate `runtime-okx-shadow/` profile requests up to five levels from
public OKX swap order books for the fixed BTC and ETH contracts. It is
registered as schema-v4
`simulation/shadow`, uses only the reviewed fixed symbols and bounded duration
from `config.yaml` (bootstrap writes the code-owned example defaults), and
does not read accounts, accept credentials, place or cancel orders, or create
hypothetical fills.

Install the reviewed optional provider extra in the active Python 3.11
environment (tested with CCXT 4.5.83 and aiohttp 3.14.3):

```bash
python -m pip install -e ".[okx-public-shadow]"
```

Then bootstrap and run from the repository checkout:

```bash
bt-runtime bootstrap --strategy-dir examples/010_live_examples/runtime-okx-shadow
bt-runtime run --strategy-dir examples/010_live_examples/runtime-okx-shadow
```

The bootstrap command creates a usable ten-second config with the two fixed
symbols and requested depth of five. The tracked
`runtime-okx-shadow/config.example.yaml` is for review; bootstrap is the setup
command. The observer limits each run to 30 seconds and requests depth five.
Providers may return more levels than requested; the observer validates at most
the first five on each side and passes only those levels to
`LiveMultiSymbolStrategy.notify_orderbook`. The callback adapter has no
Cerebro instance, broker, account access, or order route, and the report labels
the result as callback observation. The strategy's `next()` method does not
calculate a signal from order books, so this is not a strategy or trading run.
The runner disables environment proxy use and passes no credentials or
endpoint overrides to CCXT Pro. Its report is public-market observation only,
not account, execution, fill, or profitability evidence. `bt-runtime run`
returns an error when the bounded read cannot produce an order-book observation
or close the provider cleanly.

The existing `runtime/config.yaml` route remains a separate local
`simulation/replay` migration report for the retired SimNow tests. Running
`live_mixbroker_okx_demo.py` still enters that replay route; it does not start
the shadow observer.

The historical watcher and strategy helpers remain available for fake-client
unit tests. `live_tick_demo.py` remains a local queue example. `run.py`-style
direct SimNow test workflows, account credentials, and manual direct pytest
commands are not supported migration procedures.
