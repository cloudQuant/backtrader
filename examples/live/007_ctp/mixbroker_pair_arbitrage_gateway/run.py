#!/usr/bin/env python
"""CTP SimNow live runner, Gateway mode: ``PairMixArbitrageStrategy`` (mixbroker_pair_arbitrage).

Gateway mode (iteration 62, step 62.08). ``run.py`` starts the Gateway process
of this folder (``gateway_host.serve_market_hub``, a spawned child) and then
runs Cerebro:

* market data: the SDK Gateway CTP MarketHub; ``BtApiStore(...,
  market_runtime_factory=...)`` makes the SDK facade serve every tick
  subscription from the Gateway (no in-process CTP market session);
* orders (``gateway.orders: direct``, the runnable default): the SDK direct
  write path with bt_api_py write admission, exactly as the ``_direct``
  sibling, with this folder as the strategy instance (``state/`` and
  ``logs/current_position.yaml``);
* ``gateway.orders: managed`` (orders through the Gateway managed execution
  runtime) is refused with ``managed_gateway_execution_unavailable`` before
  any credential or process is touched: its startup proof, OrderRef cutover
  authority and cancel recovery do not exist yet (README.md, "缺口").

Credentials come from ``SIMNOW_USER_ID`` / ``SIMNOW_PASSWORD`` (or the
lower-case names) in the environment or in ``--env-file``; this process uses
them for its direct trading session and the Gateway child reads them itself
for its market session. They are never printed. ``--dry-run`` validates the
configuration and builds the Gateway profile offline.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import multiprocessing
import os
import threading
from pathlib import Path

import backtrader as bt
from backtrader.live_trading import stop_on_terminate
import yaml

from pair_mix_arbitrage_strategy import PairMixArbitrageStrategy

RUN_DIR = Path(__file__).resolve().parent
ROUTE = "CTP___FUTURE"
EXIT_PASS = 0
EXIT_BLOCKED = 2
STRATEGY = PairMixArbitrageStrategy
TITLE = "mixbroker_pair_arbitrage (Gateway)"
ORDER_MODES = ("direct", "managed")
#: Missing pieces of the managed (Gateway execution runtime) order path.
MANAGED_ORDER_GAPS = (
    "bt_managed_startup_proof_unavailable",
    "ctp_order_ref_cutover_authority_unavailable",
    "ctp_managed_cancel_recovery_unavailable",
    "gateway_startup_recovery_authority_unavailable",
)


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
    validate_feed_settings("feed", dict(config.get("feed") or {}))
    for symbol in symbols:
        validate_feed_settings(f"contracts.{symbol}", feed_settings(config, symbol))
    if not isinstance(config.get("strategy_params") or {}, dict):
        raise ValueError("strategy_params must be a mapping")
    if not isinstance(config.get("broker") or {}, dict):
        raise ValueError("broker must be a mapping")
    gateway = config.get("gateway")
    if not isinstance(gateway, dict) or not gateway.get("ctp_profile"):
        raise ValueError("config requires gateway.ctp_profile")
    if str(gateway.get("orders", "direct")) not in ORDER_MODES:
        raise ValueError("gateway.orders must be direct or managed")
    if str(dict(config.get("ctp") or {}).get("instrument_environment", "demo")) != "demo":
        # The Gateway SimNow market keys use the SDK route label (I62-10).
        raise ValueError("Gateway mode needs ctp.instrument_environment: demo")
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


def start_gateway(config_path, env_file, timeout=90.0):
    """Spawn the Gateway process of this folder and return it with its connection."""
    from gateway_host import serve_market_hub

    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(
        target=serve_market_hub,
        args=(child, str(config_path), env_file),
        name="bt-007-ctp-gateway",
    )
    process.start()
    child.close()
    if not parent.poll(timeout):
        stop_gateway(process, parent)
        raise RuntimeError("gateway_start_timeout")
    kind, value = parent.recv()
    if kind != "ready":
        stop_gateway(process, parent)
        raise RuntimeError(str(value))
    return process, parent, value


def stop_gateway(process, pipe, timeout=40.0):
    state = None
    try:
        pipe.send("stop")
        if pipe.poll(timeout):
            _kind, state = pipe.recv()
    except (BrokenPipeError, EOFError, OSError):
        pass
    process.join(timeout)
    if process.is_alive():
        process.kill()
        process.join(5.0)
        state = state or "killed"
    return state


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


def create_store(config, credentials, market_runtime_factory):
    """Direct-write ``BtApiStore`` whose ticks come from the Gateway MarketHub."""
    configure_catalog_cache(config)
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
            "ctp_env_profile": str(dict(config["gateway"]).get("ctp_profile")),
            "private_topic_mode": str(ctp.get("private_topic_mode", "quick")),
        }
    }
    from bt_api_py.ctp_gateway_composition import ctp_gateway_instrument_key

    contracts = dict(config.get("contracts") or {})
    contract_metadata = {
        symbol: {
            "instrument_key": ctp_gateway_instrument_key(symbol, contracts[symbol]["exchange"]),
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
        market_runtime_factory=market_runtime_factory,
    )


def create_broker(store, config, first_init):
    """``BtApiBroker`` (direct path selected by the Store) bound to this directory."""
    settings = dict(config.get("broker") or {})
    settings.setdefault("position_mode", "net")
    broker = store.getbroker(strategy_dir=str(RUN_DIR), first_init=bool(first_init), **settings)
    for symbol, spec in dict(config.get("contracts") or {}).items():
        broker.setcommission(
            commission=0.0, margin=1.0, mult=float(spec.get("multiplier") or 1), name=symbol
        )
    return broker


def add_feeds(cerebro, store, config):
    for symbol in config["symbols"]:
        # The feed: section with this contract's overrides (D62-28, README).
        feed_config = feed_settings(config, symbol)
        timeframe = parse_timeframe(feed_config.pop("timeframe", "ticks"))
        compression = int(feed_config.pop("compression", 1))
        backfill_start = bool(feed_config.pop("backfill_start", False))
        data = store.getdata(
            dataname=symbol,
            timeframe=timeframe,
            compression=compression,
            backfill_start=backfill_start,
            **feed_config,
        )
        cerebro.adddata(data, name=symbol)


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
    parser.add_argument("--orders", choices=ORDER_MODES, default=None,
                        help="order path (default: gateway.orders in config)")
    parser.add_argument("--run-seconds", type=float, default=None,
                        help="stop after N seconds (default: run_timeout_seconds in config)")
    args = parser.parse_args(argv)

    config, config_path = load_config(args.config, RUN_DIR, "config.yaml")
    symbols = validate_live_config(config)
    orders = args.orders or str(config["gateway"].get("orders", "direct"))
    if args.dry_run:
        import tempfile

        from gateway_host import build_market_hub

        with tempfile.TemporaryDirectory(prefix="bt-007-gateway-") as directory:
            profile, connection = build_market_hub(config, directory)
        print(f"Dry run OK for {config_path}")
        print(f"Strategy: {STRATEGY.__name__}; symbols: {', '.join(symbols)}")
        for symbol in symbols:
            print(f"Feed {symbol}: {describe_feed(config, symbol)}")
        print(f"Market data: Gateway {profile.profile_ref} ({connection.source_ref})")
        if orders == "managed":
            print(f"Orders: managed -> unavailable ({', '.join(MANAGED_ORDER_GAPS)})")
        else:
            print(f"Orders: direct; state directory: {RUN_DIR / 'state'}")
        return EXIT_PASS

    if orders == "managed":
        # Fail closed before credentials or processes (README.md, "缺口").
        report("BLOCKED", error_code="managed_gateway_execution_unavailable",
               missing=list(MANAGED_ORDER_GAPS))
        return EXIT_BLOCKED

    try:
        credentials = load_credentials(args.env_file)
    except (LookupError, OSError) as exc:
        report("BLOCKED", error_code="credentials_unavailable", detail=str(exc))
        return EXIT_BLOCKED

    from bt_api_py.ctp_gateway_composition import create_gateway_market_runtime

    from backtrader.brokers._btapi_direct_mode import DirectModeError

    try:
        gateway, pipe, connection = start_gateway(config_path, args.env_file)
    except RuntimeError as exc:
        credentials.clear()
        report("BLOCKED", error_code="gateway_unavailable", detail=str(exc))
        return EXIT_BLOCKED
    market_runtime = broker = termination = None
    status, code = "PASS", EXIT_PASS
    try:
        market_runtime, factory = create_gateway_market_runtime(connection)
        store = create_store(config, credentials, factory)
        credentials.clear()
        broker = create_broker(store, config, args.first_init)
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.setbroker(broker)
        add_feeds(cerebro, store, config)
        for symbol in symbols:
            print(f"Feed {symbol}: {describe_feed(config, symbol)}", flush=True)
        cerebro.addstrategy(STRATEGY, **dict(config.get("strategy_params") or {}))
        log_dir = attach_trade_logger(cerebro, config, config_path)
        seconds = args.run_seconds
        if seconds is None:
            seconds = float(config.get("run_timeout_seconds", 0.0))
        print(f"Running {TITLE}: symbols={', '.join(symbols)} market=gateway orders=direct "
              f"logs={log_dir} timeout={seconds:.0f}s", flush=True)
        termination = stop_on_terminate(cerebro)
        try:
            run_with_timeout(cerebro, seconds, termination)
        except DirectModeError as exc:
            status, code = "BLOCKED", EXIT_BLOCKED
            report(status, error_code=exc.code, detail=exc.detail)
    finally:
        credentials.clear()
        if broker is not None:
            report(
                "SUMMARY" if status == "PASS" else status,
                reconcile=broker.get_direct_reconcile_report(),
                writes_blocked=broker.direct_writes_blocked() if broker._direct_active() else None,
                shutdown=getattr(broker, "_shutdown_summary", None),
                stop_signal=termination.received if termination is not None else None,
                refresh_counts=broker.get_direct_refresh_counts(),
                cash=broker.getcash(),
                value=broker.getvalue(),
            )
        if market_runtime is not None:
            try:
                market_runtime.close()
            except Exception as exc:
                report("WARNING", error_code="gateway_client_close_uncertain",
                       detail=type(exc).__name__)
        gateway_state = stop_gateway(gateway, pipe)
        report("GATEWAY", state=gateway_state)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
