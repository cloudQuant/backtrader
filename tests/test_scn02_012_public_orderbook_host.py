"""012 public observation entry over four local Gateway Hosts.

This exercises the existing read-only public ``run.py`` route with two
independent SDK sessions.  All four Gateway processes are synthetic loopback
hosts; the result is not exchange, clock-alignment, or trading evidence.
"""

from __future__ import annotations

import importlib
import json
import multiprocessing
import os
import sys
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any
from multiprocessing.connection import wait as wait_connections

import pytest
import yaml
import zmq
from bt_api_base.account_protocol import AccountKey, AccountResourceKey
from bt_api_base.market_protocol import MarketInstrumentKey, MarketSubscriptionKey

from tests import test_service_read_proxy_integration as _fixture


_PRIVATE_ENV = (
    "OKX_DEMO_API_KEY",
    "OKX_DEMO_SECRET",
    "OKX_DEMO_PASSPHRASE",
    "BINANCE_DEMO_API_KEY",
    "BINANCE_DEMO_SECRET",
)
_CASES = (
    (
        "examples.unified.012_1_midfreq_cross_exchange.run",
        "012_1_midfreq_cross_exchange",
    ),
    (
        "examples.unified.012_2_event_driven_cross_exchange.run",
        "012_2_event_driven_cross_exchange",
    ),
)
_LEGS = (("okx", "BTC-USDT-SWAP"), ("binance", "BTCUSDT"))
_CHILD_ORIGIN_MODULES = (
    "tests.test_service_read_proxy_integration",
    "bt_api_base.account_protocol",
    "bt_api_gateway.account_session_worker",
    "bt_api_gateway.market_hub",
    "bt_api_py.service_host",
    "bt_api_py.bt_api",
    "bt_api_base.plugins.loader",
    "bt_api_transport_zmq",
)


@contextmanager
def _fixture_constants(values: dict[str, Any]):
    previous = {name: getattr(_fixture, name) for name in values}
    try:
        for name, value in values.items():
            setattr(_fixture, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(_fixture, name, value)


def _leg_constants(case_id: str, strategy_id: str, leg: str, symbol: str):
    token = f"scn02-012-{case_id}-{leg}"
    account_key = AccountKey(leg, leg, "demo", f"synthetic-{token}")
    resource = AccountResourceKey("swap", "cross")
    instrument = MarketInstrumentKey(
        provider=leg,
        venue=leg,
        environment="demo",
        product_type=resource.product_type,
        instrument_id=symbol,
        native_symbol=symbol,
    )
    names = {
        "_DOMAIN_REF": f"paper:{token}",
        "_STRATEGY_REF": strategy_id,
        "_CLIENT_PRINCIPAL": f"principal-{token}",
        "_ACCOUNT_SERVICE_ID": f"synthetic-account-{token}",
        "_ACCOUNT_INSTANCE_ID": f"account-{token}",
        "_ACCOUNT_SCOPE_REF": f"account-scope:{token}",
        "_ACCOUNT_TRANSPORT_REF": f"account-listener:{token}",
        "_ACCOUNT_CLIENT_TRANSPORT_REF": f"account-client:{token}",
        "_ACCOUNT_SECURITY_REF": f"account-curve:{token}",
        "_ACCOUNT_REF": f"account:{token}",
        "_JOURNAL_SCOPE": f"journal:{token}",
        "_STATE_SCOPE": f"state:{token}",
        "_MARKET_SERVICE_ID": f"synthetic-market-{token}",
        "_MARKET_INSTANCE_ID": f"market-{token}",
        "_MARKET_SCOPE_REF": f"market-scope:{token}",
        "_MARKET_TRANSPORT_REF": f"market-listener:{token}",
        "_MARKET_CLIENT_TRANSPORT_REF": f"market-client:{token}",
        "_MARKET_SECURITY_REF": f"market-curve:{token}",
        "_ACCOUNT_KEY": account_key,
        "_RESOURCE": resource,
        "_INSTRUMENT": instrument,
    }
    return names, account_key, resource, instrument


def _send_child_event(control, event: dict[str, Any]) -> None:
    try:
        control.send(("lifecycle", event))
    except (EOFError, OSError):
        pass


def _plugin_import_state() -> dict[str, Any]:
    bt_api_module = sys.modules.get("bt_api_py.bt_api")
    return {
        "bt_api_module_loaded": bt_api_module is not None,
        "plugins_loaded": getattr(bt_api_module, "_plugins_loaded", None),
        "plugin_loader_module_loaded": "bt_api_base.plugins.loader" in sys.modules,
    }


def _run_instrumented_host(control, role: str, target, *args) -> None:
    entered_ns = time.monotonic_ns()
    _send_child_event(
        control,
        {
            "event": "child_entry",
            "role": role,
            "pid": os.getpid(),
            "monotonic_ns": entered_ns,
            "plugin_import_state": _plugin_import_state(),
            "module_origins": {
                name: getattr(sys.modules.get(name), "__file__", None)
                for name in _CHILD_ORIGIN_MODULES
            },
        },
    )
    host_type = _fixture.ServiceHost
    original_start = host_type.start

    @wraps(original_start)
    def observed_start(host, *start_args, **kwargs):
        start_ns = time.monotonic_ns()
        _send_child_event(
            control,
            {
                "event": "host_start_enter",
                "role": role,
                "pid": os.getpid(),
                "monotonic_ns": start_ns,
                "elapsed_since_child_entry_ns": start_ns - entered_ns,
                "plugin_import_state": _plugin_import_state(),
            },
        )
        try:
            result = original_start(host, *start_args, **kwargs)
        except BaseException as exc:
            finished_ns = time.monotonic_ns()
            _send_child_event(
                control,
                {
                    "event": "host_start_error",
                    "role": role,
                    "pid": os.getpid(),
                    "monotonic_ns": finished_ns,
                    "elapsed_ns": finished_ns - start_ns,
                    "error_type": type(exc).__name__,
                    "plugin_import_state": _plugin_import_state(),
                },
            )
            raise
        finished_ns = time.monotonic_ns()
        _send_child_event(
            control,
            {
                "event": "host_start_return",
                "role": role,
                "pid": os.getpid(),
                "monotonic_ns": finished_ns,
                "elapsed_ns": finished_ns - start_ns,
                "host_state": host.state,
                "plugin_import_state": _plugin_import_state(),
            },
        )
        return result

    host_type.start = observed_start
    try:
        target(control, *args)
    finally:
        host_type.start = original_start


def _account_host_entry(control, *args) -> None:
    *host_args, values = args
    for name, value in values.items():
        setattr(_fixture, name, value)
    _run_instrumented_host(
        control, "account_session_worker", _fixture._account_service_process, *host_args
    )


def _market_host_entry(control, *args) -> None:
    *host_args, values = args
    for name, value in values.items():
        setattr(_fixture, name, value)
    _run_instrumented_host(control, "market_hub", _fixture._market_service_process, *host_args)


def _launch_host(context, target, args, label: str, role: str) -> dict[str, Any]:
    launch_ns = time.monotonic_ns()
    record = _fixture._start_process(context, target, args, label)
    record.update(
        {
            "role": role,
            "pid": record["process"].pid,
            "parent_launch_ns": launch_ns,
            "parent_start_return_ns": time.monotonic_ns(),
            "lifecycle_events": [],
            "wait_events": [],
        }
    )
    return record


def _install_diagnostic_receive(records: list[dict[str, Any]]):
    original_receive = _fixture._receive

    def receive(pipe, timeout: float = 45.0):
        record = next((item for item in records if id(item["pipe"]) == id(pipe)), None)
        if record is None:
            return original_receive(pipe, timeout)
        process = record["process"]
        wait_started_ns = time.monotonic_ns()
        deadline = time.monotonic() + timeout
        pipe_eof = False
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            waitables = [process.sentinel] if pipe_eof else [pipe, process.sentinel]
            ready = wait_connections(waitables, timeout=remaining)
            if not pipe_eof and pipe in ready:
                try:
                    message = pipe.recv()
                except EOFError:
                    record["pipe_eof_ns"] = time.monotonic_ns()
                    pipe_eof = True
                    message = None
                if message is not None:
                    now_ns = time.monotonic_ns()
                    if message[0] == "lifecycle":
                        record["lifecycle_events"].append(message[1])
                        continue
                    record["wait_events"].append(
                        {
                            "message": message[0],
                            "monotonic_ns": now_ns,
                            "wait_duration_ns": now_ns - wait_started_ns,
                        }
                    )
                    if message[0] == "ready":
                        record["ready_received_ns"] = now_ns
                        record["ready_status"] = message[-1]
                    elif message[0] == "closed":
                        record["close_ack_received_ns"] = now_ns
                        record["close_status"] = message[-1]
                    elif message[0] == "error":
                        record["child_error"] = message[1] if len(message) > 1 else None
                    return message
            if process.sentinel in ready:
                process.join(0)
                record["child_exit_observed_ns"] = time.monotonic_ns()
                record["exitcode"] = process.exitcode
                if not pipe_eof and pipe.poll():
                    continue
                record["wait_timeout_or_exit_ns"] = time.monotonic_ns()
                record["wait_duration_ns"] = record["wait_timeout_or_exit_ns"] - wait_started_ns
                raise AssertionError(
                    f"{record['label']} exited before expected response; "
                    f"pid={record['pid']} exitcode={record['exitcode']}"
                )
            if not ready:
                record["wait_timeout_or_exit_ns"] = time.monotonic_ns()
                record["wait_duration_ns"] = record["wait_timeout_or_exit_ns"] - wait_started_ns
                raise AssertionError(
                    f"{record['label']} missed response bound; pid={record['pid']} "
                    f"last_child_phase={record['lifecycle_events'][-1]['event'] if record['lifecycle_events'] else 'child_entry_unobserved'}"
                )

    _fixture._receive = receive
    return original_receive


def _close_host_diagnostically(record: dict[str, Any]) -> tuple[Any, ...]:
    process = record["process"]
    if not process.is_alive():
        record["close_skipped_process_not_alive_ns"] = time.monotonic_ns()
        raise AssertionError(f"{record['label']} exited before normal close")
    record["close_requested_ns"] = time.monotonic_ns()
    record["pipe"].send(("close",))
    record["close_requested"] = True
    deadline = time.monotonic() + 15.0
    while True:
        remaining = max(0.0, deadline - time.monotonic())
        reply = _fixture._receive(record["pipe"], timeout=remaining)
        if reply[0] == "ready":
            continue
        assert reply[0] == "closed", (record["label"], reply)
        break
    process.join(15)
    record["join_returned_ns"] = time.monotonic_ns()
    record["alive_after_join"] = process.is_alive()
    record["exitcode"] = process.exitcode
    assert not record["alive_after_join"], f"{record['label']} did not exit within its bound"
    assert record["exitcode"] == 0, f"{record['label']} exited with {record['exitcode']}"
    record["pipe"].close()
    record["pipe_closed"] = True
    process.close()
    record["process_closed"] = True
    record["closed"] = True
    return reply


def _bounded_reap_diagnostically(
    record: dict[str, Any], forced: list[str], failures: list[str]
) -> None:
    if record["closed"]:
        return
    process = record["process"]
    pipe = record["pipe"]

    if process.is_alive() and not record["close_requested"]:
        try:
            record["close_requested_ns"] = time.monotonic_ns()
            pipe.send(("close",))
            record["close_requested"] = True
        except Exception as exc:
            failures.append(f"{record['label']}:close_send:{type(exc).__name__}")

    drain_deadline = time.monotonic() + 2.0
    while process.is_alive() and time.monotonic() < drain_deadline:
        try:
            reply = _fixture._receive(pipe, timeout=max(0.0, drain_deadline - time.monotonic()))
        except AssertionError:
            break
        except Exception as exc:
            failures.append(f"{record['label']}:close_reply:{type(exc).__name__}")
            break
        if reply[0] == "closed":
            break
        if reply[0] not in {"ready", "status"}:
            failures.append(f"{record['label']}:close_reply:{reply[0]}")

    try:
        process.join(5)
    except Exception as exc:
        failures.append(f"{record['label']}:join:{type(exc).__name__}")
    record["join_returned_ns"] = time.monotonic_ns()
    record["alive_after_join"] = process.is_alive()
    if process.is_alive():
        forced.append(record["label"])
        record["terminate_requested_ns"] = time.monotonic_ns()
        try:
            process.terminate()
        except Exception as exc:
            failures.append(f"{record['label']}:terminate:{type(exc).__name__}")
        try:
            process.join(5)
        except Exception as exc:
            failures.append(f"{record['label']}:terminate_join:{type(exc).__name__}")
    if process.is_alive():
        record["kill_requested_ns"] = time.monotonic_ns()
        try:
            process.kill()
        except Exception as exc:
            failures.append(f"{record['label']}:kill:{type(exc).__name__}")
        try:
            process.join(5)
        except Exception as exc:
            failures.append(f"{record['label']}:kill_join:{type(exc).__name__}")

    record["exitcode"] = process.exitcode
    record["child_exit_observed_ns"] = time.monotonic_ns() if not process.is_alive() else None
    try:
        pipe.close()
        record["pipe_closed"] = True
    except Exception as exc:
        failures.append(f"{record['label']}:pipe_close:{type(exc).__name__}")
    if process.is_alive():
        failures.append(f"{record['label']}:still_alive_after_kill")
        return
    if process.exitcode not in (0, None):
        failures.append(f"{record['label']}:unexpected_exit:{process.exitcode}")
    try:
        process.close()
        record["process_closed"] = True
    except Exception as exc:
        failures.append(f"{record['label']}:process_close:{type(exc).__name__}")
    record["closed"] = True


def _lifecycle_report(
    case_id: str,
    strategy_id: str,
    records: list[dict[str, Any]],
    test_failure: dict[str, Any] | None,
    publisher_errors: list[str],
    cleanup_failures: list[str],
    forced_cleanup: list[str],
) -> dict[str, Any]:
    fields = (
        "label",
        "role",
        "pid",
        "parent_launch_ns",
        "parent_start_return_ns",
        "lifecycle_events",
        "wait_events",
        "ready_received_ns",
        "ready_status",
        "close_requested_ns",
        "close_ack_received_ns",
        "close_status",
        "join_returned_ns",
        "alive_after_join",
        "exitcode",
        "terminate_requested_ns",
        "kill_requested_ns",
        "child_exit_observed_ns",
        "pipe_closed",
        "process_closed",
        "closed",
        "pipe_eof_ns",
        "wait_timeout_or_exit_ns",
        "wait_duration_ns",
        "child_error",
        "forced_cleanup",
        "cleanup_failures",
    )
    hosts = []
    for record in records:
        row = {name: record.get(name) for name in fields}
        events = record.get("lifecycle_events", [])
        entry = next((event for event in events if event.get("event") == "child_entry"), None)
        start_enter = next((event for event in events if event.get("event") == "host_start_enter"), None)
        start_return = next((event for event in events if event.get("event") in {"host_start_return", "host_start_error"}), None)
        if entry is not None:
            row["parent_to_child_entry_ns"] = entry["monotonic_ns"] - record["parent_launch_ns"]
        if entry is not None and start_enter is not None:
            row["child_entry_to_host_start_ns"] = start_enter["monotonic_ns"] - entry["monotonic_ns"]
        if start_return is not None:
            row["host_start_elapsed_ns"] = start_return.get("elapsed_ns")
        if record.get("close_ack_received_ns") is not None:
            row["close_ack_elapsed_ns"] = (
                record["close_ack_received_ns"] - record.get("close_requested_ns", record["close_ack_received_ns"])
            )
        hosts.append(row)
    return {
        "case_id": case_id,
        "strategy_id": strategy_id,
        "parent_pid": os.getpid(),
        "test_failure": test_failure,
        "hosts": hosts,
        "publisher_errors": list(publisher_errors),
        "forced_cleanup": list(forced_cleanup),
        "cleanup_failures": list(cleanup_failures),
    }


def _service_material(tmp_path: Path, case_id: str, strategy_id: str, leg: str, symbol: str):
    values, account_key, resource, instrument = _leg_constants(case_id, strategy_id, leg, symbol)
    account_rpc, market_rpc, market_pub = _fixture._free_endpoints(3)
    account_server_keys = zmq.curve_keypair()
    market_server_keys = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    key = MarketSubscriptionKey(
        source_ref=f"source:{case_id}:{leg}",
        entitlement_ref=f"entitlement:{case_id}:{leg}",
        instrument=instrument,
        channel="orderbook",
        depth=3,
    )
    with _fixture_constants(values):
        account_raw = _fixture._service_config(
            service_id=values["_ACCOUNT_SERVICE_ID"],
            scope_ref=values["_ACCOUNT_SCOPE_REF"],
            transport_ref=values["_ACCOUNT_TRANSPORT_REF"],
            instance_id=values["_ACCOUNT_INSTANCE_ID"],
            bind_ports=["service.account_read", "service.provider_session"],
            options={
                "role": "account_session_worker",
                "account_session_ref": f"account-session:{case_id}:{leg}",
            },
            rpc_bind=account_rpc,
            security_ref=values["_ACCOUNT_SECURITY_REF"],
        )
        market_raw = _fixture._service_config(
            service_id=values["_MARKET_SERVICE_ID"],
            scope_ref=values["_MARKET_SCOPE_REF"],
            transport_ref=values["_MARKET_TRANSPORT_REF"],
            instance_id=values["_MARKET_INSTANCE_ID"],
            bind_ports=["service.market_source"],
            options={"role": "market_hub"},
            rpc_bind=market_rpc,
            market_bind=market_pub,
            security_ref=values["_MARKET_SECURITY_REF"],
        )
        client = _fixture._client_config(account_rpc, market_rpc, market_pub)

    env_prefix = f"SCN02_012_{case_id}_{leg}".upper().replace("-", "_")
    account_env = {
        "server_key_env": f"{env_prefix}_ACCOUNT_SERVER_KEY",
        "client_public_key_env": f"{env_prefix}_CLIENT_PUBLIC_KEY",
        "client_secret_key_env": f"{env_prefix}_CLIENT_SECRET_KEY",
    }
    market_env = {
        "server_key_env": f"{env_prefix}_MARKET_SERVER_KEY",
        "client_public_key_env": account_env["client_public_key_env"],
        "client_secret_key_env": account_env["client_secret_key_env"],
    }
    env_values = {
        account_env["server_key_env"]: account_server_keys[0].decode("ascii"),
        market_env["server_key_env"]: market_server_keys[0].decode("ascii"),
        account_env["client_public_key_env"]: client_public.decode("ascii"),
        account_env["client_secret_key_env"]: client_secret.decode("ascii"),
    }
    service = {
        "client_config": client,
        "identity": {
            "principal_ref": values["_CLIENT_PRINCIPAL"],
            "strategy_ref": strategy_id,
            "execution_domain_ref": values["_DOMAIN_REF"],
        },
        "service_principals": {
            values["_ACCOUNT_SERVICE_ID"]: "principal-account-service",
            values["_MARKET_SERVICE_ID"]: "principal-market-service",
        },
        "curve_key_envs": {
            values["_ACCOUNT_SECURITY_REF"]: account_env,
            values["_MARKET_SECURITY_REF"]: market_env,
        },
        "account": {
            "mount": "store.account",
            "account_ref": values["_ACCOUNT_REF"],
            "key": account_key.to_dict(),
            "required_coverage": [resource.to_dict()],
            "resource_by_leg": {leg: resource.to_dict()},
            "valuation_currency": "USD",
            "position_mode": "net",
            "qty_unit": "contracts",
        },
        "market": {
            "mount": "store.market",
            "source_ref": key.source_ref,
            "entitlement_ref": key.entitlement_ref,
        },
    }
    path = tmp_path / f"{leg}-service.yaml"
    path.write_text(yaml.safe_dump(service, sort_keys=True), encoding="utf-8")
    return {
        "values": values,
        "account_key": account_key,
        "resource": resource,
        "instrument": instrument,
        "market_key": key,
        "account_raw": account_raw,
        "market_raw": market_raw,
        "account_server_keys": account_server_keys,
        "market_server_keys": market_server_keys,
        "client_public": client_public,
        "config_path": path,
        "env_values": env_values,
    }


def _start_leg_hosts(
    context,
    tmp_path: Path,
    case_id: str,
    leg: str,
    material: dict[str, Any],
    records: list[dict[str, Any]],
):
    values = material["values"]
    account_guard = tmp_path / f"{leg}-account-guard"
    account_guard.mkdir()
    account = _launch_host(
        context,
        _account_host_entry,
        (
            material["account_raw"],
            str(tmp_path / f"{leg}-account-registry.sqlite3"),
            str(tmp_path / f"{leg}-account-journal.sqlite3"),
            str(account_guard),
            material["account_server_keys"],
            material["client_public"],
            values,
        ),
        f"scn02-012-{case_id}-{leg}-account-session-worker-host",
        "account_session_worker",
    )
    records.append(account)
    market = _launch_host(
        context,
        _market_host_entry,
        (
            material["market_raw"],
            str(tmp_path / f"{leg}-market-registry.sqlite3"),
            material["market_server_keys"],
            material["client_public"],
            material["market_key"],
            values,
        ),
        f"scn02-012-{case_id}-{leg}-market-hub-host",
        "market_hub",
    )
    records.append(market)
    account_ready = _fixture._receive(account["pipe"])
    market_ready = _fixture._receive(market["pipe"])
    assert account_ready[0] == "ready" and account_ready[1] == material["account_raw"]["communication"]["profiles"][values["_ACCOUNT_TRANSPORT_REF"]]["endpoints"]["rpc_bind"]
    assert account_ready[2]["host"] == "started" and account_ready[2]["ready"] is True
    assert account_ready[2]["connect_calls"] == 1 and account_ready[2]["read_calls"] == 1
    assert account_ready[2]["close_calls"] == 0 and account_ready[2]["provider_write_methods"] == ()
    assert market_ready[0] == "ready"
    market_endpoints = material["market_raw"]["communication"]["profiles"][values["_MARKET_TRANSPORT_REF"]]["endpoints"]
    assert market_ready[1] == market_endpoints["rpc_bind"]
    assert market_ready[2] == market_endpoints["market_bind"]
    assert market_ready[3]["host"] == "started" and market_ready[3]["readiness"]["ready"] is True
    assert market_ready[3]["source_starts"] == 0 and market_ready[3]["source_stops"] == 0
    return account, market


def _publish_after_subscribe(record: dict[str, Any], published: list, errors: list[str]) -> None:
    deadline = time.monotonic() + 15.0
    try:
        while time.monotonic() < deadline:
            if not record["process"].is_alive():
                raise AssertionError("market host exited before subscription")
            response = _fixture._host_command(record, "status", timeout=1.0)
            if response[1]["source_starts"] == 1:
                published.append(_fixture._host_command(record, "publish", 0, timeout=3.0))
                return
            time.sleep(0.01)
        raise AssertionError("market subscription did not reach synthetic provider")
    except BaseException as exc:
        errors.append(type(exc).__name__)


@pytest.mark.parametrize(("runner_module", "strategy_id"), _CASES)
def test_012_public_live_observe_entry_uses_two_clients_and_four_synthetic_hosts(
    runner_module: str,
    strategy_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case_id = strategy_id[:5]
    materials = {
        leg: _service_material(tmp_path, case_id, strategy_id, leg, symbol)
        for leg, symbol in _LEGS
    }
    for name in _PRIVATE_ENV:
        monkeypatch.delenv(name, raising=False)
    for material in materials.values():
        for name, value in material["env_values"].items():
            monkeypatch.setenv(name, value)

    context = multiprocessing.get_context("spawn")
    records: list[dict[str, Any]] = []
    original_receive = _install_diagnostic_receive(records)
    publishers: list[threading.Thread] = []
    publisher_errors: list[str] = []
    published: dict[str, list] = {leg: [] for leg, _symbol in _LEGS}
    closed_status: dict[str, dict[str, Any]] = {}
    forced_cleanup: list[str] = []
    cleanup_failures: list[str] = []
    test_failure: dict[str, Any] | None = None
    try:
        for leg, _symbol in _LEGS:
            _start_leg_hosts(context, tmp_path, case_id, leg, materials[leg], records)
        roles = [record["role"] for record in records]
        assert roles == ["account_session_worker", "market_hub", "account_session_worker", "market_hub"]
        assert len({record["process"].name for record in records}) == 4
        for record in records:
            assert record["process"].name == record["label"]

        for leg, _symbol in _LEGS:
            market = next(record for record in records if record["label"].endswith(f"{leg}-market-hub-host"))
            thread = threading.Thread(
                target=_publish_after_subscribe,
                args=(market, published[leg], publisher_errors),
                name=f"scn02-012-{case_id}-{leg}-synthetic-publisher",
                daemon=True,
            )
            publishers.append(thread)
            thread.start()

        runner = importlib.import_module(runner_module)
        exit_code = runner.main(
            [
                "--live",
                "--service-config-okx",
                str(materials["okx"]["config_path"]),
                "--service-config-binance",
                str(materials["binance"]["config_path"]),
                "--service-observation-timeout-ms",
                "4000",
                "--service-book-depth",
                "3",
            ]
        )
        output = capsys.readouterr().out.strip().splitlines()
        assert output, "public run.py entry emitted no report"
        report = json.loads(output[-1])
        assert exit_code == runner.EXIT_PASS, report
        assert report["status"] == "OBSERVED"
        assert report["mode"] == "live" and report["channel"] == "observe"
        assert report["example_id"] == strategy_id
        assert report["strategy_id"] == strategy_id
        assert report["write_grant_result"] == "not_requested"
        assert report["write_capability"] == "UNSUPPORTED"
        assert report["trade_execution"] == "not_run"
        assert report["execution_eligible"] is False
        assert report["cross_venue_alignment"] == "NOT_EVALUATED"
        assert report["clock_mapping_qualified"] is False
        assert report["research_status"] == "RESEARCH_REJECTED"
        assert report["observation_level"] == "INDEPENDENT_SERVICE_ORDERBOOK_SNAPSHOTS"
        assert len(report["legs"]) == 2
        assert [row["leg"] for row in report["legs"]] == ["okx", "binance"]
        assert len({row["account_snapshot"]["account_key_id"] for row in report["legs"]}) == 2
        for row, (leg, symbol) in zip(report["legs"], _LEGS, strict=True):
            assert row["status"] == "OBSERVED"
            account = row["account_snapshot"]
            assert account["facade_healthy"] is True and account["fresh"] is True
            assert account["balances_complete"] is True
            assert account["positions_complete"] is True
            assert account["open_orders_complete"] is True
            assert account["coverage_count"] == 1
            assert "balances" not in account and "positions" not in account and "open_orders" not in account
            source = row["source"]
            assert source["key_matches"] is True and type(source["stream_id"]) is str and source["stream_id"]
            assert source["execution_eligible"] is False
            assert source["clock_mapping_qualified"] is False and source["freshness_qualified"] is False
            book = row["orderbook"]
            assert book["symbol"] == symbol
            assert book["exchange"] == leg
            assert book["product_type"] == "swap"
            assert book["sequence"] == 1 and book["continuity_status"] == "snapshot"
            assert book["stale"] is False and book["depth"] == 3
            assert book["qty_unit"] == "contracts" and book["quantity_multiplier"] == "1"
            assert len(book["bids"]) == len(book["asks"]) == 2
            assert row["cleanup"]["status"] == "PASS"
            assert row["cleanup"]["facades_closed"] is True
            assert row["cleanup"]["runtime_closed"] is True
            assert row["cleanup"]["runtime_cleanup_failures"] == 0
            assert row["cleanup"]["runtime_unregister_uncertainties"] == 0
            assert row["cleanup"]["runtime_unknown_registrations"] == 0
        for publisher in publishers:
            publisher.join(16.0)
            assert not publisher.is_alive(), f"{publisher.name} missed its bound"
        assert all(len(published[leg]) == 1 for leg, _symbol in _LEGS)
        assert publisher_errors == []
        for leg, _symbol in _LEGS:
            account = next(
                record
                for record in records
                if record["role"] == "account_session_worker" and f"-{leg}-" in record["label"]
            )
            market = next(
                record
                for record in records
                if record["role"] == "market_hub" and f"-{leg}-" in record["label"]
            )
            account_status = _fixture._host_command(account, "status")[1]
            assert account_status["host"] == "started" and account_status["ready"] is True
            assert account_status["connect_calls"] == 1 and account_status["read_calls"] == 1
            assert account_status["close_calls"] == 0 and account_status["provider_write_methods"] == ()
            market_status = _fixture._host_command(market, "status")[1]
            assert market_status["host"] == "started"
            assert market_status["source_starts"] == 1 and market_status["source_stops"] == 1
            assert market_status["history_calls"] == 0
    except BaseException as exc:
        test_failure = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        for publisher in publishers:
            publisher.join(16.0)
            if publisher.is_alive():
                cleanup_failures.append(f"{publisher.name}:join_timeout")
        for record in reversed(records):
            if record["closed"]:
                continue
            try:
                reply = _close_host_diagnostically(record)
                closed_status[record["label"]] = reply[1]
            except BaseException as exc:
                cleanup_failures.append(f"{record['label']}:normal_close:{type(exc).__name__}")
        for record in reversed(records):
            if not record["closed"]:
                _bounded_reap_diagnostically(record, forced_cleanup, cleanup_failures)
        for record in records:
            record["forced_cleanup"] = record["label"] in forced_cleanup
            record["cleanup_failures"] = [
                item for item in cleanup_failures if record["label"] in item
            ]
        _fixture._receive = original_receive
        diagnostic_path = tmp_path / "host-lifecycle-diagnostic.json"
        diagnostic_path.write_text(
            json.dumps(
                _lifecycle_report(
                    case_id,
                    strategy_id,
                    records,
                    test_failure,
                    publisher_errors,
                    cleanup_failures,
                    forced_cleanup,
                ),
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"SCN02_012_HOST_DIAGNOSTIC={diagnostic_path}")
        assert cleanup_failures == [], cleanup_failures
        assert forced_cleanup == [], forced_cleanup

    for leg, _symbol in _LEGS:
        account = next(record for record in records if record["role"] == "account_session_worker" and f"-{leg}-" in record["label"])
        market = next(record for record in records if record["role"] == "market_hub" and f"-{leg}-" in record["label"])
        assert account["closed"] and market["closed"]
        account_after_close = closed_status[account["label"]]
        assert account_after_close["host"] == "closed"
        assert account_after_close["close_calls"] == 1
        assert account_after_close["provider_write_methods"] == ()
        market_after_close = closed_status[market["label"]]
        assert market_after_close["host"] == "closed"
        assert market_after_close["source_starts"] == 1 and market_after_close["source_stops"] == 1
        assert market_after_close["history_calls"] == 0
