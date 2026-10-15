"""Runnable local example for configured ServiceExecutionSession composition.

The deployment in this file is intentionally synthetic and rejects every
provider write. It exists to make the configured client-to-Cerebro lifecycle
reproducible without credentials or an exchange adapter.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import socket
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import backtrader as bt
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution import ExecutionScope, SqliteExecutionStore
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import (
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.stores.btapistore import BtApiStore
from backtrader.stores.service_execution_session import run_configured_cerebro


_DOMAIN = "paper:backtrader-local-synthetic"
_SERVICE_ID = "local-synthetic-execution"
_SERVICE_PRINCIPAL = "local-synthetic-execution-principal"
_INSTANCE_ID = "local-synthetic-execution-owner"
_SERVICE_SCOPE_REF = "local-synthetic-service-v1"
_SERVER_SECURITY_REF = "local-synthetic-server-curve-v1"
_CLIENT_SECURITY_REF = "local-synthetic-client-curve-v1"
_TRANSPORT_REF = "local-synthetic-rpc-v1"
_ACCOUNT = "local-synthetic-account"
_STRATEGY = "local-synthetic-strategy"
_PRINCIPAL = "local-synthetic-strategy-principal"
_ORDER_SCOPE_REF = "local-synthetic-orders-v1"
_QUERY_SCOPE_REF = "local-synthetic-order-query-v1"
_TRADING_DAY = "20261015"
_MAX_MESSAGE_BYTES = 65_536
_ORDER_OPERATIONS = frozenset({"orders.submit", "orders.cancel"})
_QUERY_OPERATIONS = frozenset({"orders.query"})
_WIRE_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)


class _SyntheticEmptyLegacyClient:
    """Connectable Store leaf with empty local lists and no balance method."""

    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def get_positions(self) -> list[Any]:
        return []

    def fetch_open_orders(self) -> list[Any]:
        return []


class _SyntheticNoWriteProvider:
    """Local service dispatch leaf that rejects writes and reports call counts."""

    def __init__(self) -> None:
        self.submit_calls = 0
        self.cancel_calls = 0

    def submit(self, _intent: Any) -> None:
        self.submit_calls += 1
        raise RuntimeError("LOCAL_SYNTHETIC_PROVIDER_WRITES_DISABLED")

    def cancel(self, _intent: Any) -> None:
        self.cancel_calls += 1
        raise RuntimeError("LOCAL_SYNTHETIC_PROVIDER_WRITES_DISABLED")


class _SyntheticAdmissionGate:
    """Minimal gate surface for the local service component."""

    def reserve(self, intent: Any) -> Any:
        from types import SimpleNamespace

        reference = getattr(intent, "intent_id", None) or intent.cancel_id
        return SimpleNamespace(permit_id=f"synthetic-{reference}")

    def validate(self, permit_id: str, _intent: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(permit_id=permit_id)

    def claim_for_dispatch(self, permit_id: str, _intent: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(permit_id=permit_id)

    def claim_before_dispatch(self, permit_id: str, intent: Any) -> Any:
        from bt_api_execution import CancelDispatchClaimReceiptV1

        return CancelDispatchClaimReceiptV1(
            permit_reference=permit_id,
            scope_key=intent.scope.key,
            cancel_id=intent.cancel_id,
            intent_fingerprint=intent.fingerprint,
        )

    def release(self, _permit_id: str, _reason: str) -> None:
        return None

    def settle(self, _permit_id: str) -> None:
        return None


class _BarCounter(bt.Strategy):
    """Consume the deterministic local feed without creating orders."""

    def __init__(self) -> None:
        self.bars_seen = 0
        self.last_close = None

    def next(self) -> None:
        self.bars_seen += 1
        self.last_close = float(self.data.close[0])


def _client_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": "local-synthetic-listener-v1",
        "registration_policy_ref": "local-synthetic-registration-v1",
        "service_requirements_ref": "local-synthetic-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "local-synthetic-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SERVER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _serve_local_service(
    control: Any,
    endpoint: str,
    registry_path: str,
    store_path: str,
    keys: dict[str, bytes],
) -> None:
    """Serve one local synthetic execution component until normal close."""

    _configure_local_zmq_event_loop()
    provider = _SyntheticNoWriteProvider()
    gate = _SyntheticAdmissionGate()
    execution_store = None
    host = None
    try:
        config = parse_service_config(_service_config(endpoint))
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="local-synthetic-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-local-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="local-synthetic-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="local-synthetic-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={keys["strategy_public"]: _PRINCIPAL},
            grants={
                _PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ORDER_SCOPE_REF,
                                _WIRE_SCOPE,
                                _ORDER_OPERATIONS,
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_REF,
                                _WIRE_SCOPE,
                                _QUERY_OPERATIONS,
                            ),
                        ),
                    ),
                )
            },
        )
        execution_scope = ExecutionScope(
            "PAPER", "simulation", _ACCOUNT, _STRATEGY, _TRADING_DAY
        )
        execution_store = SqliteExecutionStore(store_path)

        def resource_provider(component: str, _instance_id: str, _options: Any, _scope: Any):
            if component != "execution":
                raise RuntimeError("UNEXPECTED_LOCAL_COMPONENT")
            return ComponentResources.borrowed(
                {
                    "store": execution_store,
                    "targets": {_WIRE_SCOPE: execution_scope},
                    "dispatch": provider,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=25)
            if control.poll(0):
                command = control.recv()
                if command != ("close",):
                    control.send(("error", "UNKNOWN_LOCAL_HOST_COMMAND"))
                    return
                host.close()
                execution_store.close()
                execution_store = None
                control.send(
                    (
                        "closed",
                        host.state,
                        provider.submit_calls,
                        provider.cancel_calls,
                    )
                )
                return
    except BaseException as error:
        code = getattr(error, "code", None)
        if type(code) is not str or not code.isascii() or len(code) > 64:
            code = type(error).__name__
        try:
            control.send(("error", code))
        except Exception:
            pass
        if host is not None and host.state not in {"closed", "failed"}:
            try:
                host.close()
            except BaseException:
                pass
        if execution_store is not None:
            try:
                execution_store.close()
            except BaseException:
                pass
    finally:
        control.close()


def _start_local_service(endpoint: str, directory: Path, keys: dict[str, bytes]) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(
        target=_serve_local_service,
        args=(
            child,
            endpoint,
            str(directory / "registry.sqlite3"),
            str(directory / "execution.sqlite3"),
            keys,
        ),
        name="backtrader-local-synthetic-execution",
    )
    process.start()
    child.close()
    host = {"process": process, "pipe": parent}
    if not parent.poll(15.0):
        _bound_failed_process_close(process)
        parent.close()
        raise RuntimeError("LOCAL_SYNTHETIC_HOST_START_TIMEOUT")
    ready = parent.recv()
    if not isinstance(ready, tuple) or ready[:1] != ("ready",):
        _bound_failed_process_close(process)
        parent.close()
        raise RuntimeError("LOCAL_SYNTHETIC_HOST_START_FAILED")
    if ready[1] != endpoint or ready[2] != "started":
        _bound_failed_process_close(process)
        parent.close()
        raise RuntimeError("LOCAL_SYNTHETIC_HOST_BIND_MISMATCH")
    return host


def _close_local_service_normally(host: dict[str, Any]) -> dict[str, Any]:
    process = host["process"]
    control = host["pipe"]
    if process.is_alive():
        control.send(("close",))
        if not control.poll(15.0):
            control.close()
            _bound_failed_process_close(process)
            raise RuntimeError("LOCAL_SYNTHETIC_HOST_CLOSE_TIMEOUT")
        result = control.recv()
    else:
        result = None
    process.join(10.0)
    if process.is_alive():
        control.close()
        _bound_failed_process_close(process)
        raise RuntimeError("LOCAL_SYNTHETIC_HOST_EXIT_UNPROVEN")
    exit_code = process.exitcode
    control.close()
    process.close()
    if exit_code != 0:
        raise RuntimeError("LOCAL_SYNTHETIC_HOST_EXIT_UNPROVEN")
    if not isinstance(result, tuple) or result[:2] != ("closed", "closed"):
        raise RuntimeError("LOCAL_SYNTHETIC_HOST_CLOSE_FAILED")
    return {
        "state": result[1],
        "provider_submit_calls": result[2],
        "provider_cancel_calls": result[3],
        "exit_code": exit_code,
    }


def _bound_failed_process_close(process: Any) -> None:
    """Avoid an unbounded synthetic child leak while keeping failure visible."""

    process.join(2.0)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
    if process.is_alive():
        process.kill()
        process.join(2.0)
    if not process.is_alive():
        process.close()


def _configure_local_zmq_event_loop() -> None:
    """Avoid pyzmq's Proactor compatibility warning in this short-lived CLI."""

    import asyncio

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is not None:
        asyncio.set_event_loop_policy(selector_policy())


def _validate_local_config(parsed: Any, endpoint: str) -> tuple[str, str]:
    if parsed.process_role != "strategy_client":
        raise ValueError("LOCAL_SYNTHETIC_ROLE_MISMATCH")
    if parsed.registration.get("strategy_ref") != _STRATEGY:
        raise ValueError("LOCAL_SYNTHETIC_STRATEGY_MISMATCH")
    execution = parsed.clients.get("execution")
    if execution is None:
        raise ValueError("LOCAL_SYNTHETIC_EXECUTION_CONFIG_MISSING")
    bindings = execution["settings"]["bindings"]
    by_mount = {binding["mount"]: binding for binding in bindings}
    if set(by_mount) != {"broker.orders", "broker.order_query"}:
        raise ValueError("LOCAL_SYNTHETIC_ROUTE_SET_MISMATCH")
    expected = {
        "broker.orders": (_ORDER_SCOPE_REF, _ORDER_OPERATIONS),
        "broker.order_query": (_QUERY_SCOPE_REF, _QUERY_OPERATIONS),
    }
    transport_refs = set()
    for mount, binding in by_mount.items():
        if (
            binding.get("service_id") != _SERVICE_ID
            or binding.get("instance_id") != _INSTANCE_ID
            or binding.get("scope_ref") != expected[mount][0]
            or binding.get("account_ref") != _ACCOUNT
            or binding.get("required") is not True
        ):
            raise ValueError("LOCAL_SYNTHETIC_ROUTE_BINDING_MISMATCH")
        transport_refs.add(binding.get("transport_ref"))
    if len(transport_refs) != 1:
        raise ValueError("LOCAL_SYNTHETIC_TRANSPORT_MISMATCH")
    transport_ref = next(iter(transport_refs))
    if transport_ref != _TRANSPORT_REF:
        raise ValueError("LOCAL_SYNTHETIC_TRANSPORT_MISMATCH")
    profile = parsed.communication["profiles"].get(transport_ref)
    if profile is None or profile.get("security_profile_ref") != _CLIENT_SECURITY_REF:
        raise ValueError("LOCAL_SYNTHETIC_SECURITY_REF_MISMATCH")
    if profile["endpoints"].get("rpc_connect") != endpoint:
        raise ValueError("LOCAL_SYNTHETIC_ENDPOINT_MISMATCH")
    return transport_ref, _CLIENT_SECURITY_REF


def _make_cerebro(csv_path: Path) -> tuple[bt.Cerebro, BtApiStore, Any]:
    api = _SyntheticEmptyLegacyClient()
    store = BtApiStore(
        provider="okx",
        api=api,
        cash=0.0,
        value=0.0,
        autostart=False,
    )
    broker = store.getbroker(
        cash=0.0,
        value=0.0,
        validation_enabled=False,
        cash_check_enabled=False,
        flatten_on_stop=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    cerebro.adddata(
        bt.feeds.GenericCSVData(
            dataname=str(csv_path),
            headers=False,
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
        ),
        name="SYNTHETIC-LOCAL",
    )
    cerebro.addstrategy(_BarCounter)
    return cerebro, store, api


def _load_example_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or set(value) != {"client_config"}:
        raise ValueError("EXAMPLE_CONFIG_SHAPE_INVALID")
    if type(value["client_config"]) is not dict:
        raise ValueError("EXAMPLE_CLIENT_CONFIG_INVALID")
    return value["client_config"]


def run_example(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    client_config = _load_example_config(config_path)
    endpoint = _client_endpoint()
    client_config["communication"]["profiles"][_TRANSPORT_REF]["endpoints"][
        "rpc_connect"
    ] = endpoint
    parsed = parse_client_config(client_config)
    transport_ref, security_ref = _validate_local_config(parsed, endpoint)

    import zmq

    keys = {
        "server_public": None,
        "server_secret": None,
        "strategy_public": None,
        "strategy_secret": None,
    }
    keys["server_public"], keys["server_secret"] = zmq.curve_keypair()
    keys["strategy_public"], keys["strategy_secret"] = zmq.curve_keypair()

    with tempfile.TemporaryDirectory(prefix="bt-service-session-") as temporary_directory:
        directory = Path(temporary_directory)
        csv_path = directory / "bars.csv"
        csv_path.write_text(
            "2026-10-15,100,102,99,101,1\n"
            "2026-10-16,101,103,100,102,1\n"
            "2026-10-17,102,104,101,103,1\n",
            encoding="ascii",
        )
        endpoint = parsed.communication["profiles"][transport_ref]["endpoints"]["rpc_connect"]
        cerebro, store, api = _make_cerebro(csv_path)
        host = _start_local_service(endpoint, directory, keys)
        runtime_holder = []
        try:
            def runtime_factory(config: Any) -> ServiceClientRuntime:
                route_profile = config.communication["profiles"][transport_ref]
                if route_profile["security_profile_ref"] != security_ref:
                    raise ValueError("LOCAL_SYNTHETIC_SECURITY_REF_MISMATCH")
                runtime = ServiceClientRuntime(
                    config,
                    identity=WireIdentity(
                        WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY
                    ),
                    scope_resolver=lambda reference: {
                        _ORDER_SCOPE_REF: _WIRE_SCOPE,
                        _QUERY_SCOPE_REF: _WIRE_SCOPE,
                    }[reference],
                    peer_resolver=lambda _service_id: WireIdentity(
                        WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
                    ),
                    transport_factory=ZmqTransportFactory(
                        {
                            security_ref: ClientCurveKeys(
                                keys["server_public"],
                                keys["strategy_public"],
                                keys["strategy_secret"],
                            )
                        }
                    ),
                    run_id="local-synthetic-cerebro-run",
                    requested_operations={
                        "broker.orders": _ORDER_OPERATIONS,
                        "broker.order_query": _QUERY_OPERATIONS,
                    },
                )
                runtime_holder.append(runtime)
                return runtime

            results = run_configured_cerebro(
                cerebro,
                client_config,
                runtime_factory=runtime_factory,
                runonce=False,
                preload=False,
            )
            if len(results) != 1 or not isinstance(results[0], _BarCounter):
                raise RuntimeError("LOCAL_SYNTHETIC_STRATEGY_RESULT_INVALID")
            strategy = results[0]
            runtime = runtime_holder[0]
            if not runtime_holder or runtime.state != "closed":
                raise RuntimeError("LOCAL_SYNTHETIC_RUNTIME_CLOSE_UNPROVEN")
            if runtime.cleanup_failures != 0 or runtime.unregister_uncertainties != 0:
                raise RuntimeError("LOCAL_SYNTHETIC_RUNTIME_CLEANUP_UNCERTAIN")
            if store.is_connected or api.connected:
                raise RuntimeError("LOCAL_SYNTHETIC_STORE_CLOSE_UNPROVEN")
            result = {
                "status": "LOCAL_SYNTHETIC_COMPLETED",
                "evidence": "LOCAL_SYNTHETIC_PUBLIC_CEREBRO_ENTRY_ONLY",
                "bars_seen": strategy.bars_seen,
                "last_close": strategy.last_close,
                "runtime_state": runtime.state,
                "runtime_cleanup_failures": runtime.cleanup_failures,
                "runtime_unregister_uncertainties": runtime.unregister_uncertainties,
                "configured_route_count": len(
                    parsed.clients["execution"]["settings"]["bindings"]
                ),
                "remaining_runtime_binding_count": len(runtime.bindings),
                "store_connected_after_run": store.is_connected,
                "account_cash_snapshot_observed": False,
                "legacy_position_and_order_inputs": "synthetic-empty",
                "synthetic_provider": "synthetic-no-write",
            }
        finally:
            try:
                if runtime_holder and runtime_holder[-1].state == "new":
                    runtime_holder[-1].close()
            finally:
                host_result = _close_local_service_normally(host)
        result.update(
            {
                "provider_submit_calls": host_result["provider_submit_calls"],
                "provider_cancel_calls": host_result["provider_cancel_calls"],
                "service_host_state": host_result["state"],
                "service_host_exit_code": host_result["exit_code"],
            }
        )
        return result, host_result


def _main(argv: list[str] | None = None) -> int:
    _configure_local_zmq_event_loop()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("config.example.json"),
        help="JSON wrapper containing one supported SDK client configuration",
    )
    args = parser.parse_args(argv)
    try:
        result, host_result = run_example(args.config)
        if not isinstance(host_result, Mapping) or host_result.get("state") != "closed":
            raise RuntimeError("LOCAL_SYNTHETIC_HOST_CLOSE_UNPROVEN")
        print("SERVICE_EXECUTION_SESSION_DEMO " + json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = getattr(error, "code", None)
        if type(code) is not str or not code.isascii() or len(code) > 64:
            code = type(error).__name__
        print("SERVICE_EXECUTION_SESSION_DEMO_ERROR " + code)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
