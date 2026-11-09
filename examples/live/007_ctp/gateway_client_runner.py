"""Run a 007 strategy against a separately operated Gateway.

The installed resource provider owns the private key material and returns an
already initialized strategy-local GatewayPendingHost and CURVE profiles.  It
must not create a Gateway, provider, native trading session, or market session.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import threading
from importlib.metadata import entry_points
from pathlib import Path

import yaml

_RESOURCE_GROUP = "bt_api_py.gateway_example_resources"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def load_config(path):
    with path.open("r", encoding="utf-8-sig") as stream:
        value = yaml.safe_load(stream)
    if type(value) is not dict:
        raise ValueError("CONFIG_INVALID")
    return value


def validate_config(config):
    from bt_api_py.gateway_strategy_config import parse_gateway_strategy_config

    if any(name in config for name in ("gateway", "ctp", "direct")):
        raise ValueError("LEGACY_CONFIG_UNSUPPORTED")
    provider = config.get("gateway_resource_provider")
    if type(provider) is not str or not _REF.fullmatch(provider):
        raise ValueError("RESOURCE_PROVIDER_REQUIRED")
    symbols = config.get("symbols")
    contracts = config.get("contracts")
    if (type(symbols) is not list or not symbols or len(set(symbols)) != len(symbols)
            or any(type(symbol) is not str or not symbol for symbol in symbols)
            or type(contracts) is not dict or any(symbol not in contracts for symbol in symbols)):
        raise ValueError("CONTRACTS_INVALID")
    parsed = parse_gateway_strategy_config(config.get("gateway_strategy"))
    instruments = list(parsed.instruments_by_ref.values())
    if sorted(symbols) != sorted(key.native_symbol for key in instruments):
        raise ValueError("INSTRUMENT_SCOPE_INVALID")
    market = parsed.market_settings
    if market is None:
        raise ValueError("MARKET_SETTINGS_REQUIRED")
    for symbol in symbols:
        row = contracts[symbol]
        matches = [key for key in instruments if key.native_symbol == symbol]
        if (type(row) is not dict or len(matches) != 1 or row.get("exchange") != matches[0].venue
                or row.get("quantity_unit") not in ("contracts", "lots", "native")
                or row.get("time_in_force") not in ("GFD", "DAY")
                or type(row.get("price_tick")) not in (int, float)
                or not math.isfinite(row["price_tick"]) or row["price_tick"] <= 0):
            raise ValueError("CONTRACT_RULES_INVALID")
        subscriptions = [item for item in market.subscriptions.values()
                         if item.key.instrument == matches[0] and item.key.channel == "tick"
                         and item.require_source_descriptor]
        if len(subscriptions) != 1:
            raise ValueError("MARKET_BINDING_INVALID")
    for name in ("feed", "broker", "strategy_params", "logging", "trade_logger"):
        if type(config.get(name, {})) is not dict:
            raise ValueError("CONFIG_SECTION_INVALID")
    feed = config.get("feed", {})
    if feed.get("timeframe", "ticks") not in {"ticks", "seconds", "minutes", "days"}:
        raise ValueError("FEED_CONFIG_INVALID")
    if type(feed.get("compression", 1)) is not int or feed.get("compression", 1) <= 0:
        raise ValueError("FEED_CONFIG_INVALID")
    if type(feed.get("backfill_start", False)) is not bool:
        raise ValueError("FEED_CONFIG_INVALID")
    for symbol in symbols:
        row = contracts[symbol]
        for key in ("event_time_max_age", "receive_time_max_age"):
            number = row.get(key, feed.get(key, 2.0))
            if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
                raise ValueError("FEED_CONFIG_INVALID")
        if row.get("incomplete_volume_bars", feed.get("incomplete_volume_bars", "lines")) not in {"lines", "notify_only"}:
            raise ValueError("FEED_CONFIG_INVALID")
        multiplier = row.get("multiplier", 1)
        if type(multiplier) not in (int, float) or not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("CONTRACT_RULES_INVALID")
    clock = feed.get("gateway_clock_verification")
    if clock is not None and clock is not False:
        allowed = {"servers", "validity_seconds", "max_error_bound_ms", "timeout_seconds",
                   "refresh_interval_seconds", "max_wall_jump_ns", "max_latency_seconds",
                   "max_clock_error_ms", "rpc_timeout_seconds"}
        if type(clock) is not dict or set(clock) - allowed:
            raise ValueError("CLOCK_CONFIG_INVALID")
        servers = clock.get("servers")
        if type(servers) is not list or not servers or any(
            type(server) is not str or not server or server.strip() != server for server in servers
        ):
            raise ValueError("CLOCK_CONFIG_INVALID")
    timeout = config.get("run_timeout_seconds", 0)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError("TIMEOUT_INVALID")
    return parsed


def configure_run_logging(config, run_dir):
    """Retain the public example logging controls and redact diagnostics."""
    import logging
    import sys

    from backtrader.utils.redaction import redact_diagnostic

    class RedactingFormatter(logging.Formatter):
        def format(self, record):
            return redact_diagnostic(super().format(record))

    settings = config.get("logging") or {}
    if type(settings) is not dict or set(settings) - {"level", "other_level", "file"}:
        raise ValueError("LOGGING_CONFIG_INVALID")
    levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    level = settings.get("level", "INFO")
    other = settings.get("other_level", "WARNING")
    if not isinstance(level, str) or level.upper() not in levels or not isinstance(other, str) or other.upper() not in levels:
        raise ValueError("LOGGING_CONFIG_INVALID")
    filename = settings.get("file")
    if filename is None:
        handler = logging.StreamHandler(sys.stderr)
    elif isinstance(filename, str) and filename.strip():
        path = Path(filename).expanduser()
        path = path if path.is_absolute() else run_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    else:
        raise ValueError("LOGGING_CONFIG_INVALID")
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(other.upper())
    logging.getLogger("bt_api_ctp").setLevel(level.upper())


def resolve_resources(name, *, config, run_dir, first_init, upgrade_state, security_files):
    """Resolve only explicitly installed trusted code; never import a YAML path."""
    if name == "local_files":
        from gateway_local_resources import load_local_resources

        return load_local_resources(config, strategy_dir=run_dir, first_init=first_init,
                                    upgrade_state=upgrade_state, security_files=security_files)
    if upgrade_state:
        raise RuntimeError("EXTERNAL_PROVIDER_UPGRADE_UNSUPPORTED")
    discovered = entry_points()
    matches = list(discovered.select(group=_RESOURCE_GROUP, name=name)) if hasattr(discovered, "select") else [
        item for item in discovered.get(_RESOURCE_GROUP, ()) if item.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError("RESOURCE_PROVIDER_UNAVAILABLE")
    provider = matches[0].load()
    if not callable(provider):
        raise RuntimeError("RESOURCE_PROVIDER_INVALID")
    result = provider(config=config, strategy_dir=run_dir, first_init=first_init)
    if type(result) is not tuple or len(result) != 2:
        raise RuntimeError("RESOURCE_PROVIDER_INVALID")
    return result


def main(strategy, title, run_dir, argv=None):
    parser = argparse.ArgumentParser(description=f"Run {title} using an independent Gateway")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="validate public config offline")
    parser.add_argument("--first-init", action="store_true", help="initialize local identity only, then stop")
    parser.add_argument("--upgrade-state", action="store_true", help="explicitly upgrade local state, then stop")
    parser.add_argument("--run-seconds", type=float, default=None)
    args = parser.parse_args(argv)
    run_dir = Path(run_dir).resolve()
    path = Path(args.config).expanduser()
    path = path if path.is_absolute() else run_dir / path
    try:
        config = load_config(path)
        parsed = validate_config(config)
        if config["gateway_resource_provider"] == "local_files":
            from gateway_local_resources import validate_security_file_config

            validate_security_file_config(parsed, config.get("gateway_resource_files"), run_dir)
    except Exception:
        print(json.dumps({"status": "BLOCKED", "error_code": "GATEWAY_CONFIG_INVALID"}))
        return 2
    if args.dry_run:
        print(json.dumps({"status": "PASS", "mode": "offline_config_validation",
                          "strategy": strategy.__name__, "symbols": config["symbols"]}))
        return 0

    try:
        configure_run_logging(config, run_dir)
    except Exception:
        print(json.dumps({"status": "BLOCKED", "error_code": "LOGGING_CONFIG_INVALID"}))
        return 2

    # A provider may read locally protected key files but no key or provider
    # configuration is ever printed or passed in command-line arguments.
    try:
        host, profiles = resolve_resources(config["gateway_resource_provider"],
            config=parsed, run_dir=run_dir, first_init=args.first_init,
            upgrade_state=args.upgrade_state, security_files=config.get("gateway_resource_files"))
    except Exception as exc:
        from gateway_local_resources import ResourceSetupRequired

        if isinstance(exc, ResourceSetupRequired):
            print(json.dumps({"status": "SETUP_REQUIRED", "error_code": exc.code}))
            return 2
        print(json.dumps({"status": "BLOCKED", "error_code": "GATEWAY_RESOURCES_UNAVAILABLE"}))
        return 2

    import backtrader as bt
    from backtrader.live_trading import stop_on_terminate
    from backtrader.stores.btapistore import BtApiStore

    instruments = {key.native_symbol: key for key in parsed.instruments_by_ref.values()}
    contracts = config["contracts"]
    metadata = {symbol: {"instrument_key": instruments[symbol], "exchange_name": parsed.exchange_name,
                         "quantity_unit": contracts[symbol]["quantity_unit"],
                         "time_in_force": contracts[symbol]["time_in_force"],
                         "price_tick": contracts[symbol]["price_tick"],
                         "multiplier": contracts[symbol].get("multiplier", 1)}
                for symbol in config["symbols"]}
    try:
        store = BtApiStore(config={"gateway_strategy": config["gateway_strategy"]},
                           gateway_host=host, gateway_security_profiles=profiles,
                           symbol_routes={symbol: parsed.exchange_name for symbol in config["symbols"]},
                           contract_metadata=metadata)
        broker = store.getbroker(**config.get("broker", {}))
        for symbol, row in contracts.items():
            if symbol in instruments:
                broker.setcommission(commission=0.0, margin=1.0, mult=float(row.get("multiplier", 1)), name=symbol)
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.setbroker(broker)
        feed_defaults = dict(config.get("feed", {}))
        timeframe = {"ticks": bt.TimeFrame.Ticks, "seconds": bt.TimeFrame.Seconds,
                     "minutes": bt.TimeFrame.Minutes, "days": bt.TimeFrame.Days}
        for symbol in config["symbols"]:
            options = dict(feed_defaults)
            for key in ("event_time_max_age", "receive_time_max_age", "incomplete_volume_bars"):
                if key in contracts[symbol]:
                    options[key] = contracts[symbol][key]
            frame = timeframe[options.pop("timeframe", "ticks")]
            compression = options.pop("compression", 1)
            options.setdefault("backfill_start", False)
            options.setdefault("price_tick", contracts[symbol]["price_tick"])
            data = store.getdata(dataname=symbol, timeframe=frame, compression=compression, **options)
            cerebro.adddata(data, name=symbol)
        cerebro.addstrategy(strategy, **config.get("strategy_params", {}))
        logger_config = dict(config.get("trade_logger") or {})
        if logger_config.pop("enabled", True):
            import datetime

            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = (path.parent / "logs" / path.stem / stamp).resolve()
            for key in ("log_orders", "log_trades", "log_positions", "log_signals", "log_errors",
                        "log_value", "log_system", "log_position_snapshot"):
                logger_config.setdefault(key, True)
            logger_config.setdefault("log_format", "json")
            logger_config.setdefault("log_to_console", False)
            cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(log_dir), **logger_config)
        seconds = args.run_seconds if args.run_seconds is not None else float(config.get("run_timeout_seconds", 0))
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("TIMEOUT_INVALID")
        timer = None
        with stop_on_terminate(cerebro):
            if seconds:
                timer = threading.Timer(seconds, cerebro.runstop)
                timer.daemon = True
                timer.start()
            try:
                cerebro.run()
            finally:
                if timer is not None:
                    timer.cancel()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": type(exc).__name__}))
        return 2
    print(json.dumps({"status": "STOPPED", "mode": "gateway"}))
    return 0
