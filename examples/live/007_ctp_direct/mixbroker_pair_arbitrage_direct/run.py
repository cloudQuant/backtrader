#!/usr/bin/env python
"""CTP SimNow live runner, direct mode: ``PairMixArbitrageStrategy`` (mixbroker_pair_arbitrage).

Direct mode (iteration 62 / Split): ``DirectBtApiStore`` (via
``create_direct_store``) -> bt_api_py ``BtApi`` -> CTP, with the SDK write
admission enabled for ``CTP___FUTURE`` and zero optional SDK service
subpackages.  ``DirectBtApiBroker`` and ``DirectBtApiFeed`` then run the strict
direct path bound by an immutable ``LiveRunBinding(mode='direct')``:

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
import math
import os
import sys
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path

import backtrader as bt
from backtrader.live_trading import (
    DEFAULT_HEARTBEAT_INTERVAL_S,
    RunStatusWriter,
    stop_on_terminate,
)
from backtrader.live_state import LiveStateError, load_identity
import yaml

from pair_mix_arbitrage_strategy import PairMixArbitrageStrategy

# The shared D67-01 calendar gate and D67-11 Feed scope live in the parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calendar_feed_scope import (
    CalendarFeedScopeRefusal,
    check_direct_feed_scope,
    store_calendar_section,
)
from calendar_gate import CalendarGateRefusal, check_direct_calendar

RUN_DIR = Path(__file__).resolve().parent
ROUTE = "CTP___FUTURE"
EXIT_PASS = 0
EXIT_BLOCKED = 2
STRATEGY = PairMixArbitrageStrategy
TITLE = "mixbroker_pair_arbitrage (direct)"


def run_id_from_cli(value):
    """Canonicalise ``--run-id``; the runtime passes the UUID it registered."""
    try:
        return str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise argparse.ArgumentTypeError("run-id must be a UUID") from None


class RunProgress(bt.Analyzer):
    """Publish main-loop progress and the LIVE phase to ``state/run_status.json``.

    The contract's heartbeat thread performs every file write; this runs once
    per evaluated bar and only stamps an in-memory UTC time, so the per-bar
    path stays free of file I/O (iteration 66, §5.2 B2).
    """

    params = (("contract", None),)

    def start(self):
        # Called once the Broker and data started: the run is in its loop.
        self.p.contract.set_phase("LIVE")

    def next(self):
        self.p.contract.loop_progress()


# Feed settings a contract may override under contracts.<symbol>: the feed: section is
# the venue/strategy default (D62-28: per venue, strategy and contract; decision 2 of
# 2026-11-06 for incomplete_volume_bars). BtApiFeed defaults when a key is absent:
FEED_DEFAULTS = {
    "event_time_max_age": 2.0,
    "receive_time_max_age": 2.0,
    "incomplete_volume_bars": "lines",
}
CONTRACT_FEED_KEYS = tuple(FEED_DEFAULTS)


def feed_settings(config, symbol):
    """The ``feed:`` section with the overrides of ``contracts.<symbol>`` applied."""
    settings = dict(config.get("feed") or {})
    contract = dict(config.get("contracts") or {}).get(symbol) or {}
    settings.update({key: contract[key] for key in CONTRACT_FEED_KEYS if key in contract})
    return settings


def validate_feed_settings(scope, values):
    for key in ("event_time_max_age", "receive_time_max_age"):
        value = values.get(key, FEED_DEFAULTS[key])
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{scope}.{key} must be a positive number of seconds")
    if values.get("incomplete_volume_bars", "lines") not in ("lines", "notify_only"):
        raise ValueError(f"{scope}.incomplete_volume_bars must be lines or notify_only")


def describe_feed(config, symbol):
    """Effective per-contract feed settings, printed at startup."""
    settings = feed_settings(config, symbol)
    return " ".join(f"{key}={settings.get(key, FEED_DEFAULTS[key])}" for key in CONTRACT_FEED_KEYS)


def load_config(config_arg, base_dir, default_name):
    path = Path(config_arg or default_name)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(handle), path
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
    from backtrader.stores.btapi_composition import (
        validate_live_config as validate_product_live_config,
    )

    if config.get("mode") != "direct":
        raise ValueError("direct runner requires explicit mode: direct")
    validate_product_live_config(config)
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
    validate_feed_settings("feed", dict(config.get("feed") or {}))
    for symbol in symbols:
        validate_feed_settings(f"contracts.{symbol}", feed_settings(config, symbol))
    logging_settings(config)
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


def configure_catalog_cache(config):
    """Point the CTP instrument-catalog cache at ``ctp.catalog_cache_dir`` (I62-12).

    Optional. A relative path is resolved against this folder, so the same
    ``config.yaml`` works on Windows, Linux and macOS; unset keeps the
    provider's default (the user cache directory). The provider reads it from
    ``BT_API_CTP_CATALOG_CACHE_DIR``, set here before the Store is built.
    """
    value = dict(config.get("ctp") or {}).get("catalog_cache_dir")
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (RUN_DIR / path).resolve()
    os.environ["BT_API_CTP_CATALOG_CACHE_DIR"] = str(path)
    return path


# Process logging (iteration 62, D62-38 point 7): the bt_api_ctp loggers report front
# connect/disconnect, login and market-source recovery at INFO (re-login lines carry
# reason=... and retry_in=...; they never print a user id or a password). Python's
# last-resort handler shows WARNING and above only, so run.py installs one handler.
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOGGING_DEFAULTS = {"level": "INFO", "other_level": "WARNING", "file": None}


def logging_settings(config):
    """The validated ``logging:`` section: bt_api_ctp level, every other logger, file."""
    section = config.get("logging")
    section = {} if section is None else section
    if not isinstance(section, dict):
        raise ValueError("logging must be a mapping")
    unknown = sorted(str(key) for key in set(section) - set(LOGGING_DEFAULTS))
    if unknown:
        raise ValueError(f"unknown logging keys: {', '.join(unknown)}")
    settings = {**LOGGING_DEFAULTS, **section}
    for key in ("level", "other_level"):
        value = settings[key]
        if not isinstance(value, str) or value.strip().upper() not in LOG_LEVELS:
            raise ValueError(f"logging.{key} must be one of {', '.join(LOG_LEVELS)}")
        settings[key] = value.strip().upper()
    path = settings["file"]
    if path is not None:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("logging.file must be a file path")
        path = Path(path.strip()).expanduser()
        settings["file"] = path if path.is_absolute() else (RUN_DIR / path).resolve()
    return settings


def describe_logging(config):
    """Effective logging settings, printed by --dry-run and at startup."""
    settings = logging_settings(config)
    target = settings["file"] or "stderr"
    return f"bt_api_ctp={settings['level']} other={settings['other_level']} to={target}"


def configure_run_logging(config):
    """One handler (stderr or ``logging.file``) for the bt_api_ctp lines and the rest.

    ``bt_api_ctp`` loggers use ``logging.level``; every other logger, including
    backtrader's own (silent until configured), uses ``logging.other_level``.
    Messages also pass backtrader's credential redaction (a second defence).
    """
    import logging
    import sys

    from backtrader.utils.redaction import redact_diagnostic

    class RedactingFormatter(logging.Formatter):
        def format(self, record):
            return redact_diagnostic(super().format(record))

    settings = logging_settings(config)
    if settings["file"] is not None:
        settings["file"].parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(settings["file"], encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(settings["other_level"])
    logging.getLogger("bt_api_ctp").setLevel(settings["level"])
    bt.configure_logging(level=settings["other_level"], console=False, propagate=True)
    return describe_logging(config)


def create_store(config, credentials, config_path=None):
    """DirectBtApiStore via the single composition root: write admission on, no optional service packages."""
    configure_catalog_cache(config)
    from backtrader.stores.btapi_composition import create_direct_store

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
            "private_topic_mode": str(ctp.get("private_topic_mode", "quick")),
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
    # ``calendars.feed_scope`` is consumer-side; the Store's SDK parser accepts
    # only root/review_mode, so forward that exact subset.
    calendar_section = store_calendar_section(config)
    return create_direct_store(
        config=config,
        provider="ctp",
        route=ROUTE,
        calendar_config_file=config_path if calendar_section is not None else None,
        calendar_config={"calendars": calendar_section} if calendar_section is not None else None,
        calendar_ctp_routes=(ROUTE,) if calendar_section is not None else None,
        contract_metadata=contract_metadata,
        exchange_kwargs=exchange_kwargs,
        write_admission={ROUTE: bool(direct.get("write_admission", True))},
        market_clock_verification=direct.get("market_clock_verification", True),
        symbol_routes={symbol: ROUTE for symbol in config["symbols"]},
    )


def create_broker(store, config, first_init):
    """``DirectBtApiBroker`` (strict direct path) bound to this directory."""
    settings = dict(config.get("broker") or {})
    settings.setdefault("position_mode", "net")
    broker = store.getbroker(strategy_dir=str(RUN_DIR), first_init=bool(first_init), **settings)
    for symbol, spec in dict(config.get("contracts") or {}).items():
        # Futures projection for BT trades/PnL: no local commission estimate.
        broker.setcommission(
            commission=0.0, margin=1.0, mult=float(spec.get("multiplier") or 1), name=symbol
        )
    return broker


def add_feeds(cerebro, store, config, calendar_scopes=None):
    feeds = []
    for symbol in config["symbols"]:
        # The feed: section with this contract's overrides (D62-28, README).
        feed_config = feed_settings(config, symbol)
        timeframe = parse_timeframe(feed_config.pop("timeframe", "ticks"))
        compression = int(feed_config.pop("compression", 1))
        backfill_start = bool(feed_config.pop("backfill_start", False))
        # D67-11: one explicit read-only calendar scope per Feed, declared in
        # calendars.feed_scope. Without it the Feed answers
        # CALENDAR_SCOPE_UNAVAILABLE (fail closed, no symbol->contract guess).
        options = dict(feed_config)
        options.update((calendar_scopes or {}).get(symbol, {}))
        data = store.getdata(
            dataname=symbol,
            timeframe=timeframe,
            compression=compression,
            backfill_start=backfill_start,
            **options,
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


def run_with_timeout(cerebro, seconds, termination):
    """Run until ``seconds`` pass (0: no limit) or a SIGTERM arrives; both stop gracefully.

    ``termination`` (``stop_on_terminate``) turns SIGTERM, and SIGBREAK on Windows,
    into ``cerebro.runstop()`` while the run lasts, so the Broker's stop path runs
    (README, "停止"). SIGINT (Ctrl+C) is unchanged.
    """
    with termination:
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
    parser.add_argument("--run-id", type=run_id_from_cli, default=None,
                        help="run UUID (default: generated; bt_api_runtime passes its own)")
    parser.add_argument("--run-seconds", type=float, default=None,
                        help="stop after N seconds (default: run_timeout_seconds in config)")
    parser.add_argument("--heartbeat-interval", type=float, default=None,
                        help="heartbeat interval seconds (default: 1.0; runtime passes it)")
    parser.add_argument("--stop-request-file", default=None,
                        help="opt-in runtime stop-request file (bt_api_runtime passes it)")
    args = parser.parse_args(argv)

    try:
        config, config_path = load_config(args.config, RUN_DIR, "config.yaml")
        if not isinstance(config, Mapping):
            raise ValueError("invalid configuration root")
        symbols = validate_live_config(config)
    except Exception:
        print("Configuration invalid or unavailable")
        return EXIT_BLOCKED
    # D67-01: this entry enables SDK write admission, so a missing or unusable
    # calendars.root refuses the live start before credentials, the Store or the
    # Broker.  --dry-run only reports the configuration problem.
    try:
        calendar = check_direct_calendar(
            config, config_file=config_path, ctp_routes=(ROUTE,), configured_routes={ROUTE}
        )
    except CalendarGateRefusal as exc:
        if args.dry_run:
            print(f"Calendar: {exc.code} ({exc.reason}); dry-run only reports")
        else:
            report("BLOCKED", error_code=exc.code, detail=f"Calendar: {exc.reason}")
        return EXIT_BLOCKED
    if calendar.code is not None and not args.dry_run:
        report("BLOCKED", error_code=calendar.code, detail=f"Calendar: {calendar.reason}")
        return EXIT_BLOCKED
    # D67-11: the Feed calendar scope is explicit configuration, never inferred
    # from a symbol. A missing declaration is reported by --dry-run and refuses
    # the live start; a malformed or conflicting one is refused in both modes.
    try:
        feed_calendar = check_direct_feed_scope(config, symbols=symbols, route=ROUTE)
    except CalendarFeedScopeRefusal as exc:
        if args.dry_run:
            print(f"Calendar feed scope: {exc.code} ({exc.reason}); "
                  "dry-run reports an invalid configuration")
        else:
            report("BLOCKED", error_code=exc.code,
                   detail=f"Calendar feed scope: {exc.reason}")
        return EXIT_BLOCKED
    if feed_calendar.code is not None and not args.dry_run:
        report("BLOCKED", error_code=feed_calendar.code,
               detail=f"Calendar feed scope: {feed_calendar.reason}")
        return EXIT_BLOCKED
    if args.dry_run:
        print("Dry run OK")
        print(f"Strategy: {STRATEGY.__name__}; symbols: {', '.join(symbols)}")
        for symbol in symbols:
            print(f"Feed {symbol}: {describe_feed(config, symbol)}")
        settings = logging_settings(config)
        target = "configured file" if settings["file"] else "stderr"
        print(f"Logging: bt_api_ctp={settings['level']} other={settings['other_level']} to={target}")
        print("State directory: configured locally")
        if calendar.kind == "directory":
            print("Calendar: external directory configured; local status only")
        elif calendar.kind == "package_seed":
            print("Calendar: in-package seed is installed by the Store at live start "
                  "(SYNTHETIC_MOCK, not exchange truth)")
        else:
            print(f"Calendar: {calendar.code}; live start will be refused "
                  "(dry-run only reports)")
        if feed_calendar.code is not None:
            print(f"Calendar feed scope: {feed_calendar.code}; live start will be refused "
                  "(dry-run only reports)")
        else:
            for symbol in symbols:
                scope = feed_calendar.scopes.get(symbol)
                if scope is None:
                    continue
                print("Calendar feed scope {}: {}/{}/{}/{}/{}".format(
                    symbol, scope["calendar_route"], scope["calendar_venue"],
                    scope["calendar_kind"], scope["calendar_product"],
                    scope["calendar_contract"]))
        return EXIT_PASS

    print(f"Logging: {configure_run_logging(config)}", flush=True)
    try:
        credentials = load_credentials(args.env_file)
    except (LookupError, OSError) as exc:
        report("BLOCKED", error_code="credentials_unavailable", detail=str(exc))
        return EXIT_BLOCKED

    from backtrader.brokers._btapi_direct_mode import DirectModeError, DirectStartStopped

    store = create_store(config, credentials, config_path)
    credentials.clear()
    broker = create_broker(store, config, args.first_init)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    feeds = add_feeds(cerebro, store, config, feed_calendar.scopes)
    for symbol in symbols:
        print(f"Feed {symbol}: {describe_feed(config, symbol)}", flush=True)
    cerebro.addstrategy(STRATEGY, **dict(config.get("strategy_params") or {}))
    log_dir = attach_trade_logger(cerebro, config, config_path)
    seconds = args.run_seconds
    if seconds is None:
        seconds = float(config.get("run_timeout_seconds", 0.0))
    print(f"Running {TITLE}: symbols={', '.join(symbols)} logs={log_dir} timeout={seconds:.0f}s",
          flush=True)
    status = "PASS"
    stop_request_file = args.stop_request_file
    if stop_request_file is not None:
        # Opt-in stop-file channel: the request is bound to this exact
        # strategy UUID and the run id supplied by bt_api_runtime.
        if args.run_id is None:
            report("BLOCKED", error_code="stop_request_requires_run_id")
            return EXIT_BLOCKED
        try:
            stop_request_strategy_uuid = load_identity(RUN_DIR).strategy_uuid
        except Exception:
            report("BLOCKED", error_code="stop_request_identity_unavailable")
            return EXIT_BLOCKED
    else:
        stop_request_strategy_uuid = None
    termination = stop_on_terminate(
        cerebro,
        stop_request_file=stop_request_file,
        stop_request_strategy_uuid=stop_request_strategy_uuid,
        stop_request_run_id=args.run_id,
    )
    contract = RunStatusWriter(
        RUN_DIR,
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
    cerebro.addanalyzer(RunProgress, contract=contract)
    failure = None
    try:
        run_with_timeout(cerebro, seconds, termination)
    except DirectStartStopped as exc:
        # A latched stop request aborted the start: the Broker's own summary
        # proves a write-free NOT_STARTED (exit 0) or reports UNKNOWN (exit 1).
        failure, status = exc, "NOT_STARTED"
        report(status, error_code=exc.code, detail=exc.detail)
    except (DirectModeError, LiveStateError) as exc:
        failure, status = exc, "BLOCKED"
        report(status, error_code=exc.code, detail=exc.detail)
    except KeyboardInterrupt as exc:
        # SIGINT keeps propagating; the summary still records the crash.
        failure, status = exc, "CRASHED"
        raise
    except Exception as exc:
        failure, status = exc, "CRASHED"
        report(status, error_type=type(exc).__name__)
    finally:
        conclusion = contract.finish(
            broker_summary=broker.get_shutdown_summary(), exception=failure
        )
        report(
            "SUMMARY" if status == "PASS" else status,
            outcome=conclusion.outcome,
            exit_code=conclusion.exit_code,
            reconcile=broker.get_direct_reconcile_report(),
            writes_blocked=broker.direct_writes_blocked() if broker._direct_active() else None,
            shutdown=getattr(broker, "_shutdown_summary", None),
            stop_signal=termination.received,
            refresh_counts=broker.get_direct_refresh_counts(),
            cash=broker.getcash(),
            value=broker.getvalue(),
        )
    return conclusion.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
