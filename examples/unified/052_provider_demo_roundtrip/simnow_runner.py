"""SimNow route adapter for the iteration-52 provider demo.

The example consumes only the SDK's provider-neutral configuration and
managed-runtime facades.  CTP configuration parsing, endpoint selection,
credential handling, native records and execution admission stay in the SDK.
An external host must inject the exact ready runtime binding; this module never
constructs a client or turns configuration/readiness into write authority.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

import paper_common
import simnow_paper

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SIMNOW_ROUTE = "CTP___FUTURE"


class _ManagedSessionAbort(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_code(exc: BaseException, fallback: str) -> str:
    value = getattr(exc, "code", None)
    if (
        type(value) is str
        and value.isascii()
        and value
        and all(char.isalnum() or char == "_" for char in value)
        and len(value) <= 96
    ):
        return value
    return fallback


def _close_unclaimed_composition_once(composition: Any) -> tuple[bool, str | None]:
    """Close only an exact SDK composition whose live owner check succeeds.

    Call this only when ManagedRuntimeCerebroSession construction failed before
    assigning a session. The session constructor only validates and stores the
    composition; it does not claim or close it on a failed construction.
    """

    try:
        from bt_api_py.managed_runtime_composition import ManagedRuntimeComposition
    except Exception:
        return False, "MANAGED_RUNTIME_SDK_UNAVAILABLE"
    if type(composition) is not ManagedRuntimeComposition:
        return False, "MANAGED_RUNTIME_COMPOSITION_INVALID"
    try:
        assert_owner_thread = composition.assert_owner_thread
        close = composition.close
    except Exception:
        return False, "MANAGED_RUNTIME_COMPOSITION_INVALID"
    from types import MethodType

    if (
        type(assert_owner_thread) is not MethodType
        or assert_owner_thread.__self__ is not composition
        or assert_owner_thread.__func__ is not ManagedRuntimeComposition.assert_owner_thread
        or type(close) is not MethodType
        or close.__self__ is not composition
        or close.__func__ is not ManagedRuntimeComposition.close
    ):
        return False, "MANAGED_RUNTIME_COMPOSITION_INVALID"
    try:
        assert_owner_thread()
    except Exception as exc:
        return False, _safe_code(exc, "MANAGED_RUNTIME_OWNER_THREAD_UNVERIFIED")
    try:
        close()
    except Exception as exc:
        return False, _safe_code(exc, "MANAGED_RUNTIME_CLOSE_FAILED")
    return True, None


def _emit(payload: dict[str, Any]) -> int:
    evidence = paper_common.write_evidence(payload)
    payload["evidence_path"] = str(evidence.relative_to(REPO_ROOT))
    print(json.dumps(paper_common.summarize(payload), sort_keys=True))
    return {
        "PASS": 0,
        "COMPLETED": 0,
        "FAILED": 1,
        "BLOCKED": 2,
        "UNKNOWN": 3,
    }.get(str(payload.get("status")), 2)


def _base_payload(tier_evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason": "SIMNOW_RUNTIME_UNAVAILABLE",
        "entry_tier": tier_evidence,
        "venue": "SIMNOW",
    }


def _public_configuration(configuration: Any) -> dict[str, Any]:
    builder = getattr(configuration, "to_public_dict", None)
    if not callable(builder):
        raise simnow_paper.SimNowPaperError("PROVIDER_CONFIGURATION_RESULT_INVALID")
    result = builder()
    if type(result) is not dict:
        raise simnow_paper.SimNowPaperError("PROVIDER_CONFIGURATION_RESULT_INVALID")
    return result


def _load_configuration(args: Any, params: dict[str, Any]) -> Any:
    """Pass paths to the SDK; never open the private files in Backtrader."""

    configured_names = params.get("credential_env_names", {})
    if not isinstance(configured_names, dict):
        configured_names = {}
    return simnow_paper.load_configuration(
        exchange_name=SIMNOW_ROUTE,
        config_path=Path(args.private_config),
        credential_env_file=Path(args.env_file),
        credential_values={},
        credential_names=configured_names,
    )


def _run_readonly_preflight(
    *,
    configuration: Any,
    public_configuration: dict[str, Any],
    runtime_binding: object,
    tier_evidence: dict[str, Any],
) -> int:
    composition = None
    runtime_session = None
    payload = _base_payload(tier_evidence)
    payload["provider_configuration"] = public_configuration
    try:
        composition = simnow_paper.compose_runtime(
            configuration,
            runtime_binding=runtime_binding,
            access_mode="read_only",
        )
        from backtrader.service.managed_runtime_host import ManagedRuntimeCerebroSession

        runtime_session = ManagedRuntimeCerebroSession(composition)
        runtime_session.assert_owner_thread()
        payload.update(
            {
                "status": "COMPLETED",
                "reason": "readonly_preflight_complete",
                "readiness": simnow_paper.collect_readonly_preflight(
                    composition.api,
                    configuration,
                ),
            }
        )
    except simnow_paper.SimNowPaperError as exc:
        payload.update({"status": "BLOCKED", "reason": exc.code})
    except Exception as exc:  # noqa: BLE001 - report a finite error only
        payload.update(
            {
                "status": "BLOCKED",
                "reason": _safe_code(exc, "SIMNOW_PREFLIGHT_FAILED"),
            }
        )
    finally:
        if composition is None:
            payload["route_close_confirmed"] = None
            payload["cleanup_status"] = "NOT_CREATED"
            payload["cleanup_reason"] = "MANAGED_RUNTIME_COMPOSITION_NOT_CREATED"
        elif runtime_session is None:
            route_closed, cleanup_reason = _close_unclaimed_composition_once(composition)
            payload["route_close_confirmed"] = route_closed
            payload["cleanup_status"] = "CLOSED" if route_closed else "UNKNOWN"
            payload["cleanup_reason"] = cleanup_reason
            if not route_closed:
                payload["status"] = "UNKNOWN"
                payload.setdefault("reason", "MANAGED_RUNTIME_CLEANUP_UNCERTAIN")
        else:
            try:
                close_report = runtime_session.close()
                route_closed = close_report.composition_close_confirmed is True
                payload["route_close_confirmed"] = route_closed
                payload["cleanup_status"] = "CLOSED" if route_closed else "UNKNOWN"
                payload["cleanup_reason"] = (
                    None if route_closed else "MANAGED_RUNTIME_CLOSE_UNCERTAIN"
                )
                if not route_closed:
                    payload["status"] = "UNKNOWN"
                    payload.setdefault("reason", "MANAGED_RUNTIME_CLOSE_UNCERTAIN")
            except Exception as exc:  # noqa: BLE001 - one-shot close, no retry
                payload["status"] = "UNKNOWN"
                payload["cleanup_status"] = "UNKNOWN"
                payload["cleanup_reason"] = _safe_code(
                    exc, "MANAGED_RUNTIME_CLOSE_FAILED"
                )
                payload["route_close_confirmed"] = False
                payload.setdefault("reason", "MANAGED_RUNTIME_CLOSE_UNCERTAIN")
    return _emit(payload)


def _bounded_strategy_facts(strategy: Any) -> dict[str, Any]:
    facts = getattr(strategy, "session_facts", None)
    if not callable(facts):
        return {}
    try:
        raw = facts()
    except Exception:
        return {"available": False}
    if not isinstance(raw, dict):
        return {"available": False}
    result: dict[str, Any] = {
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


def _safe_shutdown_facts(broker: Any, store: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
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


def _run_managed_bt_session(
    *,
    composition: Any,
    configuration: Any,
    public_configuration: dict[str, Any],
    params: dict[str, Any],
    args: Any,
    plan: Any,
    operator_grant: Any,
    execution_authorization: object,
    tier_evidence: dict[str, Any],
) -> int:
    """Run the shared BT strategy over the provider-neutral managed facade."""

    payload = _base_payload(tier_evidence)
    payload["provider_configuration"] = public_configuration
    payload["strategy_started"] = False
    report: dict[str, Any] = {}
    store = broker = cerebro = None
    timer = None
    route_closed = False
    runtime_session = None
    session_run_attempted = False
    try:
        from backtrader.service.managed_runtime_host import ManagedRuntimeCerebroSession

        runtime_session = ManagedRuntimeCerebroSession(composition)
        runtime_session.assert_owner_thread()
        readiness = simnow_paper.collect_readonly_preflight(
            composition.api,
            configuration,
        )
        payload["readiness"] = readiness
        if readiness.get("flat_and_instrument_ready") is not True:
            raise _ManagedSessionAbort(
                "SIMNOW_READINESS_NOT_FLAT_OR_INSTRUMENT_UNVERIFIED"
            )

        instrument = configuration.instrument
        route = configuration.exchange_name
        if (
            type(instrument.native_symbol) is not str
            or not instrument.native_symbol
            or route != SIMNOW_ROUTE
            or instrument.environment != configuration.environment
        ):
            raise _ManagedSessionAbort("PROVIDER_CONFIGURATION_RESULT_INVALID")

        import backtrader as bt
        from backtrader.dataseries import TimeFrame
        from backtrader.stores.btapistore import BtApiStore
        from provider_demo_roundtrip_strategy import ProviderDemoRoundTripStrategy

        symbol = instrument.native_symbol
        store = BtApiStore(
            api=composition.api,
            execution_authorization=execution_authorization,
            config={
                "symbol_routes": {symbol: route},
                "required_environments": {route: configuration.environment},
                "supports_dual_side": True,
                "position_mode": "dual_side",
            },
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
            raise _ManagedSessionAbort("SESSION_TIMEOUT_INVALID")
        timer = threading.Timer(float(timeout), cerebro.runstop)
        timer.daemon = True
        timer.start()
        payload["strategy_started"] = True
        try:
            session_run_attempted = True
            run_result = runtime_session.run(cerebro, runonce=False)
        finally:
            timer.cancel()
            timer = None
        strategy = run_result[0] if isinstance(run_result, (list, tuple)) and run_result else None
        strategy_facts = _bounded_strategy_facts(strategy)
        shutdown_facts = _safe_shutdown_facts(broker, store)
        report = {
            "strategy": strategy_facts,
            "shutdown": shutdown_facts,
        }
        payload["report"] = report
        phase = strategy_facts.get("phase")
        shutdown_pass = (
            shutdown_facts.get("broker_status") == "PASS"
            and shutdown_facts.get("broker_remote_flat_proven") is True
            and shutdown_facts.get("store_shutdown_state") == "PASS"
            and shutdown_facts.get("store_close_thread_alive") is False
        )
        if phase in {"canceled", "closed_verified"} and shutdown_pass:
            payload.update({"status": "PASS", "reason": "round_trip_" + phase})
        elif shutdown_facts.get("broker_status") == "FAIL":
            payload.update({"status": "UNKNOWN", "reason": "broker_shutdown_unproven"})
        elif phase in {"waiting", "submitted", "resting", "partially_filled", "filled", "awaiting_close", "flattening"}:
            payload.update({"status": "UNKNOWN", "reason": "round_trip_incomplete"})
        else:
            payload.update({"status": "BLOCKED", "reason": "round_trip_not_verified"})
    except _ManagedSessionAbort as exc:
        payload.update({"status": "BLOCKED", "reason": exc.code})
    except Exception as exc:  # noqa: BLE001 - no native/provider text in evidence
        payload.update(
            {
                "status": "BLOCKED",
                "reason": _safe_code(exc, "MANAGED_BACKTRADER_SESSION_FAILED"),
            }
        )
        if broker is not None and store is not None:
            payload["report"] = {"shutdown": _safe_shutdown_facts(broker, store)}
    finally:
        if timer is not None:
            timer.cancel()
        if runtime_session is None:
            route_closed, cleanup_reason = _close_unclaimed_composition_once(composition)
            payload["route_close_confirmed"] = route_closed
            payload["cleanup_status"] = "CLOSED" if route_closed else "UNKNOWN"
            payload["cleanup_reason"] = cleanup_reason
            if not route_closed:
                payload["status"] = "UNKNOWN"
                payload.setdefault("reason", "MANAGED_RUNTIME_CLEANUP_UNCERTAIN")
        elif session_run_attempted:
            # run() owns the one close attempt. Inspect only; never close twice.
            try:
                cleanup_report = runtime_session.cleanup_report
                route_closed = cleanup_report.composition_close_confirmed is True
                payload["route_close_confirmed"] = route_closed
                payload["cleanup_status"] = "CLOSED" if route_closed else "UNKNOWN"
                payload["cleanup_reason"] = (
                    None if route_closed else "MANAGED_RUNTIME_CLEANUP_UNCERTAIN"
                )
            except Exception:
                route_closed = False
                payload["route_close_confirmed"] = False
                payload["cleanup_status"] = "UNKNOWN"
                payload["cleanup_reason"] = "MANAGED_RUNTIME_CLEANUP_REPORT_UNAVAILABLE"
            if not route_closed:
                payload["status"] = "UNKNOWN"
                payload.setdefault("reason", "MANAGED_RUNTIME_CLEANUP_UNCERTAIN")
        else:
            # Setup/readiness failed before run() took lifecycle ownership.
            try:
                close_report = runtime_session.close()
                route_closed = close_report.composition_close_confirmed is True
                cleanup_reason = (
                    None if route_closed else "MANAGED_RUNTIME_CLOSE_UNCERTAIN"
                )
            except Exception as exc:  # noqa: BLE001 - one-shot close, no retry
                route_closed = False
                cleanup_reason = _safe_code(exc, "MANAGED_RUNTIME_CLOSE_FAILED")
            payload["route_close_confirmed"] = route_closed
            payload["cleanup_status"] = "CLOSED" if route_closed else "UNKNOWN"
            payload["cleanup_reason"] = cleanup_reason
            if not route_closed:
                payload["status"] = "UNKNOWN"
                payload.setdefault("reason", "MANAGED_RUNTIME_CLOSE_UNCERTAIN")
    return _emit(payload)


def run_simnow(
    plan: Any,
    params: dict[str, Any],
    args: Any,
    tier_evidence: dict[str, Any],
    *,
    runtime_binding: object | None = None,
    authorization_source: object | None = None,
    operator_grant: object | None = None,
    execution_authorization: object | None = None,
) -> int:
    """Run a read-only preflight or compose an explicitly authorized route.

    Runtime and write-capability parameters are supplied only by a trusted
    host.  This CLI has no implicit host resolver, credential accessor or
    operator-grant issuer.  A managed runtime can be composed after all exact
    inputs are present. Provider market-clock and execution capabilities can
    independently remain unavailable after composition.
    """

    payload = _base_payload(tier_evidence)
    if sys.version_info[:2] != (3, 11):
        payload.update(
            {
                "reason": "LIVE_TIER_REQUIRES_PYTHON_3_11",
                "current_python": "{}.{}".format(*sys.version_info[:2]),
            }
        )
        return _emit(payload)
    if getattr(args, "order_journal", None):
        payload["reason"] = "ORDER_JOURNAL_UNSUPPORTED_FOR_SIMNOW"
        return _emit(payload)
    if runtime_binding is None:
        payload["reason"] = "MANAGED_RUNTIME_BINDING_UNAVAILABLE"
        return _emit(payload)

    if not bool(getattr(args, "preflight_only", False)):
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
        configuration = _load_configuration(args, params)
        public_configuration = _public_configuration(configuration)
    except simnow_paper.SimNowPaperError as exc:
        payload["reason"] = exc.code
        return _emit(payload)
    except Exception as exc:  # noqa: BLE001 - no provider/file values in output
        payload["reason"] = _safe_code(exc, "PROVIDER_CONFIGURATION_UNAVAILABLE")
        return _emit(payload)

    if getattr(args, "preflight_only", False):
        return _run_readonly_preflight(
            configuration=configuration,
            public_configuration=public_configuration,
            runtime_binding=runtime_binding,
            tier_evidence=tier_evidence,
        )

    try:
        from bt_api_py.facade_protocol import OperatorWriteGrant

        if type(operator_grant) is not OperatorWriteGrant:
            payload["reason"] = "OPERATOR_WRITE_GRANT_INVALID"
            payload["provider_configuration"] = public_configuration
            return _emit(payload)
        composition = simnow_paper.compose_runtime(
            configuration,
            runtime_binding=runtime_binding,
            access_mode="managed_execution",
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
    except simnow_paper.SimNowPaperError as exc:
        payload["reason"] = exc.code
        payload["provider_configuration"] = public_configuration
        return _emit(payload)
    except Exception as exc:  # noqa: BLE001 - no provider details in output
        payload["reason"] = _safe_code(exc, "MANAGED_RUNTIME_COMPOSITION_UNAVAILABLE")
        payload["provider_configuration"] = public_configuration
        return _emit(payload)

    return _run_managed_bt_session(
        composition=composition,
        configuration=configuration,
        public_configuration=public_configuration,
        params=params,
        args=args,
        plan=plan,
        operator_grant=operator_grant,
        execution_authorization=execution_authorization,
        tier_evidence=tier_evidence,
    )


__all__ = ["run_simnow"]
