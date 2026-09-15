"""Runner for the mid-frequency cross-product pair arbitrage example.

Reuses the SimNow wiring and config loading from
``examples/007_ctp/ctp_example_support``; ``--replay`` validates the strategy
state machine on a local MixBroker with synthetic ticks.
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SUPPORT_ROOT = REPO_ROOT / "examples" / "007_ctp"
for path in (str(HERE), str(SUPPORT_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import backtrader as bt  # noqa: E402
from backtrader.events import TickEvent  # noqa: E402
from backtrader.stores.btapistore import BtApiStore  # noqa: E402
from backtrader.comminfo import ComminfoFuturesPercent  # noqa: E402
from backtrader.brokers.mixbroker import MixBroker  # noqa: E402
from backtrader.brokers.hft.exchange import SimpleExchangeModel  # noqa: E402

from strategy import PairArbitrageStrategy, close_offset  # noqa: E402,F401
from ctp_example_support import (  # noqa: E402
    add_live_feeds,
    create_live_broker,
    create_live_store,
    run_cerebro_with_timeout,
)
from ctp_example_support import load_config as support_load_config  # noqa: E402

STRATEGY_CLASS = PairArbitrageStrategy
DEFAULT_CONFIG = "config.yaml"

# m (DCE) and rm (CZCE) share the same delivery-month calendar.
PRODUCT_CALENDARS = {"m": (1, 3, 5, 7, 8, 9, 11, 12), "rm": (1, 3, 5, 7, 8, 9, 11, 12)}
CZCE_PRODUCTS = frozenset({"rm"})
MIN_DAYS_TO_EXPIRY = 45
BUSINESS_SUMMARY_VOLATILE_FIELDS = frozenset(
    {
        # TradeLogger is the complete runtime envelope.  Its run id,
        # timestamps and callback counters intentionally vary across an
        # equivalent replay and therefore are not business inputs.
        "trade_logger",
        "business_summary",
        "business_summary_hash",
    }
)
BUSINESS_SUMMARY_VOLATILE_NESTED_FIELDS = frozenset(
    {
        # ``Order.ref`` is process-global in Backtrader.  The raw report keeps
        # it for operator traceability, but an equivalent replay receives a
        # different sequence after another run in the same interpreter.
        "ref",
        "order_refs",
        "pending_order_ref",
    }
)


def _contract_code(product, year, month):
    if product in CZCE_PRODUCTS:
        return f"{product.upper()}{year % 10}{month:02d}"
    return f"{product}{year % 100}{month:02d}"


def dominant_contracts(product, today, count=1):
    """Nearest delivery months clearing the expiry guard (approx day 15)."""
    months = PRODUCT_CALENDARS.get(product.lower())
    if not months:
        raise ValueError(f"Unsupported product {product!r}")
    picked = []
    year, month = today.year, today.month
    while len(picked) < count:
        month += 1
        if month > 12:
            month, year = 1, year + 1
        if month not in months:
            continue
        expiry = dt.date(year, month, 15)
        if (expiry - today).days < MIN_DAYS_TO_EXPIRY:
            continue
        picked.append(_contract_code(product, year, month))
        if len(picked) >= 36:
            break
    if len(picked) < count:
        raise ValueError(f"No live {product} contracts found from {today}")
    return picked


def resolve_symbols(today=None):
    """Dominant contract of each correlated product."""
    today = today or dt.date.today()
    return [dominant_contracts(product, today, count=1)[0] for product in ("m", "rm")]


def load_config(directory=HERE, name=DEFAULT_CONFIG):
    """Load this example's yaml config through the shared 007 support loader."""
    config, _path = support_load_config(name, directory, DEFAULT_CONFIG)
    return config


def configure_commissions(broker, symbols, params):
    """Register per-symbol futures commission/multiplier/margin on the broker.

    Defaults model per-lot commissions for meal-class products and can be
    overridden by the config strategy_params.
    """
    for symbol in symbols:
        broker.addcommissioninfo(
            ComminfoFuturesPercent(
                commission=params.get("commission_rate", 0.0001),
                mult=params.get("multiplier", 10.0),
                margin=params.get("margin_rate", 0.1),
            ),
            name=symbol,
        )


def _trade_logger_console_enabled() -> bool:
    """Real-time console streaming; on by default, opt out with TRADE_LOGGER_CONSOLE=0."""
    return os.getenv("TRADE_LOGGER_CONSOLE", "1").strip().lower() not in ("0", "false", "no", "off")


def _attach_trade_logger(cerebro, log_dir):
    """Attach the generic report owner under a stable strategy-local name."""
    console = _trade_logger_console_enabled()
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(log_dir),
        log_format="json",
        log_to_console=console,
        log_positions=False,
        log_indicators=False,
        log_ticks=console,
        log_bars=console,
        log_value=False,
        log_position_snapshot=False,
    )


def _final_pair_report(strategy):
    """Read the frozen pair-arbitrage extension from TradeLogger."""
    observer = getattr(getattr(strategy, "stats", None), "trade_logger", None)
    final_report = getattr(observer, "final_report", None)
    if not callable(final_report):
        raise RuntimeError("named TradeLogger final report is unavailable")
    generic = final_report()
    if not isinstance(generic, dict):
        raise RuntimeError("TradeLogger did not freeze a final report")
    if generic.get("finalized") is not True:
        raise RuntimeError("TradeLogger final report is not finalized")
    extensions = generic.get("extensions")
    context = extensions.get("pair_arbitrage") if isinstance(extensions, dict) else None
    if not isinstance(context, dict) or not context:
        raise RuntimeError("TradeLogger final report is missing the pair_arbitrage extension")
    if bool(getattr(strategy, "_trade_logger_context_failed_since_success", False)):
        raise RuntimeError("TradeLogger pair_arbitrage extension is stale after a publish failure")
    return {**context, "trade_logger": generic}


def business_summary(report):
    """Return replay-stable pair data without observer or process telemetry."""

    def stable_value(value):
        if isinstance(value, Mapping):
            return {
                key: stable_value(nested)
                for key, nested in value.items()
                if key not in BUSINESS_SUMMARY_VOLATILE_NESTED_FIELDS
            }
        if isinstance(value, (list, tuple)):
            return [stable_value(item) for item in value]
        return value

    return stable_value(
        {key: value for key, value in report.items() if key not in BUSINESS_SUMMARY_VOLATILE_FIELDS}
    )


def business_summary_hash(report):
    """Hash the stable pair business summary, excluding TradeLogger runtime data."""
    payload = json.dumps(
        business_summary(report),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _attach_business_summary(report):
    summary = business_summary(report)
    report["business_summary"] = summary
    report["business_summary_hash"] = business_summary_hash(report)
    return report


# ---------------- synthetic replay ----------------


class ReplayClient:
    """Tick-only input fixture; no order or account engine."""

    def __init__(self, ticks):
        """Hold the frozen synthetic tick stream and empty client state."""
        self.ticks = deque(ticks)
        self.subscriptions = []
        self.connected = False
        self._stop = None
        self._empty_polls = 0

    def set_stop_callback(self, callback):
        """Store cerebro.runstop so tick exhaustion can end the replay."""
        self._stop = callback

    def connect(self):
        """Mark the fake client connected (no network side effects)."""
        self.connected = True

    def disconnect(self):
        """Mark the fake client disconnected."""
        self.connected = False

    def subscribe(self, symbol):
        """Record the requested subscription for replay bookkeeping."""
        self.subscriptions.append(symbol)

    def supports_live_ticks(self, symbol):
        """Declare tick streaming support so the store keeps polling us."""
        return True

    def poll_tick(self, symbol):
        """Pop the next tick for ``symbol``; after 8 empty polls stop Cerebro.

        A tick is popped only when the queue head matches, preserving the
        two-leg interleaving order; consecutive empty polls end the replay
        via runstop.
        """
        if not self.ticks:
            self._empty_polls += 1
            if self._empty_polls > 8 and self._stop:
                self._stop()
            return None
        if self.ticks[0].symbol != symbol:
            return None
        return self.ticks.popleft()


def _defaults():
    return dict(STRATEGY_CLASS.params._getpairs())


def replay_ticks(symbols, scenario, window, step, burst):
    """Generate the interleaved two-leg synthetic tick stream for a scenario.

    profitable: the spread widens then reverts; loss: widens then keeps
    inverting; no_edge: a stable spread. Two-leg ticks interleave per
    ``pair()`` so ReplayClient consumes them in order.
    """
    base = 3500.0
    stamp = 100.0

    def pair(spread):
        nonlocal stamp
        stamp += step
        for symbol, mid in zip(symbols, (base, base - spread)):
            yield TickEvent(
                timestamp=stamp,
                symbol=symbol,
                exchange="",
                asset_type="futures",
                price=mid,
                bid_price=mid - 1.0,
                ask_price=mid + 1.0,
                bid_volume=100,
                ask_volume=100,
                volume=1,
            )

    groups = [pair(30.0) for _ in range(window)]
    if scenario == "no_edge":
        groups += [pair(30.0) for _ in range(window * 3)]
    elif scenario == "loss":
        # Widen (entry) then invert hard: the mean-reversion pair keeps
        # losing, forcing the risk exit path.
        groups += [pair(90.0) for _ in range(burst)]
        groups += [pair(-30.0 - 2.0 * index) for index in range(window * 3)]
    else:
        for _ in range(2):
            groups += [pair(90.0) for _ in range(burst)]
            groups += [pair(32.0) for _ in range(window)]
    for group in groups:
        yield from group


def run_replay(scenario="profitable"):
    """Run the synthetic tick replay on a local MixBroker and freeze its report.

    No network and no exchange orders; the frozen pair_arbitrage extension
    is read from the named TradeLogger at the end, with a business_summary/hash
    attached for equivalent-replay comparison.
    """
    defaults = _defaults()
    window = int(defaults["period"])
    step = 2.0 if defaults["min_interval"] >= 1.0 else 0.05
    burst = int(defaults["confirmations"] * math.ceil(defaults["min_interval"] / step)) + 2
    symbols = resolve_symbols()
    client = ReplayClient(replay_ticks(symbols, scenario, window, step, burst))
    store = BtApiStore(provider="ctp", api=client)
    broker = MixBroker(cash=1_000_000.0, position_mode="net", exchange_model=SimpleExchangeModel())
    configure_commissions(broker, symbols, defaults)
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    for symbol in symbols:
        cerebro.adddata(
            store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Ticks,
                backfill_start=False,
                qcheck=0.01,
            ),
            name=symbol,
        )
    # The replay client stops Cerebro once its synthetic ticks are exhausted.
    client.set_stop_callback(cerebro.runstop)
    with tempfile.TemporaryDirectory(prefix="bt-013-1-replay-") as report_directory:
        _attach_trade_logger(cerebro, Path(report_directory))
        cerebro.addstrategy(STRATEGY_CLASS)
        strategy = cerebro.run(preload=False, runonce=False)[0]
        report = _final_pair_report(strategy)
    report.update(
        scenario=scenario,
        symbols=symbols,
        evidence="Synthetic CTP tick replay; does not establish live profitability",
    )
    return _attach_business_summary(report)


# ---------------- SimNow live ----------------


def run_live(args):
    """Run the SimNow live session (default 7x24) and freeze its final report.

    Symbols can be overridden via --symbols or yaml (dominant legs resolved
    from the delivery calendar by default); connection info is printed first
    (password excluded) and run_timeout_seconds stops the run through
    run_cerebro_with_timeout to freeze the final business report.
    """
    config = load_config(HERE, args.config)
    symbols = (
        [token.strip() for token in args.symbols.split(",")] if args.symbols else resolve_symbols()
    )
    if config.get("symbols") not in (None, ["auto"]):
        symbols = list(config["symbols"])
    store, connection = create_live_store({**config, "symbols": symbols})
    broker = create_live_broker(store, config)
    defaults = _defaults()
    defaults.update(config.get("strategy_params") or {})
    configure_commissions(broker, symbols, defaults)
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    add_live_feeds(cerebro, store, {**config, "symbols": symbols})
    _attach_trade_logger(
        cerebro,
        HERE / "reports" / "trade-logger" / dt.datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    cerebro.addstrategy(STRATEGY_CLASS, **dict(config.get("strategy_params") or {}))
    timeout = float(config.get("run_timeout_seconds", 300))
    print(
        json.dumps(
            {
                "symbols": symbols,
                "connection": {k: v for k, v in connection.items() if k != "password"},
            },
            default=str,
        )
    )
    strategies = run_cerebro_with_timeout(cerebro, timeout)
    report = _final_pair_report(strategies[0])
    report.update(symbols=symbols, mode="simnow_live")
    return _attach_business_summary(report)


def main():
    """Parse CLI args, dispatch replay vs live, print and optionally write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--replay", action="store_true", help="synthetic tick replay")
    parser.add_argument(
        "--scenario", choices=("profitable", "loss", "no_edge"), default="profitable"
    )
    parser.add_argument("--symbols", help="comma-separated override, e.g. m2701,RM701")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.replay:
        report = run_replay(args.scenario)
    else:
        report = run_live(args)
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    printable = {k: v for k, v in report.items() if k not in {"orders", "results"}}
    print(json.dumps(printable, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
