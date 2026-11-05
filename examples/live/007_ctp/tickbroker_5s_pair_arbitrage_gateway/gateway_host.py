#!/usr/bin/env python
"""Gateway process of the tickbroker_5s_pair_arbitrage (Gateway) example (iteration 62, step 62.08).

It serves the SDK Gateway CTP MarketHub (``bt_api_py.ctp_gateway_composition``)
for the SimNow profile ``gateway.ctp_profile`` of ``config.yaml`` on loopback
CURVE ZMQ with keys generated for this run. ``run.py`` starts it as a child
process (``serve_market_hub``) and receives the client connection through a
pipe; the keys never touch argv, files or logs.

Stand-alone use:

* ``--dry-run``: build the Gateway profile offline (no credentials, no network);
* ``--check-seconds N``: serve the hub and subscribe every configured symbol
  with an in-process CURVE client, then print tick counts (Gateway check only);
* ``--managed-boot-check``: boot the managed CTP execution runtime under SDK
  write admission (login, settlement readback, arm) and close it again; it
  places no order (the managed order path itself is unavailable, README).

Credentials are read only by this process, from ``SIMNOW_USER_ID`` /
``SIMNOW_PASSWORD`` (or the lower-case names) in the environment or in
``--env-file``; they are handed to the SDK provider through this process's own
environment (``CTP_USER_ID`` / ``CTP_PASSWORD`` / ``CTP_BROKER_ID``), never
printed, and removed again before exit.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import yaml

RUN_DIR = Path(__file__).resolve().parent
EXIT_PASS = 0
EXIT_BLOCKED = 2
EXIT_CLEANUP_UNCERTAIN = 3
TITLE = "tickbroker_5s_pair_arbitrage (Gateway)"
ROUTE = "CTP___FUTURE"
_CTP_ENV_NAMES = ("CTP_USER_ID", "CTP_PASSWORD", "CTP_BROKER_ID")


def load_config(config_arg):
    path = Path(config_arg or "config.yaml")
    if not path.is_absolute():
        path = (RUN_DIR / path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}, path


def report(status, **fields):
    record = {"status": status, **fields}
    print(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def gateway_settings(config):
    """Validated ``(instruments, ctp_profile, check_seconds)`` of the config."""
    symbols = list(config.get("symbols") or [])
    contracts = dict(config.get("contracts") or {})
    if not symbols or any(not dict(contracts.get(s) or {}).get("exchange") for s in symbols):
        raise ValueError("config requires symbols with a contracts.<symbol>.exchange")
    gateway = config.get("gateway")
    if not isinstance(gateway, dict) or not gateway.get("ctp_profile"):
        raise ValueError("config requires gateway.ctp_profile")
    seconds = float(gateway.get("market_check_seconds", 60))
    if not 0 < seconds <= 3600:
        raise ValueError("gateway.market_check_seconds must be in (0, 3600]")
    instruments = [(symbol, str(contracts[symbol]["exchange"])) for symbol in symbols]
    return instruments, str(gateway["ctp_profile"]), seconds


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


def _install_market_credentials(config, env_file):
    credentials = load_credentials(env_file)
    os.environ["CTP_USER_ID"] = credentials["user_id"]
    os.environ["CTP_PASSWORD"] = credentials["password"]
    os.environ["CTP_BROKER_ID"] = str(dict(config.get("ctp") or {}).get("broker_id", "9999"))
    credentials.clear()


def _remove_market_credentials():
    for name in _CTP_ENV_NAMES:
        os.environ.pop(name, None)


def build_market_hub(config, registry_directory):
    """SDK composition of the MarketHub profile and its client connection."""
    from bt_api_py.ctp_gateway_composition import build_ctp_gateway_market_host

    instruments, ctp_profile, _seconds = gateway_settings(config)
    return build_ctp_gateway_market_host(
        ctp_profile=ctp_profile,
        instruments=instruments,
        registry_path=Path(registry_directory) / "gateway-market-registry.sqlite3",
    )


def serve_market_hub(pipe, config_path, env_file):
    """Child-process entry for ``run.py``: serve until told to stop."""
    from bt_api_py.gateway_operator_application import (
        GatewayOperatorApplication,
        GatewayOperatorApplicationError,
    )

    config, _path = load_config(config_path)
    try:
        _install_market_credentials(config, env_file)
    except (LookupError, OSError):
        pipe.send(("error", "credentials_unavailable"))
        return
    application = None
    try:
        with tempfile.TemporaryDirectory(prefix="bt-007-gateway-") as directory:
            profile, connection = build_market_hub(config, directory)
            application = GatewayOperatorApplication(profile)
            try:
                application.start(timeout_seconds=30.0)
            except GatewayOperatorApplicationError as exc:
                pipe.send(("error", exc.code))
                return
            pipe.send(("ready", connection))
            while True:
                if pipe.poll(0.5):
                    try:
                        message = pipe.recv()
                    except EOFError:
                        break
                    if message == "stop":
                        break
            try:
                closed = application.close(timeout_seconds=30.0)
                state = closed.get("state")
            except GatewayOperatorApplicationError as exc:
                state = exc.code
            try:
                pipe.send(("closed", state))
            except (BrokenPipeError, OSError):
                pass
            if state not in {"closed", "stopped"}:
                os._exit(EXIT_CLEANUP_UNCERTAIN)
    finally:
        _remove_market_credentials()


def market_check(config, seconds, env_file):
    """Serve the hub and count ticks per symbol with an in-process client."""
    from bt_api_py.ctp_gateway_composition import (
        create_gateway_market_runtime,
        gateway_market_check_client,
    )
    from bt_api_py.gateway_operator_application import (
        GatewayOperatorApplication,
        GatewayOperatorApplicationError,
    )

    instruments, ctp_profile, _seconds = gateway_settings(config)
    try:
        _install_market_credentials(config, env_file)
    except (LookupError, OSError) as exc:
        report("BLOCKED", error_code="credentials_unavailable", detail=str(exc))
        return EXIT_BLOCKED
    counts = {symbol: 0 for symbol, _venue in instruments}
    first, errors, clients = {}, {}, {}
    runtime = None
    status, code, closed = "PASS", EXIT_PASS, {"state": None}
    with tempfile.TemporaryDirectory(prefix="bt-007-gateway-") as directory:
        profile, connection = build_market_hub(config, directory)
        application = GatewayOperatorApplication(profile)
        try:
            application.start(timeout_seconds=30.0)
            runtime, _factory = create_gateway_market_runtime(connection)
            for symbol, venue in instruments:
                client = gateway_market_check_client(runtime, connection, symbol, venue)
                try:
                    client.start()
                except Exception as exc:  # finite SDK code only
                    errors[symbol] = getattr(exc, "code", type(exc).__name__)
                    continue
                clients[symbol] = client
            deadline = time.monotonic() + seconds
            while clients and time.monotonic() < deadline:
                for symbol, client in clients.items():
                    try:
                        event = client.poll(timeout_ms=20)
                    except Exception as exc:
                        errors.setdefault(symbol, getattr(exc, "code", type(exc).__name__))
                        continue
                    if event is not None:
                        counts[symbol] += 1
                        data = dict(event.payload.get("data") or {})
                        first.setdefault(symbol, {
                            "last_price": data.get("last_price"),
                            "provider_event_time_utc": data.get("provider_event_time_utc"),
                            "received_at_utc": data.get("received_at_utc"),
                            "freshness_status": data.get("freshness_status"),
                            "execution_eligible": data.get("execution_eligible"),
                        })
        except GatewayOperatorApplicationError as exc:
            status, code = "BLOCKED", EXIT_BLOCKED
            errors["gateway"] = exc.code
        finally:
            for client in clients.values():
                try:
                    client.close()
                except Exception as exc:
                    errors.setdefault("market_close", getattr(exc, "code", type(exc).__name__))
            if runtime is not None:
                try:
                    runtime.close()
                except Exception as exc:
                    errors.setdefault("runtime_close", getattr(exc, "code", type(exc).__name__))
            try:
                closed = application.close(timeout_seconds=30.0)
            except GatewayOperatorApplicationError as exc:
                closed = {"state": exc.code}
            _remove_market_credentials()
    if status == "PASS" and (errors or not all(counts.values())):
        status, code = "BLOCKED", EXIT_BLOCKED
    if closed.get("state") not in {"closed", "stopped"}:
        status, code = "CLEANUP_UNCERTAIN", EXIT_CLEANUP_UNCERTAIN
    report(status, gateway_profile=profile.profile_ref, ctp_profile=ctp_profile,
           channel="tick", seconds=seconds, ticks=counts, first_tick=first,
           errors=errors, gateway_state=closed.get("state"))
    if code == EXIT_CLEANUP_UNCERTAIN:
        os._exit(code)  # a non-daemon owner thread may still hold the MD client
    return code


def managed_boot_check(config, env_file):
    """Boot and close the managed CTP runtime under SDK write admission."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from bt_api_ctp.ctp_env_selector import official_simnow_fronts
    from bt_api_ctp.trading_session_schedule import create_ctp_trading_session_schedule
    from bt_api_py.ctp_execution_runtime import (
        DIRECT_MANAGED_OWNER_OPTIONS,
        CtpExecutionResourceProvider,
    )
    from bt_api_py.ctp_gateway_execution import (
        CtpGatewayExecutionSettings,
        build_ctp_gateway_execution,
    )
    from bt_api_py.write_admission import WriteAdmission

    instruments, ctp_profile, _seconds = gateway_settings(config)
    symbol, venue = instruments[0]
    session = create_ctp_trading_session_schedule().session_state(
        symbol, datetime.now(timezone.utc)
    )
    if session.trading_day is None:
        report("BLOCKED", error_code="trading_day_unknown", reason=session.reason)
        return EXIT_BLOCKED
    try:
        credentials = load_credentials(env_file)
    except (LookupError, OSError) as exc:
        report("BLOCKED", error_code="credentials_unavailable", detail=str(exc))
        return EXIT_BLOCKED
    td_front, md_front = official_simnow_fronts(ctp_profile)
    contract = dict(config["contracts"][symbol])
    execution = dict(dict(config.get("gateway") or {}).get("execution") or {})
    with tempfile.TemporaryDirectory(prefix="bt-007-managed-") as directory:
        settings = CtpGatewayExecutionSettings(
            symbol=symbol,
            exchange_id=venue,
            strategy_ref="strategy.bt-007-" + RUN_DIR.name,
            trading_day=session.trading_day.strftime("%Y%m%d"),
            store_directory=directory,
            td_front=td_front,
            md_front=md_front,
            broker_id=str(dict(config.get("ctp") or {}).get("broker_id", "9999")),
            user_id=credentials["user_id"],
            password=credentials["password"],
            price_tick=Decimal(str(contract.get("price_tick", 1))),
        )
        credentials.clear()
        admission = WriteAdmission({ROUTE: bool(execution.get("write_admission", False))})
        composition = build_ctp_gateway_execution(settings, write_admission=admission)
        provider = CtpExecutionResourceProvider(composition.config)
        resources = None
        status, code, phase = "PASS", EXIT_PASS, None
        try:
            resources = provider("execution", "bt-007-managed-owner",
                                 DIRECT_MANAGED_OWNER_OPTIONS, composition.service_scope)
        except Exception as exc:
            status, code = "BLOCKED", EXIT_BLOCKED
            resources = getattr(exc, "resources", None)
        runtime = provider.last_runtime
        if runtime is not None:
            phase = runtime.status.phase
            gate = runtime._trader.get_execution_gate_state() if runtime._trader else {}
        else:
            gate = {}
        error_code = runtime.status.code if runtime is not None else "RUNTIME_NOT_CREATED"
        try:
            if resources is not None:
                resources.close()
            composition.close()
        except Exception:
            status, code = "CLEANUP_UNCERTAIN", EXIT_CLEANUP_UNCERTAIN
        report(status, phase=phase, error_code=error_code if status != "PASS" else None,
               write_admission=admission.is_enabled(ROUTE),
               gate_armed=gate.get("armed"), sdk_write_admission=gate.get("sdk_write_admission"),
               trading_day=settings.trading_day, instrument=symbol)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"Gateway process for {TITLE}")
    parser.add_argument("--config", default="config.yaml", help="config path (relative to here)")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the Gateway profile offline (no credentials, no network)")
    parser.add_argument("--check-seconds", type=float, default=None,
                        help="serve the MarketHub and count ticks for N seconds")
    parser.add_argument("--managed-boot-check", action="store_true",
                        help="boot and close the managed CTP runtime under SDK write admission")
    parser.add_argument("--env-file", default=None, help="env file with SimNow credentials")
    args = parser.parse_args(argv)

    config, config_path = load_config(args.config)
    instruments, ctp_profile, seconds = gateway_settings(config)
    if args.dry_run:
        with tempfile.TemporaryDirectory(prefix="bt-007-gateway-") as directory:
            profile, connection = build_market_hub(config, directory)
        print(f"Dry run OK for {config_path}")
        print(f"Gateway profile: {profile.profile_ref} (role {profile.role})")
        print(f"CTP SimNow profile: {ctp_profile}; source: {connection.source_ref}")
        print(f"Market keys (channel tick, environment demo): "
              f"{', '.join(symbol for symbol, _venue in instruments)}")
        return EXIT_PASS
    if args.managed_boot_check:
        return managed_boot_check(config, args.env_file)
    if args.check_seconds is not None:
        seconds = float(args.check_seconds)
    return market_check(config, seconds, args.env_file)


if __name__ == "__main__":
    raise SystemExit(main())
