#!/usr/bin/env python
"""CTP SimNow live runner, direct mode: ``SingleSymbolTickStrategy`` (tickbroker_single_symbol).

Direct mode (iteration 62): ``BtApiStore`` -> bt_api_py ``BtApi`` -> CTP, with
the SDK write admission enabled for ``CTP___FUTURE`` and no optional execution
component.  ``BtApiBroker`` then runs its direct path:

* this directory is the strategy instance: ``state/`` holds its UUID, local
  order sequence, pending markers and waiting orders, and
  ``logs/current_position.yaml`` is the reconciliation snapshot the Broker
  writes atomically with every fill;
* the very first start needs ``--first-init`` and a completely flat account
  without working orders; every later start reconciles the snapshot with the
  account before any order is allowed (see README.md);
* TradeLogger writes human-readable logs per run under
  ``logs/<config>/<timestamp>/``.

Credentials come from ``SIMNOW_USER_ID`` / ``SIMNOW_PASSWORD`` (or the
lower-case names) in the environment or in ``--env-file``; they are never
printed.  ``--dry-run`` validates ``config.yaml`` offline.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import threading
from pathlib import Path

import backtrader as bt
import yaml

from single_symbol_tick_strategy import SingleSymbolTickStrategy

RUN_DIR = Path(__file__).resolve().parent
ROUTE = "CTP___FUTURE"
EXIT_PASS = 0
EXIT_BLOCKED = 2
STRATEGY = SingleSymbolTickStrategy
TITLE = "tickbroker_single_symbol (direct)"


def load_config(config_arg, base_dir, default_name):
    path = Path(config_arg or default_name)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(handle) or {}, path
        if path.suffix.lower() == ".json":
            return json.load(handle), path
    raise ValueError(f"Unsupported config format: {path}")


def parse_timeframe(value):
    mapping = {
        "ticks": bt.TimeFrame.Ticks,
        "seconds": bt.TimeFrame.Seconds,
        "minutes": bt.TimeFrame.Minutes,
        "days": bt.TimeFrame.Days,
    }
    normalized = str(value or "ticks").strip().lower()
    if normalized not in mapping:
        raise ValueError(f"Unsupported timeframe: {value}")
    return mapping[normalized]


def validate_live_config(config):
    symbols = list(config.get("symbols") or [])
    if not symbols:
        raise ValueError("config requires at least one symbol")
    contracts = dict(config.get("contracts") or {})
    missing = [
        symbol
        for symbol in symbols
        if not isinstance(contracts.get(symbol), dict)
        or not contracts[symbol].get("exchange")
        or not float(contracts[symbol].get("price_tick") or 0) > 0
    ]
    if missing:
        raise ValueError(f"contracts must give exchange and price_tick of: {', '.join(missing)}")
    parse_timeframe(dict(config.get("feed") or {}).get("timeframe", "ticks"))
    if not isinstance(config.get("strategy_params") or {}, dict):
        raise ValueError("strategy_params must be a mapping")
    if not isinstance(config.get("broker") or {}, dict):
        raise ValueError("broker must be a mapping")
    return symbols


def load_credentials(env_file):
    """SimNow credentials from the environment or an env file (never printed)."""
    names = {"user_id": ("SIMNOW_USER_ID", "simnow_user_id"),
             "password": ("SIMNOW_PASSWORD", "simnow_password")}
    values = {}
    for key, candidates in names.items():
        for name in candidates:
            if os.environ.get(name):
                values[key] = os.environ[name]
                break
    if env_file and len(values) < 2:
        for line in Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, value = line.split("=", 1)
            name = name.strip().removeprefix("export ").strip()
            for key, candidates in names.items():
                if name in candidates and key not in values:
                    values[key] = value.strip().strip('"').strip("'")
    if len(values) < 2 or not all(values.values()):
        raise LookupError("SimNow credentials not found (SIMNOW_USER_ID / SIMNOW_PASSWORD)")
    return values


def create_store(config, credentials):
    """BtApiStore in SDK direct mode: write admission on, no execution component."""
    from backtrader.stores.btapistore import BtApiStore

    ctp = dict(config.get("ctp") or {})
    direct = dict(config.get("direct") or {})
    exchange_kwargs = {
        ROUTE: {
            "broker_id": str(ctp.get("broker_id", "9999")),
            "user_id": credentials["user_id"],
            "password": credentials["password"],
            "app_id": str(ctp.get("app_id", "simnow_client_test")),
            "auth_code": str(ctp.get("auth_code", "0000000000000000")),
            "ctp_env_profile": str(ctp.get("env_profile", "set1_group1_vpn")),
            "private_topic_mode": str(ctp.get("private_topic_mode", "restart")),
        }
    }
    from bt_api_base.market_protocol import MarketInstrumentKey

    environment = str(ctp.get("instrument_environment", "demo"))
    contracts = dict(config.get("contracts") or {})
    contract_metadata = {
        symbol: {
            "instrument_key": MarketInstrumentKey(
                "ctp", str(contracts[symbol]["exchange"]), environment, "future", symbol, symbol
            ),
            "price_tick": float(contracts[symbol]["price_tick"]),
            "multiplier": float(contracts[symbol].get("multiplier") or 1),
        }
        for symbol in config["symbols"]
    }
    return BtApiStore(
        provider="ctp",
        contract_metadata=contract_metadata,
        exchange_kwargs=exchange_kwargs,
        write_admission={ROUTE: bool(direct.get("write_admission", True))},
        market_clock_verification=direct.get("market_clock_verification", True),
        symbol_routes={symbol: ROUTE for symbol in config["symbols"]},
    )


def create_broker(store, config, first_init):
    """``BtApiBroker`` (direct path selected by the Store) bound to this directory."""
    settings = dict(config.get("broker") or {})
    settings.setdefault("position_mode", "net")
    broker = store.getbroker(strategy_dir=str(RUN_DIR), first_init=bool(first_init), **settings)
    for symbol, spec in dict(config.get("contracts") or {}).items():
        # Futures projection for BT trades/PnL: no local commission estimate.
        broker.setcommission(
            commission=0.0, margin=1.0, mult=float(spec.get("multiplier") or 1), name=symbol
        )
    return broker


def add_feeds(cerebro, store, config):
    feed_config = dict(config.get("feed") or {})
    timeframe = parse_timeframe(feed_config.pop("timeframe", "ticks"))
    compression = int(feed_config.pop("compression", 1))
    backfill_start = bool(feed_config.pop("backfill_start", False))
    feeds = []
    for symbol in config["symbols"]:
        data = store.getdata(
            dataname=symbol,
            timeframe=timeframe,
            compression=compression,
            backfill_start=backfill_start,
            **feed_config,
        )
        cerebro.adddata(data, name=symbol)
        feeds.append(data)
    return feeds


def attach_trade_logger(cerebro, config, config_path):
    """Human-readable logs per run; never the reconciliation snapshot."""
    settings = dict(config.get("trade_logger") or {})
    if not bool(settings.pop("enabled", True)):
        return None
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = (config_path.parent / "logs" / config_path.stem / stamp).resolve()
    for key in ("log_orders", "log_trades", "log_positions", "log_signals", "log_errors",
                "log_value", "log_system", "log_position_snapshot"):
        settings.setdefault(key, True)
    settings.setdefault("log_format", "json")
    settings.setdefault("log_to_console", False)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(log_dir), **settings)
    return log_dir


def run_with_timeout(cerebro, seconds):
    if float(seconds) <= 0:
        return cerebro.run()
    timer = threading.Timer(float(seconds), cerebro.runstop)
    timer.daemon = True
    timer.start()
    try:
        return cerebro.run()
    finally:
        timer.cancel()


def report(status, **fields):
    record = {"status": status, **fields}
    print(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"Run the {TITLE} live example (CTP SimNow)")
    parser.add_argument("--config", default="config.yaml", help="config path (relative to here)")
    parser.add_argument("--dry-run", action="store_true", help="validate the config offline")
    parser.add_argument("--first-init", action="store_true",
                        help="explicit first initialization (needs a flat account, D62-13)")
    parser.add_argument("--env-file", default=None, help="env file with SimNow credentials")
    parser.add_argument("--run-seconds", type=float, default=None,
                        help="stop after N seconds (default: run_timeout_seconds in config)")
    args = parser.parse_args(argv)

    config, config_path = load_config(args.config, RUN_DIR, "config.yaml")
    symbols = validate_live_config(config)
    if args.dry_run:
        print(f"Dry run OK for {config_path}")
        print(f"Strategy: {STRATEGY.__name__}; symbols: {', '.join(symbols)}")
        print(f"State directory: {RUN_DIR / 'state'}")
        return EXIT_PASS

    try:
        credentials = load_credentials(args.env_file)
    except (LookupError, OSError) as exc:
        report("BLOCKED", error_code="credentials_unavailable", detail=str(exc))
        return EXIT_BLOCKED

    from backtrader.brokers._btapi_direct_mode import DirectModeError

    store = create_store(config, credentials)
    credentials.clear()
    broker = create_broker(store, config, args.first_init)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    add_feeds(cerebro, store, config)
    cerebro.addstrategy(STRATEGY, **dict(config.get("strategy_params") or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)
    seconds = args.run_seconds
    if seconds is None:
        seconds = float(config.get("run_timeout_seconds", 0.0))
    print(f"Running {TITLE}: symbols={', '.join(symbols)} logs={log_dir} timeout={seconds:.0f}s",
          flush=True)
    status, code = "PASS", EXIT_PASS
    try:
        run_with_timeout(cerebro, seconds)
    except DirectModeError as exc:
        status, code = "BLOCKED", EXIT_BLOCKED
        report(status, error_code=exc.code, detail=exc.detail)
    finally:
        report(
            "SUMMARY" if status == "PASS" else status,
            reconcile=broker.get_direct_reconcile_report(),
            writes_blocked=broker.direct_writes_blocked() if broker._direct_active() else None,
            shutdown=getattr(broker, "_shutdown_summary", None),
            refresh_counts=broker.get_direct_refresh_counts(),
            cash=broker.getcash(),
            value=broker.getvalue(),
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
