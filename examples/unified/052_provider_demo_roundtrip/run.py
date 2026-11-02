"""Iteration 52 provider-neutral paper entry: one bounded Demo round trip.

``--dry`` validates the unified configuration without credentials, network or
provider imports. ``--live`` selects the configured channel. Read-only
preflight does not require the separate write gate; order entry still requires
``--allow-write`` and independently supplied SDK authorization.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

import paper_common

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
# ``--private-config`` default; only the SIMNOW live branch consumes it.
DEFAULT_PRIVATE_CONFIG = (
    HERE.parent / "013_3_sa_midfreq_simnow" / "runtime-ctp-private" / "config.yaml"
)
DEFAULT_SDK_SRC = Path(os.environ.get("BT_API_PY_SRC", "D:/bt_api_py"))
if str(HERE) not in sys.path:
    # simnow_paper / provider_demo_roundtrip_strategy are folder-local modules.
    sys.path.insert(0, str(HERE))


def _prepend_sources() -> None:
    for path in (REPO_ROOT, DEFAULT_SDK_SRC):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _load_yaml_text(path: Path) -> dict:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must contain a mapping")
    return raw


def _venue(params: dict) -> str:
    value = params.get("venue", "BINANCE")
    if type(value) is not str or not value or value != value.strip():
        raise RuntimeError("provider_route_invalid")
    return value.upper()


def _safe_code(exc: BaseException, fallback: str) -> str:
    value = getattr(exc, "code", None)
    if (
        type(value) is str
        and value.isascii()
        and value
        and len(value) <= 96
        and all(char.isalnum() or char == "_" for char in value)
    ):
        return value
    return fallback


def _public_configuration(configuration) -> dict:
    builder = getattr(configuration, "to_public_dict", None)
    if not callable(builder):
        raise RuntimeError("provider_configuration_result_invalid")
    result = builder()
    if type(result) is not dict:
        raise RuntimeError("provider_configuration_result_invalid")
    return result


def _parse_ledger_routes(value: object) -> tuple[str, ...]:
    if type(value) is not str or not value:
        raise RuntimeError("MULTI_ROUTE_READ_ROUTE_INVALID")
    parts = tuple(value.split(","))
    if (
        not parts
        or any(not item or item != item.strip() or item != item.upper() for item in parts)
        or len(set(parts)) != len(parts)
    ):
        raise RuntimeError("MULTI_ROUTE_READ_ROUTE_INVALID")
    return parts


def query_ledger_routes(
    *,
    routes: tuple[str, ...],
    read_facades: Mapping[str, object],
    query_requests: Mapping[str, object],
):
    """Return route-isolated SDK order-query outcomes for explicit host inputs.

    This helper creates no clients and does not close the caller-owned
    read-only facades. Each route must have its own typed request sequence.
    """
    from bt_api_py.multi_route_read import query_orders_sync

    return query_orders_sync(
        routes=routes,
        read_facades=read_facades,
        query_requests=query_requests,
    )


def _emit(payload: dict) -> int:
    evidence = paper_common.write_evidence(payload)
    payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
    print(json.dumps(paper_common.summarize(payload), sort_keys=True))
    return {"PASS": 0, "COMPLETED": 0, "FAILED": 1, "BLOCKED": 2, "UNKNOWN": 3}.get(
        str(payload.get("status")), 2
    )


def _bounded_strategy_facts(strategy) -> dict:
    facts = getattr(strategy, "session_facts", None)
    if not callable(facts):
        return {}
    try:
        raw = facts()
    except Exception:
        return {"available": False}
    if not isinstance(raw, dict):
        return {"available": False}
    result = {
        "available": True,
        "phase": raw.get("phase") if type(raw.get("phase")) is str else None,
        "cancel_requested": (
            raw.get("cancel_requested")
            if type(raw.get("cancel_requested")) is bool
            else None
        ),
    }
    for name in ("open_order", "close_order"):
        order = raw.get(name)
        status = order.get("status") if isinstance(order, dict) else None
        result[name + "_status"] = status if type(status) is str else None
    return result


def _bounded_shutdown_facts(broker, store) -> dict:
    result = {}
    try:
        state = broker.get_shutdown_state()
    except Exception:
        state = None
    if isinstance(state, dict):
        for key in ("status", "remote_flat_proven", "flat_proven"):
            value = state.get(key)
            if type(value) in (str, bool):
                result["broker_" + key] = value
    try:
        health = store.get_command_health()
    except Exception:
        health = None
    if isinstance(health, dict):
        for key in ("shutdown_state", "close_thread_alive", "restart_blocked_by_close"):
            value = health.get(key)
            if type(value) in (str, bool):
                result["store_" + key] = value
    return result


def _run_managed_provider_session(
    *,
    composition,
    configuration,
    public_configuration: dict,
    params: dict,
    args,
    venue: str,
    route: str,
    operator_grant,
    execution_authorization,
    tier_evidence: dict,
) -> int:
    payload = {
        "status": "BLOCKED",
        "reason": "MANAGED_BACKTRADER_SESSION_FAILED",
        "entry_tier": tier_evidence,
        "venue": venue,
        "provider_configuration": public_configuration,
        "strategy_started": False,
    }
    store = broker = timer = None
    runtime_session = None
    try:
        import simnow_paper

        from backtrader.service.managed_runtime_host import ManagedRuntimeCerebroSession

        runtime_session = ManagedRuntimeCerebroSession(composition)
        runtime_session.assert_owner_thread()

        readiness = simnow_paper.collect_readonly_preflight(composition.api, configuration)
        payload["readiness"] = readiness
        if readiness.get("flat_and_instrument_ready") is not True:
            raise RuntimeError("READINESS_NOT_FLAT_OR_INSTRUMENT_VERIFIED")

        from bt_api_py.facade_protocol import MarketInstrumentKey

        instrument = getattr(configuration, "instrument", None)
        if type(instrument) is not MarketInstrumentKey:
            raise RuntimeError("PROVIDER_CONFIGURATION_RESULT_INVALID")
        symbol = instrument.native_symbol
        if (
            type(symbol) is not str
            or not symbol
            or configuration.exchange_name != route
            or instrument.environment != configuration.environment
        ):
            raise RuntimeError("PROVIDER_CONFIGURATION_RESULT_INVALID")

        import backtrader as bt
        from backtrader.dataseries import TimeFrame
        from backtrader.stores.btapistore import BtApiStore
        from provider_demo_roundtrip_strategy import ProviderDemoRoundTripStrategy

        store_config = {
            "symbol_routes": {symbol: route},
            "required_environments": {route: configuration.environment},
            "position_mode": "dual_side",
            "supports_dual_side": True,
            "require_account_risk": True,
            "account_maximum_loss_bps": "50",
            "account_risk_max_age_seconds": "60",
        }
        if args.order_journal:
            store_config["order_journal"] = args.order_journal
        store = BtApiStore(
            api=composition.api,
            execution_authorization=execution_authorization,
            config=store_config,
            contract_metadata={symbol: {"instrument_key": instrument}},
        )
        broker = store.getbroker(
            position_mode="dual_side",
            position_sync_policy="startup",
            cancel_wait_remote=True,
            cancel_confirmation_timeout=5.0,
            shutdown_timeout=30.0,
            flatten_on_stop=True,
            approval_expires_at_utc=operator_grant.expires_at_utc,
            approval_max_order_count=operator_grant.max_order_count,
        )
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        cerebro.setbroker(broker)
        data = store.getdata(
            dataname=symbol,
            timeframe=TimeFrame.Ticks,
            orderbook_as_ticks=True,
            backfill_start=False,
            qcheck=0.05,
        )
        cerebro.adddata(data, name=symbol)
        cerebro.addstrategy(
            ProviderDemoRoundTripStrategy,
            **paper_common.strategy_params(params),
        )
        timeout = getattr(args, "session_seconds", 60.0)
        if (
            isinstance(timeout, bool)
            or type(timeout) not in (int, float)
            or not 1.0 <= float(timeout) <= 300.0
        ):
            raise RuntimeError("SESSION_TIMEOUT_INVALID")
        timer = threading.Timer(float(timeout), cerebro.runstop)
        timer.daemon = True
        timer.start()
        payload["strategy_started"] = True
        try:
            result = runtime_session.run(cerebro, runonce=False)
        finally:
            timer.cancel()
            timer = None
        strategy = result[0] if isinstance(result, (list, tuple)) and result else None
        strategy_facts = _bounded_strategy_facts(strategy)
        shutdown = _bounded_shutdown_facts(broker, store)
        payload["report"] = {
            "run_id": operator_grant.run_id,
            "strategy_facts": strategy_facts,
            "shutdown": shutdown,
        }
        phase = strategy_facts.get("phase")
        shutdown_pass = (
            shutdown.get("broker_status") == "PASS"
            and shutdown.get("broker_remote_flat_proven") is True
            and shutdown.get("store_shutdown_state") == "PASS"
            and shutdown.get("store_close_thread_alive") is False
        )
        if phase in {"canceled", "closed_verified"} and shutdown_pass:
            payload.update({"status": "PASS", "reason": "round_trip_" + phase})
        elif shutdown.get("broker_status") == "FAIL":
            payload.update({"status": "UNKNOWN", "reason": "broker_shutdown_unproven"})
        elif phase in {
            "waiting",
            "submitted",
            "resting",
            "partially_filled",
            "filled",
            "awaiting_close",
            "flattening",
        }:
            payload.update({"status": "UNKNOWN", "reason": "round_trip_incomplete"})
        else:
            payload.update({"status": "BLOCKED", "reason": "round_trip_not_verified"})
    except Exception as exc:  # noqa: BLE001 - report only finite codes
        payload.update({"status": "BLOCKED", "reason": _safe_code(exc, "MANAGED_BACKTRADER_SESSION_FAILED")})
        if broker is not None and store is not None:
            payload["report"] = {
                "run_id": operator_grant.run_id,
                "shutdown": _bounded_shutdown_facts(broker, store),
            }
    finally:
        if timer is not None:
            timer.cancel()
        try:
            if runtime_session is None:
                payload["status"] = "UNKNOWN"
                payload["reason"] = "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
                payload["route_close_confirmed"] = False
            else:
                close_report = runtime_session.close()
                payload["route_close_confirmed"] = (
                    close_report.composition_close_confirmed is True
                )
                if not payload["route_close_confirmed"]:
                    payload["status"] = "UNKNOWN"
                    payload["reason"] = "MANAGED_RUNTIME_CLOSE_UNCERTAIN"
        except Exception as exc:  # noqa: BLE001 - one-shot close, no retry
            payload["status"] = "UNKNOWN"
            payload["reason"] = _safe_code(exc, "MANAGED_RUNTIME_CLOSE_FAILED")
            payload["route_close_confirmed"] = False
        else:
            if "route_close_confirmed" not in payload:
                payload["route_close_confirmed"] = True
    return _emit(payload)


def _run_provider_neutral(
    params: dict,
    args,
    tier_evidence: dict,
    *,
    provider_selection,
    runtime_binding,
    authorization_source,
    operator_grant,
    execution_authorization,
    ledger_read_facades,
    ledger_query_requests,
    venue: str,
) -> int:
    payload = {
        "status": "BLOCKED",
        "reason": "PROVIDER_CONFIGURATION_UNAVAILABLE",
        "entry_tier": tier_evidence,
        "venue": venue,
    }
    preflight_only = bool(getattr(args, "preflight_only", False))
    if args.ledger_venues is not None:
        try:
            requested_routes = _parse_ledger_routes(args.ledger_venues)
            outcomes = query_ledger_routes(
                routes=requested_routes,
                read_facades=ledger_read_facades,
                query_requests=ledger_query_requests,
            )
        except Exception as exc:  # noqa: BLE001 - only finite route/error codes escape
            payload.update(
                {
                    "reason": _safe_code(exc, "MULTI_ROUTE_READ_UNAVAILABLE"),
                    "ledger_scope": "explicit_route_isolated_reads",
                    "ledger_reconciled": False,
                }
            )
            return _emit(payload)
        failed = any(not outcome.returned for outcome in outcomes)
        payload.update(
            {
                "status": "BLOCKED" if failed else "COMPLETED",
                "reason": (
                    "multi_route_order_query_failed"
                    if failed
                    else "multi_route_order_query_returned"
                ),
                "ledger_scope": "explicit_route_isolated_reads",
                "ledger_reconciled": False,
                "ledger_routes": list(requested_routes),
                "ledger_route_outcomes": [
                    {
                        "route": item.route,
                        "ordinal": item.ordinal,
                        "returned": item.returned,
                        "error_code": item.error_code,
                    }
                    for item in outcomes
                ],
            }
        )
        return _emit(payload)
    if ledger_read_facades is not None or ledger_query_requests is not None:
        payload["reason"] = "MULTI_ROUTE_READ_SELECTION_REQUIRED"
        return _emit(payload)

    import simnow_paper

    try:
        from bt_api_py.provider_configuration import (
            ProviderConfigurationSelection,
            load_provider_configuration,
        )

        if type(provider_selection) is not ProviderConfigurationSelection:
            payload["reason"] = "PROVIDER_CONFIGURATION_INPUT_UNAVAILABLE"
            return _emit(payload)
        route = provider_selection.exchange_name
        route_provider = route.split("___", 1)[0].upper()
        if venue not in {route.upper(), route_provider}:
            payload["reason"] = "PROVIDER_CONFIGURATION_ROUTE_MISMATCH"
            return _emit(payload)
        requested_symbol = params.get("symbol")
        instrument = provider_selection.instrument
        if requested_symbol is not None and requested_symbol not in {
            instrument.instrument_id,
            instrument.native_symbol,
        }:
            payload["reason"] = "PROVIDER_CONFIGURATION_INSTRUMENT_MISMATCH"
            return _emit(payload)
    except ImportError:
        payload["reason"] = "PROVIDER_CONFIGURATION_FACADE_UNAVAILABLE"
        return _emit(payload)
    if not preflight_only and runtime_binding is None:
        payload["reason"] = "MANAGED_RUNTIME_BINDING_UNAVAILABLE"
        return _emit(payload)
    if not preflight_only:
        if not bool(getattr(args, "allow_write", False)):
            payload["reason"] = "WRITE_NOT_AUTHORIZED"
            return _emit(payload)
        if operator_grant is None:
            payload["reason"] = "OPERATOR_WRITE_GRANT_UNAVAILABLE"
            return _emit(payload)
        if authorization_source is None:
            payload["reason"] = "SDK_AUTHORIZATION_SOURCE_UNAVAILABLE"
            return _emit(payload)
        if execution_authorization is None:
            payload["reason"] = "SDK_EXECUTION_AUTHORIZATION_UNAVAILABLE"
            return _emit(payload)

    try:
        from bt_api_py.facade_protocol import OperatorWriteGrant

        if not preflight_only and type(operator_grant) is not OperatorWriteGrant:
            payload["reason"] = "OPERATOR_WRITE_GRANT_INVALID"
            return _emit(payload)
        # The neutral DTO is only a route/profile selector. The selected SDK
        # provider must bind its opaque handle to a trusted profile registry.
        configuration = load_provider_configuration(
            route,
            config_path=Path(args.config),
            selection=provider_selection,
            credential_values={},
            credential_names={},
        )
        public_configuration = _public_configuration(configuration)
    except Exception as exc:  # noqa: BLE001 - no configuration values in output
        payload["reason"] = _safe_code(exc, "PROVIDER_CONFIGURATION_UNAVAILABLE")
        return _emit(payload)

    try:
        if preflight_only:
            from bt_api_py.managed_runtime_composition import compose_read_only_runtime

            composition = compose_read_only_runtime(configuration)
        else:
            composition = simnow_paper.compose_runtime(
                configuration,
                runtime_binding=runtime_binding,
                access_mode="managed_execution",
                authorization_source=authorization_source,
                operator_grant=operator_grant,
            )
    except Exception as exc:  # noqa: BLE001 - never surface provider details
        payload["reason"] = _safe_code(exc, "MANAGED_RUNTIME_COMPOSITION_UNAVAILABLE")
        payload["provider_configuration"] = public_configuration
        return _emit(payload)

    if preflight_only:
        readonly_session = None
        try:
            from backtrader.service.managed_runtime_host import ManagedRuntimeCerebroSession

            readonly_session = ManagedRuntimeCerebroSession(composition)
            readonly_session.assert_owner_thread()
            readiness = simnow_paper.collect_readonly_preflight(
                composition.api,
                configuration,
            )
            payload.update(
                {
                    "status": "COMPLETED",
                    "reason": "readonly_preflight_complete",
                    "provider_configuration": public_configuration,
                    "readiness": readiness,
                }
            )
        except Exception as exc:  # noqa: BLE001 - no provider details in output
            payload["reason"] = _safe_code(exc, "READONLY_PREFLIGHT_FAILED")
            payload["provider_configuration"] = public_configuration
        finally:
            if readonly_session is None:
                payload["status"] = "UNKNOWN"
                payload["reason"] = "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED"
                payload["route_close_confirmed"] = False
            else:
                try:
                    close_report = readonly_session.close()
                    payload["route_close_confirmed"] = (
                        close_report.composition_close_confirmed is True
                    )
                    if not payload["route_close_confirmed"]:
                        payload["status"] = "UNKNOWN"
                        payload["reason"] = "MANAGED_RUNTIME_CLOSE_UNCERTAIN"
                except Exception as exc:  # noqa: BLE001 - one-shot close
                    payload["status"] = "UNKNOWN"
                    payload["reason"] = _safe_code(exc, "MANAGED_RUNTIME_CLOSE_FAILED")
                    payload["route_close_confirmed"] = False
        return _emit(payload)

    return _run_managed_provider_session(
        composition=composition,
        configuration=configuration,
        public_configuration=public_configuration,
        params=params,
        args=args,
        venue=venue,
        route=route,
        operator_grant=operator_grant,
        execution_authorization=execution_authorization,
        tier_evidence=tier_evidence,
    )


def main(
    argv: list[str] | None = None,
    *,
    runtime_binding: object | None = None,
    authorization_source: object | None = None,
    operator_grant: object | None = None,
    execution_authorization: object | None = None,
    provider_selection: object | None = None,
    ledger_read_facades: Mapping[str, object] | None = None,
    ledger_query_requests: Mapping[str, object] | None = None,
) -> int:
    """Validate offline input or run one host-bound SDK route.

    This example does not issue provider selections, runtime bindings, grants,
    or execution authorization. A trusted host supplies those values for live
    composition; multi-route reads separately require exact read-only SDK
    facades and per-route typed requests. Missing capability never falls back
    to a direct client.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(HERE / "config.yaml"))
    parser.add_argument("--dry", action="store_true", help="offline validation only")
    parser.add_argument("--live", action="store_true", help="select the live channel")
    parser.add_argument("--allow-write", action="store_true", help="explicit write grant")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument(
        "--private-config",
        default=str(DEFAULT_PRIVATE_CONFIG),
        help="sealed CTP ctp: block used only by the SIMNOW live tier",
    )
    parser.add_argument(
        "--order-journal",
        default=None,
        help="reuse one existing account execution journal (required when the "
        "account is already bound to it)",
    )
    parser.add_argument(
        "--ledger-venues",
        default=None,
        help="explicit comma-separated SDK route keys for isolated order reads",
    )
    parser.add_argument("--preflight-only", action="store_true", help="account/readiness only; no order")
    parser.add_argument("--session-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)

    _prepend_sources()
    from entry_tier import decide, conflict, invalid

    config_path = Path(args.config)
    raw = _load_yaml_text(config_path)
    cli_tier = "dry" if args.dry else ("live" if args.live else None)
    decision = decide(raw, cli_tier)
    tier_evidence = decision.as_evidence()
    if invalid(decision) or conflict(decision):
        payload = {"status": "BLOCKED", "reason": "config_tier_invalid_or_conflict", "entry_tier": tier_evidence}
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    try:
        from bt_api_py.run_contracts import ValidatedRunConfigV2, parse_config
    except ImportError:
        payload = {
            "status": "BLOCKED",
            "reason": "RUN_CONFIG_CONTRACT_UNAVAILABLE",
            "entry_tier": tier_evidence,
        }
        paper_common.write_evidence(payload)
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    try:
        plan = parse_config(config_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - finite code only
        payload = {
            "status": "BLOCKED",
            "reason": "config_invalid:" + type(exc).__name__,
            "entry_tier": tier_evidence,
        }
        paper_common.write_evidence(payload)
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2
    if not isinstance(plan, ValidatedRunConfigV2):
        payload = {"status": "BLOCKED", "reason": "schema_v2_required", "entry_tier": tier_evidence}
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2

    params = plan.strategy_parameters_dict()
    if decision.effective_tier != "live":
        payload = {
            "status": "COMPLETED",
            "reason": "offline_validate_ok",
            "entry_tier": tier_evidence,
            "plan": {
                "mode": plan.mode.value,
                "environment": plan.environment.value,
                "capabilities": list(plan.requested_capabilities),
            },
        }
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 0

    venue = _venue(params)
    if venue == "SIMNOW":
        import simnow_runner

        return simnow_runner.run_simnow(
            plan,
            params,
            args,
            tier_evidence,
            provider_selection=provider_selection,
            runtime_binding=runtime_binding,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
            execution_authorization=execution_authorization,
        )

    try:
        return _run_provider_neutral(
            params,
            args,
            tier_evidence,
            provider_selection=provider_selection,
            runtime_binding=runtime_binding,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
            execution_authorization=execution_authorization,
            ledger_read_facades=ledger_read_facades,
            ledger_query_requests=ledger_query_requests,
            venue=venue,
        )
    except Exception as exc:  # noqa: BLE001 - safe bounded setup failure
        payload = {
            "status": "BLOCKED",
            "reason": _safe_code(exc, "PROVIDER_NEUTRAL_SETUP_FAILED"),
            "entry_tier": tier_evidence,
        }
        paper_common.write_evidence(payload)
        print(json.dumps(paper_common.summarize(payload), sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
