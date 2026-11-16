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
import sys
import threading
import uuid
from collections.abc import Mapping
from importlib.metadata import entry_points
from pathlib import Path

import yaml

# The shared D67-01 calendar gate lives next to this runner.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

_RESOURCE_GROUP = "bt_api_py.gateway_example_resources"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class GatewayExecutionConfigUnsupported(ValueError):
    """A top-level Execution selection cannot be used by this Gateway runner."""


def run_id_from_cli(value):
    """Canonicalise ``--run-id``; the runtime passes the UUID it registered."""
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise argparse.ArgumentTypeError("run-id must be a UUID") from None


def contract_broker_summary(summary):
    """Translate the Gateway shutdown summary to the run contract's statuses.

    The Gateway stop reports session/Store facts (``PASS``/``INCOMPLETE``/
    ``FAIL`` plus the nested ``gateway_working_orders``), while the run
    contract reads the direct-mode stop vocabulary from
    ``broker.get_shutdown_summary()``.  Only a ``PASS`` shutdown with no
    unresolved working order is claimed clean; unresolved orders are
    ``STOPPED_WITH_WORKING_ORDERS``; every other combination stays ``UNKNOWN``
    (never a clean stop).  This bridge is example-local: the Gateway stop needs
    its own contract status in iteration 66 before this translation can move
    into the product.
    """
    if not isinstance(summary, Mapping):
        return None
    working = summary.get("gateway_working_orders")
    working = working if isinstance(working, Mapping) else None
    unresolved = working.get("unresolved_working_orders") if working is not None else None
    gateway_status = summary.get("status")
    translated = dict(summary, gateway_status=gateway_status)
    if isinstance(unresolved, int) and not isinstance(unresolved, bool) and unresolved > 0:
        return dict(
            translated,
            status="STOPPED_WITH_WORKING_ORDERS",
            unresolved_working_orders=unresolved,
        )
    if gateway_status == "PASS" and unresolved == 0:
        return dict(translated, status="STOPPED")
    return dict(translated, status="UNKNOWN")


def load_config(path):
    with path.open("r", encoding="utf-8-sig") as stream:
        value = yaml.safe_load(stream)
    if type(value) is not dict:
        raise ValueError("CONFIG_INVALID")
    return value


def validate_config(config):
    if any(name in config for name in ("gateway", "ctp", "direct")):
        raise ValueError("LEGACY_CONFIG_UNSUPPORTED")
    if "risk" in config:
        # Risk is selected only as gateway_strategy.risk (D64-01).
        raise ValueError("RISK_SELECTION_INVALID")
    if "execution" in config:
        raise GatewayExecutionConfigUnsupported("GATEWAY_TOP_LEVEL_EXECUTION_UNSUPPORTED")

    from bt_api_py.gateway_strategy_config import parse_gateway_strategy_config

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
    parser.add_argument("--run-id", type=run_id_from_cli, default=None,
                        help="run UUID (default: generated; bt_api_runtime passes its own)")
    parser.add_argument("--heartbeat-interval", type=float, default=None,
                        help="heartbeat interval seconds (default: 1.0; runtime passes it)")
    parser.add_argument("--stop-request-file", default=None,
                        help="opt-in runtime stop-request file (bt_api_runtime passes it)")
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
    except GatewayExecutionConfigUnsupported:
        print(json.dumps({"status": "BLOCKED", "error_code": "GATEWAY_TOP_LEVEL_EXECUTION_UNSUPPORTED",
                          "message": "Top-level execution configuration is unsupported by this Gateway runner."}))
        return 2
    except Exception:
        print(json.dumps({"status": "BLOCKED", "error_code": "GATEWAY_CONFIG_INVALID"}))
        return 2
    # D67-01 calendar gate, shared with the 11 direct entries: a Gateway live
    # start without a declared calendars.root is refused before resources,
    # Store or Broker work; --dry-run only reports the configuration problem.
    from calendar_gate import CalendarGateRefusal, check_gateway_calendar

    try:
        gate = check_gateway_calendar(config, config_file=path, dry_run=args.dry_run)
    except CalendarGateRefusal as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": exc.code}))
        return 2
    if args.dry_run:
        if gate.kind == "unconfigured":
            calendar_status = "calendar_root_unconfigured"
        elif gate.kind == "package_seed":
            calendar_status = "package_seed_declared_not_bound"
        else:
            calendar_status = "external_directory_configured_not_bound"
        print(json.dumps({"status": "PASS", "mode": "offline_config_validation",
                          "strategy": strategy.__name__, "symbols": config["symbols"],
                          "calendar": calendar_status}))
        return 0
    if gate.code is not None:
        print(json.dumps({"status": "BLOCKED", "error_code": gate.code}))
        return 2

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
        # Gateway mode routes by the configured exchange_name; the Store refuses
        # direct-mode options such as symbol_routes (GATEWAY_CONFIGURATION_CONFLICT).
        store = BtApiStore(config={"gateway_strategy": config["gateway_strategy"]},
                           gateway_host=host, gateway_security_profiles=profiles,
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
        feeds = []
        # D67-11 Feed calendar scope is intentionally not wired here: in Gateway
        # mode the Store refuses the read-only calendar query with
        # STORE_UNAVAILABLE (`BtApiStore.trading_calendar_query` requires the SDK
        # direct mode), so passing calendar_* would only rename a known gap and
        # could imply a bound session. Wire the explicit scope here once the
        # Gateway exposes its own read-only calendar query; until then the Feed
        # keeps answering CALENDAR_SCOPE_UNAVAILABLE and never guesses a session.
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
            feeds.append(data)
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
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_code": type(exc).__name__}))
        return 2

    # Iteration 66, §5.2 B2/B3/B5: the run-status contract writes the heartbeat
    # and the final summary; the strategy process never imports bt_api_runtime.
    from backtrader.live_trading import DEFAULT_HEARTBEAT_INTERVAL_S, RunStatusWriter
    from backtrader.live_state import load_identity

    stop_request_file = args.stop_request_file
    if stop_request_file is not None:
        # Opt-in stop-file channel, bound to this exact strategy and run.
        if args.run_id is None:
            print(json.dumps({"status": "BLOCKED", "error_code": "stop_request_requires_run_id"}))
            return 2
        try:
            stop_request_strategy_uuid = load_identity(run_dir).strategy_uuid
        except Exception:
            print(json.dumps({"status": "BLOCKED", "error_code": "stop_request_identity_unavailable"}))
            return 2
    else:
        stop_request_strategy_uuid = None
    termination = stop_on_terminate(
        cerebro,
        stop_request_file=stop_request_file,
        stop_request_strategy_uuid=stop_request_strategy_uuid,
        stop_request_run_id=args.run_id,
    )
    contract = RunStatusWriter(
        run_dir,
        run_id=args.run_id,
        heartbeat_interval_s=(
            DEFAULT_HEARTBEAT_INTERVAL_S
            if args.heartbeat_interval is None
            else args.heartbeat_interval
        ),
        broker=broker,
        feeds=feeds,
        stop_request_provider=termination.request_state,
    )
    contract.start()

    class RunProgress(bt.Analyzer):
        """Stamp main-loop progress and the LIVE phase into the status file."""

        params = (("contract", None),)

        def start(self):
            self.p.contract.set_phase("LIVE")

        def next(self):
            self.p.contract.loop_progress()

    cerebro.addanalyzer(RunProgress, contract=contract)
    failure = None
    timer = None
    try:
        with termination:
            if seconds:
                timer = threading.Timer(seconds, cerebro.runstop)
                timer.daemon = True
                timer.start()
            cerebro.run()
    except KeyboardInterrupt as exc:
        # SIGINT keeps propagating; the summary still records the crash.
        failure = exc
        raise
    except Exception as exc:
        failure = exc
        print(json.dumps({"status": "CRASHED", "error_code": type(exc).__name__}))
    finally:
        if timer is not None:
            timer.cancel()
        conclusion = contract.finish(
            broker_summary=contract_broker_summary(broker.get_shutdown_summary()),
            exception=failure,
        )
    print(json.dumps({"status": conclusion.outcome, "mode": "gateway",
                      "exit_code": conclusion.exit_code}))
    return conclusion.exit_code
