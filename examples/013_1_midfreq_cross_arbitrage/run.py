"""Runner for the mid-frequency cross-product pair arbitrage example.

复用 ``examples/007_ctp/ctp_example_support`` 的 SimNow 接线与配置加载；
``--replay`` 使用合成 tick 在本地 MixBroker 上验证策略状态机。
"""

import argparse
import datetime as dt
import json
import math
import sys
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
    for symbol in symbols:
        broker.addcommissioninfo(
            ComminfoFuturesPercent(
                commission=params.get("commission_rate", 0.0001),
                mult=params.get("multiplier", 10.0),
                margin=params.get("margin_rate", 0.1),
            ),
            name=symbol,
        )


# ---------------- synthetic replay ----------------


class ReplayClient:
    """Tick-only input fixture; no order or account engine."""

    def __init__(self, ticks):
        self.ticks = deque(ticks)
        self.subscriptions = []
        self.connected = False
        self._stop = None
        self._empty_polls = 0

    def set_stop_callback(self, callback):
        self._stop = callback

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def subscribe(self, symbol):
        self.subscriptions.append(symbol)

    def supports_live_ticks(self, symbol):
        return True

    def poll_tick(self, symbol):
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
    cerebro.addstrategy(STRATEGY_CLASS)
    strategy = cerebro.run(preload=False, runonce=False)[0]
    report = strategy.report()
    report.update(
        scenario=scenario,
        symbols=symbols,
        evidence="Synthetic CTP tick replay; does not establish live profitability",
    )
    return report


# ---------------- SimNow live ----------------


def run_live(args):
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
    report = strategies[0].report()
    report.update(symbols=symbols, mode="simnow_live")
    return report


def main():
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
