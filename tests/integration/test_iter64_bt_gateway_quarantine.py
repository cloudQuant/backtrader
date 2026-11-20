"""64.09: real CURVE Gateway/Risk sessions with a BT local v1 gate.

Only INTEGRATION_SIM evidence: provider, account, market qualification and
CLOSE capacity are synthetic. The SDK returns UNKNOWN locally; these BT
orders do not reach the Risk process. This does not prove a source cut or
cross-generation absence, and the test does not seed an authorized cancel.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from types import SimpleNamespace

import backtrader as bt
import pytest
import zmq
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.gateway_strategy_position import GatewayStrategyPositionObservation, GatewayStrategyPositionResult
from bt_api_py.risk_service_client import RiskClientRoute, RiskServiceClient
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory

from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.integration.iter64_bt_quarantine_gateway_support import (
    _report, _retain_forever, _run_child, _write_protected_key,
)
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework


import bt_api_py

SDK_ROOT = Path(bt_api_py.__file__).resolve().parent.parent
GATEWAY_HELPER = Path(__file__).with_name("iter64_bt_quarantine_gateway_support.py")
ACCOUNT, DOMAIN, RUN = "account-a", "paper:demo", "strategy-run"
GATEWAY = WireIdentity(WireRole.SERVICE, "gateway-principal", "gateway-service")
STRATEGY = WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", "strategy-a")
RISK_HOST = WireIdentity(WireRole.SERVICE, "risk-host", "risk-service")
OPERATOR = WireIdentity(WireRole.APPLICATION_CLIENT, "risk-operator", "risk-operator-actor")
SCOPE = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY.actor_ref, run_id=RUN)
ACCOUNT_ONLY = WireScope(DOMAIN, account_ref=ACCOUNT)
INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb", "rb")
ROUTE = "CTP___FUTURE"
_RETAINED_OBJECTS = []


class SyntheticCleanupUncertain(RuntimeError):
    """A test-owned resource could not be proven closed; preserve the hosts."""


class SyntheticKeys(dict):
    def __repr__(self):
        return "<synthetic keys redacted>"


def _error_category(error):
    if isinstance(error, SyntheticCleanupUncertain):
        return "cleanup_uncertain"
    if isinstance(error, AssertionError):
        return "assertion"
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    if isinstance(error, SystemExit):
        return "system_exit"
    return "other"


def _zero_count(value):
    return type(value) is int and value == 0


def _private_file(path, mode):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    if os.fstat(descriptor).st_mode & 0o777 != 0o600:
        os.close(descriptor)
        raise RuntimeError("synthetic_private_file_permissions")
    return os.fdopen(descriptor, mode)


def _snapshot_closed(snapshot, *, strict):
    return (snapshot.state == "closed" and snapshot.thread_alive is False
            and _zero_count(snapshot.cleanup_failures) and _zero_count(snapshot.unregister_uncertainties)
            and _zero_count(snapshot.owner_cleanup_uncertainties)
            and _zero_count(snapshot.unknown_registration_count)
            and snapshot.strict_unregister_ack is strict)


def _endpoint() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return "tcp://127.0.0.1:" + str(listener.getsockname()[1])


def _wait_for(predicate, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("synthetic_readiness_timeout")


def _events(path):
    return [] if not path.exists() else [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _gateway_events_valid(records, pid, *, terminal):
    """Validate only this child's finite lifecycle messages, including conflicts."""
    if type(records) is not list or type(pid) is not int:
        return False
    ordinary = {"ready", "observing", "reporter_probe", "closed"}
    counts = dict.fromkeys(ordinary, 0)
    cleanup_steps = []
    for item in records:
        if type(item) is not dict or type(item.get("pid")) is not int or item["pid"] != pid:
            return False
        kind = item.get("event")
        if type(kind) is not str or counts["closed"]:
            return False
        if cleanup_steps and kind not in {"cleanup_step", "closed"}:
            return False
        if kind in ordinary:
            if set(item) != {"event", "pid"}:
                return False
            counts[kind] += 1
        elif kind == "cleanup_step":
            if (set(item) != {"event", "pid", "step", "code"}
                    or item["step"] not in {"host", "owner"} or item["code"] != "ok"):
                return False
            cleanup_steps.append(item["step"])
        else:
            # Includes error, cleanup_uncertain, and unknown event kinds.
            return False
    if (counts["ready"] != 1 or counts["observing"] > 1
            or not records or records[0] != {"event": "ready", "pid": pid}):
        return False
    if terminal:
        return (counts["closed"] == 1 and records[-1] == {"event": "closed", "pid": pid}
                and cleanup_steps == ["host", "owner"])
    return counts["closed"] == 0 and not cleanup_steps


def _pre_stop_check(gateway, risk, events, *, risk_stopped):
    """Check only this test's owned children and its finite event channel."""
    if gateway.poll() is not None or gateway.stdin is None or gateway.stdin.closed:
        return False
    if risk is not None:
        if risk_stopped:
            if risk.returncode != 0:
                return False
        elif risk.poll() is not None:
            return False
    try:
        records = _events(events)
        if not _gateway_events_valid(records, gateway.pid, terminal=False):
            return False
        probe = {"event": "reporter_probe", "pid": gateway.pid}
        previous_probes = records.count(probe)
        gateway.stdin.write(b"probe\n")
        gateway.stdin.flush()
        _wait_for(lambda: _events(events).count(probe) > previous_probes, seconds=5)
        records = _events(events)
        if gateway.poll() is not None or not _gateway_events_valid(records, gateway.pid, terminal=False):
            return False
        return risk is None or (risk.returncode == 0 if risk_stopped else risk.poll() is None)
    except BaseException:
        return False


def _client_config(endpoint, *, risk=False):
    mount = "broker.risk_order" if risk else "broker.direct_write"
    service = RISK_HOST.actor_ref if risk else GATEWAY.actor_ref
    instance, scope = ("risk-a", "risk-scope") if risk else ("gateway-a", "scope-a")
    return parse_client_config({
        "client_config_schema_version": 1, "process_role": "strategy_client",
        "registration": {"strategy_ref": STRATEGY.actor_ref},
        "clients": {("risk" if risk else "gateway"): {"config_schema_version": 1, "settings": {"bindings": [{
            "mount": mount, "service_id": service, "instance_id": instance,
            "scope_ref": scope, "account_ref": ACCOUNT, "transport_ref": "transport",
            "required": True,
        }]}}},
        "communication": {"config_schema_version": 1, "profiles": {"transport": {
            "backend": "zmq", "config_schema_version": 1,
            "endpoints": {"rpc_connect": endpoint}, "security_profile_ref": "security",
        }}},
    })


def _risk_client(endpoint, keys):
    route = RiskClientRoute("broker.risk_order", RISK_HOST.actor_ref, "risk-a", "risk-scope", SCOPE, STRATEGY)
    return RiskServiceClient.compose(
        _client_config(endpoint, risk=True), route=route, peer=RISK_HOST,
        security_profiles={"security": ClientCurveKeys(keys["risk_server"][0], *keys["strategy"])},
        requested_operations=frozenset({"risk.order.reserve", "risk.order.dispatch", "risk.order.release",
                                        "risk.order.status", "risk.status"}),
    )


def _close_operator(client, precheck):
    try:
        if precheck() is not True:
            raise SyntheticCleanupUncertain("operator_preclose_uncertain")
        client.close()
        if (client.state != "closed" or not _zero_count(client.cleanup_failures)
                or not _zero_count(client.unregister_uncertainties)
                or not _zero_count(client.unknown_registration_count)):
            raise SyntheticCleanupUncertain("operator_cleanup_uncertain")
    except BaseException:
        _RETAINED_OBJECTS.append(client)
        raise SyntheticCleanupUncertain("operator_cleanup_uncertain") from None


def _operator_failed_start_cleanup(client, original_error, precheck):
    try:
        state = client.state
        safe = (not isinstance(original_error, SyntheticCleanupUncertain)
                and type(state) is str and state in {"failed", "registered", "closed"}
                and _zero_count(client.unknown_registration_count)
                and _zero_count(client.unregister_uncertainties)
                and _zero_count(client.cleanup_failures))
    except BaseException as read_error:
        _RETAINED_OBJECTS.extend((client, original_error, read_error))
        raise SyntheticCleanupUncertain("operator_start_state_uncertain") from None
    if not safe:
        _RETAINED_OBJECTS.extend((client, original_error))
        raise SyntheticCleanupUncertain("operator_start_state_uncertain") from None
    try:
        _close_operator(client, precheck)
    except BaseException as close_error:
        _RETAINED_OBJECTS.extend((client, original_error, close_error))
        raise SyntheticCleanupUncertain("operator_cleanup_uncertain") from None


def _close_strategy(api, precheck):
    if precheck() is not True:
        raise SyntheticCleanupUncertain("strategy_preclose_uncertain")
    return api.close(timeout_seconds=15)


def _construct_case_resources(make_binding, make_host, make_session, make_risk, make_api):
    retained = []
    stage = "binding"
    try:
        binding = make_binding()
        retained.append(binding)
        stage = "host"
        state_host = make_host(binding)
        retained.append(state_host)
        state, host = state_host
        stage = "session"
        session = make_session(binding, host)
        retained.append(session)
        stage = "risk"
        risk = make_risk()
        retained.append(risk)
        stage = "api"
        api = make_api(session, risk)
        retained.append(api)
        return binding, state, host, session, risk, api
    except BaseException as error:
        _RETAINED_OBJECTS.extend(retained)
        # Retain the original traceback in memory as well: a constructor may
        # have acquired an object before raising without returning it.
        _RETAINED_OBJECTS.append(error)
        print(f"TEST_STAGE stage=construct_{stage} code={_error_category(error)}", flush=True)
        raise SyntheticCleanupUncertain("case_construction_uncertain") from None


def _finish_case(api, risk, session, host, state, binding, precheck, primary_error, case):
    if primary_error == "cleanup_uncertain":
        _RETAINED_OBJECTS.extend((api, risk, session, host, state, binding))
        if sys.exc_info()[1] is not None:
            _RETAINED_OBJECTS.append(sys.exc_info()[1])
        print(f"TEST_CLOSE case={case} step=close code=uncertain original=cleanup_uncertain", flush=True)
        raise SyntheticCleanupUncertain("strategy_cleanup_uncertain") from None
    try:
        closed = _close_strategy(api, precheck)
        gateway_closed = _snapshot_closed(closed, strict=False)
        print(f"TEST_CLOSE case={case} step=gateway code={'ok' if gateway_closed else 'uncertain'}", flush=True)
        risk_closed = risk.runtime_status()
        risk_ok = _snapshot_closed(risk_closed, strict=True)
        print(f"TEST_CLOSE case={case} step=risk code={'ok' if risk_ok else 'uncertain'}", flush=True)
        if not gateway_closed or not risk_ok:
            raise SyntheticCleanupUncertain("strategy_cleanup_uncertain")
    except BaseException as error:
        _RETAINED_OBJECTS.extend((api, risk, session, host, state, binding))
        _RETAINED_OBJECTS.append(error)
        print(f"TEST_CLOSE case={case} step=close code=uncertain "
              f"original={primary_error} close={_error_category(error)}", flush=True)
        raise SyntheticCleanupUncertain("strategy_cleanup_uncertain") from None


def _operator(endpoint, keys, precheck):
    config = parse_client_config({
        "client_config_schema_version": 1, "process_role": "application_client",
        "registration": {"application_ref": OPERATOR.actor_ref},
        "clients": {"risk": {"config_schema_version": 1, "settings": {"bindings": [{
            "mount": "application.risk_admin", "service_id": RISK_HOST.actor_ref,
            "instance_id": "risk-a", "scope_ref": "risk-scope", "account_ref": ACCOUNT,
            "transport_ref": "risk",
        }]}}},
        "communication": {"config_schema_version": 1, "profiles": {"risk": {
            "backend": "zmq", "config_schema_version": 1, "endpoints": {"rpc_connect": endpoint},
            "security_profile_ref": "risk-curve",
        }}},
    })
    client = ServiceClientRuntime(
        config, identity=OPERATOR, scope_resolver=lambda _: ACCOUNT_ONLY,
        peer_resolver=lambda _: RISK_HOST,
        transport_factory=ZmqTransportFactory({
            "risk-curve": ClientCurveKeys(keys["risk_server"][0], *keys["operator"]),
        }),
        requested_operations={"application.risk_admin": frozenset({"risk.admin.status", "risk.policy.read"})},
        require_unregister_ack=True,
    )
    try:
        client.start()
        assert client.healthy
    except BaseException as error:
        original = _error_category(error)
        print(f"TEST_STAGE stage=operator_start code={original}", flush=True)
        try:
            _operator_failed_start_cleanup(client, error, precheck)
        except BaseException as close_error:
            print(f"TEST_CLOSE step=operator code=uncertain original={original} "
                  f"close={_error_category(close_error)}", flush=True)
            raise SyntheticCleanupUncertain("operator_cleanup_uncertain") from None
        raise
    return client


def _journal_counts(path):
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as db:
        return tuple(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                     for table in ("direct_journal_commands", "direct_journal_releases"))


def _make_host(path, binding):
    path.mkdir()
    state = StrategyStateDir.initialize(path)
    GatewayPendingHost.upgrade_for_gateway(path, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(path, state.strategy_uuid, binding)
    consumer = gateway_execution_consumer_ref(
        principal_ref=STRATEGY.principal_ref, actor_ref=STRATEGY.actor_ref,
        execution_domain_ref=DOMAIN, account_scope=ACCOUNT, strategy_scope=STRATEGY.actor_ref,
    )
    GatewayPendingHost.upgrade_for_execution(path, state.strategy_uuid, binding, consumer_ref=consumer)
    return state, GatewayPendingHost.upgrade_for_order_state(path, state.strategy_uuid, binding)


def _session(endpoint, keys, binding, host):
    route = GatewayClientRoute("broker.direct_write", GATEWAY.actor_ref, "gateway-a", "scope-a", SCOPE, STRATEGY)
    return GatewayStrategyClientSession(
        _client_config(endpoint), binding=binding, route=route, peer=GATEWAY,
        security_profiles={"security": ClientCurveKeys(keys["gateway_server"][0], *keys["strategy"])},
        host=host, requested_operations=frozenset({
            "direct.reserve", "direct.dispatch", "direct.command_status",
            "direct.delegated_command_status", "direct.events.read_after", "direct.events.ack",
        }),
    )


def _synthetic_case(tmp_path, case, endpoint, risk_endpoint, keys, journal_id, monkeypatch, precheck):
    binding, state, host, session, risk, api = _construct_case_resources(
        lambda: GatewayCommandBinding(journal_id, ACCOUNT, STRATEGY.actor_ref, STRATEGY.principal_ref),
        lambda value: _make_host(tmp_path / ("strategy-" + case), value),
        lambda value, pending: _session(endpoint, keys, value, pending),
        lambda: _risk_client(risk_endpoint, keys),
        lambda value, risk_client: GatewayBtApi(value, exchange_name=ROUTE, owns_session=True,
                                               risk_client=risk_client),
    )
    stage = "start"
    primary_error = "none"
    try:
        started = api.start(timeout_seconds=15)
        assert started.healthy is True and risk.runtime_status().healthy is True
        status = risk.service_status(timeout_seconds=10)
        assert status.outcome == "ANSWERED" and status.status.available is False
        stage = "setup"
        risk_operations = []
        original_call = risk._runtime.call

        def monitored_call(mount, operation, arguments, **kwargs):
            risk_operations.append(operation)
            return original_call(mount, operation, arguments, **kwargs)

        monkeypatch.setattr(risk._runtime, "call", monitored_call)
        data, broker, strategy = framework()
        broker.store = SimpleNamespace(
            _gateway_mode=True, gateway_api=api, is_connected=True,
            gateway_strategy_config=SimpleNamespace(risk_selection=object()),
            contract_metadata={"rb": {"instrument_key": INSTRUMENT.to_dict(), "exchange_name": ROUTE,
                                      "quantity_unit": "lots", "time_in_force": "GFD"}},
        )
        qualification_calls = []

        def synthetic_qualification(data_arg, instrument_arg):
            qualification_calls.append((data_arg, instrument_arg))
            return {"synthetic": True}

        monkeypatch.setattr(broker, "_gateway_require_trade_qualification", synthetic_qualification)
        if case == "close":
            # Explicit synthetic long position and capacity. This is not an
            # authenticated Gateway or provider position observation.
            broker.positions["rb"].update(1, 10)
            observation = GatewayStrategyPositionObservation(
                INSTRUMENT, "lots", "20300101", Decimal(0), Decimal(1), Decimal(0), Decimal(0),
                False, "synthetic-generation", "UNKNOWN", Decimal(1), Decimal(0),
                time.monotonic_ns(), binding, "synthetic-registration", "synthetic-epoch",
            )
            monkeypatch.setattr(api, "get_strategy_close_capacity", lambda *a, **kw:
                                GatewayStrategyPositionResult("OBSERVED", observation))
            monkeypatch.setattr(api, "strategy_position_is_current", lambda *a, **kw: True)
            order = bt.SellOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
        else:
            order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
        order.addinfo(offset=case, quantity_unit="lots", time_in_force="GFD")
        stage = "bind"
        broker.bind_gateway_execution_stream(
            strategy, api=api, host=host, data_by_ref={"rb": data}, orders_by_key={},
            instrument_by_ref={"rb": INSTRUMENT}, time_policy=GatewayExecutionTimePolicy(ROUTE, "UTC"),
            sequence=state.sequence,
        )
        stage = "submit"
        result = broker.submit(order)
        assert result is order and order.status == order.Submitted
        assert broker.gateway_execution_stream_status() == "SUBMIT_UNKNOWN"
        key = order.info.gateway_request_key
        assert host.load_intent(key) is not None and host.load_record(key) is None
        assert host.load_delegated_command(key) is None
        assert qualification_calls == [(data, INSTRUMENT)]
        assert not {"risk.order.reserve", "risk.order.dispatch", "risk.order.release"} & set(risk_operations)
        return key
    except BaseException as error:
        primary_error = _error_category(error)
        print(f"TEST_STAGE case={case} stage={stage} code={primary_error}", flush=True)
        raise
    finally:
        _finish_case(api, risk, session, host, state, binding, precheck, primary_error, case)


def _run_synthetic_test(tmp_path, monkeypatch):
    keys = SyntheticKeys({name: zmq.curve_keypair() for name in (
        "gateway_server", "strategy", "risk_delegate", "risk_control", "risk_server", "operator")})
    gateway_root, risk_root = tmp_path / "gateway", tmp_path / "risk"
    gateway_root.mkdir()
    risk_root.mkdir()
    gateway_endpoint, risk_endpoint = _endpoint(), _endpoint()
    events, metadata, operations = (tmp_path / name for name in ("events.jsonl", "metadata.json", "operations.jsonl"))
    config = tmp_path / "synthetic.json"
    with _private_file(config, "w") as out:
        json.dump({
            "gateway_root": str(gateway_root), "risk_root": str(risk_root),
            "gateway_endpoint": gateway_endpoint, "risk_endpoint": risk_endpoint,
            "events": str(events), "metadata": str(metadata), "operations": str(operations),
            "keys": {name: [part.decode("ascii") for part in pair] for name, pair in keys.items()},
        }, out)
    with _private_file(operations, "w"):
        pass
    gateway_log, risk_log = (_private_file(tmp_path / "gateway.log", "wb"),
                             _private_file(tmp_path / "risk.log", "wb"))
    gateway = subprocess.Popen([sys.executable, str(GATEWAY_HELPER), str(config)], cwd=SDK_ROOT,
                               stdin=subprocess.PIPE, stdout=gateway_log, stderr=subprocess.STDOUT)
    risk = operator = None
    risk_start_attempted = False
    gateway_ready_verified = risk_ready_verified = False
    cleanup_uncertain = False
    try:
        ready = _wait_for(lambda: next((item for item in _events(events)
                                        if item["event"] in {"ready", "error"}), None))
        assert ready == {"event": "ready", "pid": gateway.pid}
        gateway_ready_verified = True
        info = json.loads(metadata.read_text(encoding="utf-8"))
        risk_ready = risk_root / "ready.json"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        risk_start_attempted = True
        risk = subprocess.Popen([sys.executable, "-m", "bt_api_py.risk_service_host", "run",
                                 "--config", info["risk_config"], "--ready-file", str(risk_ready)],
                                cwd=SDK_ROOT, env=env, stdout=risk_log, stderr=subprocess.STDOUT)

        def ready_risk():
            if risk.poll() is not None:
                raise AssertionError("synthetic_risk_exited_before_ready")
            return risk_ready.exists()

        _wait_for(ready_risk, seconds=60)
        assert json.loads(risk_ready.read_text(encoding="utf-8"))["pid"] == risk.pid
        risk_ready_verified = True
        def preclose():
            return _pre_stop_check(gateway, risk, events, risk_stopped=False)

        operator = _operator(risk_endpoint, keys, preclose)
        policy = operator.call("application.risk_admin", "risk.policy.read", {}, account_ref=ACCOUNT,
                               scope_ref="risk-scope")
        assert policy["document"]["self_trade"]["enabled"] is True
        status = operator.call("application.risk_admin", "risk.admin.status", {}, account_ref=ACCOUNT,
                               scope_ref="risk-scope")
        assert status["summary"]["available"] is False
        before = _journal_counts(gateway_root / "journal.sqlite")
        assert gateway.stdin is not None
        gateway.stdin.write(b"observe\n")
        gateway.stdin.flush()
        _wait_for(lambda: {"event": "observing", "pid": gateway.pid} in _events(events))
        keys_seen = [_synthetic_case(tmp_path, case, gateway_endpoint, risk_endpoint, keys,
                                     info["journal_id"], monkeypatch, preclose) for case in ("open", "close")]
        assert len(set(keys_seen)) == 2
        observed = _events(operations)
        assert all("overflow" not in item for item in observed)
        prohibited = {"direct.reserve", "direct.dispatch", "direct.release",
                      "direct.delegated_reserve", "direct.delegated_dispatch"}
        assert not prohibited & {item["operation"] for item in observed}
        assert _journal_counts(gateway_root / "journal.sqlite") == before
    except BaseException as error:
        if isinstance(error, SyntheticCleanupUncertain):
            cleanup_uncertain = True
        print(f"TEST_RESULT stage=execution code={_error_category(error)}", flush=True)
        raise
    finally:
        active_error = sys.exc_info()[1]
        primary_error = "none" if active_error is None else _error_category(active_error)
        close_error = "none"
        risk_stop_sent = False
        gateway_stop_sent = False
        if not cleanup_uncertain and operator is not None:
            try:
                _close_operator(operator, lambda: _pre_stop_check(gateway, risk, events, risk_stopped=False))
            except BaseException as error:
                cleanup_uncertain = True
                close_error = _error_category(error)
            print(f"TEST_CLOSE step=operator code={'uncertain' if cleanup_uncertain else 'ok'}", flush=True)
        if (risk_start_attempted and risk is None) or (risk is not None and not risk_ready_verified) or not gateway_ready_verified:
            cleanup_uncertain = True
        if not cleanup_uncertain and risk is not None:
            try:
                if not _pre_stop_check(gateway, risk, events, risk_stopped=False):
                    raise SyntheticCleanupUncertain("pre_risk_stop_uncertain")
                risk.send_signal(signal.SIGTERM)
                risk_stop_sent = True
                risk.wait(timeout=30)
            except BaseException as error:
                cleanup_uncertain = True
                close_error = _error_category(error)
        if risk is not None and (not risk_stop_sent or risk.returncode != 0):
            cleanup_uncertain = True
        if risk is not None:
            print(f"TEST_CLOSE step=risk_process code={'uncertain' if cleanup_uncertain else 'ok'}", flush=True)
        if not cleanup_uncertain:
            try:
                if not _pre_stop_check(gateway, risk, events, risk_stopped=True):
                    raise SyntheticCleanupUncertain("pre_gateway_stop_uncertain")
                if gateway.stdin is None:
                    raise SyntheticCleanupUncertain("gateway_control_unavailable")
                gateway.stdin.write(b"stop\n")
                gateway.stdin.flush()
                gateway_stop_sent = True
                gateway.wait(timeout=30)
            except BaseException as error:
                cleanup_uncertain = True
                close_error = _error_category(error)
        if not cleanup_uncertain:
            try:
                cleanup_uncertain = (not gateway_stop_sent or gateway.returncode != 0 or
                                     not _gateway_events_valid(_events(events), gateway.pid, terminal=True))
            except BaseException as error:
                cleanup_uncertain = True
                close_error = _error_category(error)
        print(f"TEST_CLOSE step=gateway_process code={'uncertain' if cleanup_uncertain else 'ok'}", flush=True)
        if not cleanup_uncertain:
            print(f"TEST_CLEANUP complete risk_pid={None if risk is None else risk.pid} "
                  f"risk_exit={None if risk is None else risk.returncode} "
                  f"gateway_pid={gateway.pid} gateway_exit={gateway.returncode}", flush=True)
        else:
            print(f"TEST_CLEANUP retained risk_pid={None if risk is None else risk.pid} "
                  f"gateway_pid={gateway.pid} original={primary_error} cleanup={close_error}", flush=True)
        if cleanup_uncertain:
            _RETAINED_OBJECTS.extend((gateway, risk, operator))
        gateway_log.close()
        risk_log.close()
        if cleanup_uncertain:
            raise SyntheticCleanupUncertain("synthetic_host_cleanup_uncertain")
        shutil.rmtree(tmp_path)


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only quarantine harness (requires 0o600 mode checks, umask and SIGTERM)",
)
def test_bt_local_gate_with_real_gateway_and_risk_sessions(monkeypatch):
    tmp_path = Path(tempfile.mkdtemp(prefix="iter64-bt-quarantine-"))
    try:
        _run_synthetic_test(tmp_path, monkeypatch)
    except BaseException as error:
        code = _error_category(error)
        if tmp_path.exists():
            print(f"TEST_RETAINED path={tmp_path} code={code}", flush=True)
        if isinstance(error, SyntheticCleanupUncertain):
            print(f"TEST_RETAINED owner_pid={os.getpid()} code=cleanup_uncertain", flush=True)
            _retain_forever()
        pytest.fail(f"synthetic_test_{code}", pytrace=False)


@pytest.mark.parametrize(
    ("messages", "write_failure", "closed_seen", "failed", "fixture_error"),
    [
        ([("ready", 7, "synthetic"), ("closed", 7)], "metadata", False, True, False),
        ([("ready", 7, "synthetic"), ("closed", 7)], "event", False, True, False),
        ([], None, False, True, False),
        ([("cleanup_uncertain", "fixed_code")], None, False, False, True),
        ([("closed", 8)], None, False, True, False),
        ([("closed", 7)], None, True, False, False),
    ],
)
def test_synthetic_reporter_fails_closed(messages, write_failure, closed_seen, failed, fixture_error):
    class FakeMessages:
        def __init__(self, items):
            self.items = iter(items)

        def get(self):
            return next(self.items)

    def write_metadata(_journal):
        if write_failure == "metadata":
            raise OSError

    def write_event(_kind):
        if write_failure == "event":
            raise OSError

    lifecycle = {"fixture_error": False}
    state = {"closed_seen": False, "failed": False}
    _report(FakeMessages(messages), write_metadata, write_event, lifecycle, state, 7)
    assert state == {"closed_seen": closed_seen, "failed": failed}
    assert lifecycle["fixture_error"] is fixture_error


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_fake_child_base_exception_retains(exception_type):
    observed = []

    def fail(_path):
        raise exception_type("never print this payload")

    _run_child(fail, "unused", lambda: observed.append("failure"), lambda: observed.append("retained"))
    assert observed == ["failure", "retained"]


@pytest.mark.parametrize("requested_secret", [True, False])
@pytest.mark.parametrize("mode", [0o600, 0o644])
def test_fake_key_writer_delegation(requested_secret, mode):
    calls = []
    fake_path = SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=mode))

    def fake_sdk_writer(path, key, *, secret):
        calls.append((path is fake_path, key == b"synthetic", secret))
        return "ok"

    if mode == 0o600:
        assert _write_protected_key(fake_sdk_writer, fake_path, b"synthetic", secret=requested_secret) == "ok"
    else:
        with pytest.raises(RuntimeError, match="synthetic_key_permissions"):
            _write_protected_key(fake_sdk_writer, fake_path, b"synthetic", secret=requested_secret)
    assert calls == [(True, True, True)]


def test_fake_key_writer_error_propagates():
    def fake_sdk_writer(_path, _key, *, secret):
        assert secret is True
        raise OSError("fixed failure")

    with pytest.raises(OSError, match="fixed failure"):
        _write_protected_key(fake_sdk_writer, None, b"synthetic", secret=False)


@pytest.mark.parametrize("scenario", ["ok", "prior_error", "prior_uncertain", "error_after_probe"])
def test_fake_operator_preclose_check(monkeypatch, scenario):
    records = [{"event": "ready", "pid": 7}]
    if scenario == "prior_error":
        records.append({"event": "error", "pid": 7})
    elif scenario == "prior_uncertain":
        records.append({"event": "cleanup_uncertain", "pid": 7})

    class FakeInput:
        closed = False

        def write(self, data):
            assert data == b"probe\n"
            records.append({"event": "reporter_probe", "pid": 7})
            if scenario == "error_after_probe":
                records.append({"event": "error", "pid": 7})

        def flush(self):
            pass

    class FakeGateway:
        pid = 7
        stdin = FakeInput()

        def poll(self):
            return None

    class FakeRisk:
        def poll(self):
            return None

    class FakeOperator:
        state = "open"
        cleanup_failures = unregister_uncertainties = unknown_registration_count = 0
        close_calls = 0

        def close(self):
            self.close_calls += 1
            self.state = "closed"

    module = sys.modules[__name__]
    retained = []
    monkeypatch.setattr(module, "_events", lambda _path: list(records))
    monkeypatch.setattr(module, "_RETAINED_OBJECTS", retained)
    client = FakeOperator()

    def precheck():
        return _pre_stop_check(FakeGateway(), FakeRisk(), "unused", risk_stopped=False)

    if scenario == "ok":
        _close_operator(client, precheck)
        assert client.close_calls == 1 and not retained
    else:
        with pytest.raises(SyntheticCleanupUncertain):
            _close_operator(client, precheck)
        assert client.close_calls == 0 and retained == [client]


@pytest.mark.parametrize("scenario", [
    "safe_failed", "safe_registered", "unknown", "unregister", "cleanup", "close_failed",
    "starting", "reading_raises", "invalid_count", "original_uncertain", "probe_uncertain",
])
def test_fake_operator_failed_start_retains_before_close(monkeypatch, scenario):
    retained, checks = [], []
    monkeypatch.setattr(sys.modules[__name__], "_RETAINED_OBJECTS", retained)

    class FakeClient:
        state = "registered" if scenario == "safe_registered" else (
            "close_failed" if scenario == "close_failed" else "starting" if scenario == "starting" else "failed"
        )
        unregister_uncertainties = 1 if scenario == "unregister" else 0
        cleanup_failures = 1 if scenario == "cleanup" else 0
        close_calls = 0

        @property
        def unknown_registration_count(self):
            if scenario == "reading_raises":
                raise RuntimeError("private synthetic payload")
            if scenario == "unknown":
                return 1
            return False if scenario == "invalid_count" else 0

        def close(self):
            self.close_calls += 1
            self.state = "closed"

    client = FakeClient()
    original = (SyntheticCleanupUncertain("fixed") if scenario == "original_uncertain"
                else ValueError("private synthetic payload"))

    def precheck():
        checks.append("probe")
        return scenario != "probe_uncertain"

    if scenario in {"safe_failed", "safe_registered"}:
        _operator_failed_start_cleanup(client, original, precheck)
        assert client.close_calls == 1 and checks == ["probe"] and not retained
    else:
        with pytest.raises(SyntheticCleanupUncertain):
            _operator_failed_start_cleanup(client, original, precheck)
        assert client.close_calls == 0
        assert any(item is client for item in retained)
        assert any(item is original for item in retained)
        assert checks == (["probe"] if scenario == "probe_uncertain" else [])


@pytest.mark.parametrize("safe", [False, True])
def test_fake_strategy_preclose_check(safe):
    calls = []
    api = SimpleNamespace(close=lambda **kwargs: calls.append(kwargs) or "closed")
    if safe:
        assert _close_strategy(api, lambda: safe) == "closed"
        assert calls == [{"timeout_seconds": 15}]
    else:
        with pytest.raises(SyntheticCleanupUncertain):
            _close_strategy(api, lambda: safe)
        assert not calls


@pytest.mark.parametrize("failure", ["binding", "host", "session", "risk", "api", "none"])
def test_fake_case_construction_failure_retains(monkeypatch, capsys, failure):
    module = sys.modules[__name__]
    retained, created, calls = [], [], []
    monkeypatch.setattr(module, "_RETAINED_OBJECTS", retained)

    class FakeResource:
        def close(self):
            calls.append("close")

        def stop(self):
            calls.append("stop")

    def construct(stage, *, pair=False):
        value = (FakeResource(), FakeResource()) if pair else FakeResource()
        created.append(value)
        if failure == stage:
            raise AssertionError("private synthetic failure payload")
        return value

    factories = (
        lambda: construct("binding"),
        lambda _binding: construct("host", pair=True),
        lambda _binding, _host: construct("session"),
        lambda: construct("risk"),
        lambda _session, _risk: construct("api"),
    )
    if failure == "none":
        result = _construct_case_resources(*factories)
        assert len(result) == 6 and not retained
    else:
        with pytest.raises(SyntheticCleanupUncertain, match="case_construction_uncertain"):
            _construct_case_resources(*factories)
        assert all(any(item is value for item in retained) for value in created[:-1])
        assert any(isinstance(item, AssertionError) and item.__traceback__ is not None for item in retained)
        output = capsys.readouterr().out
        assert f"stage=construct_{failure} code=assertion" in output
        assert "private synthetic failure payload" not in output
    assert not calls


def test_fake_known_uncertain_skips_case_close(monkeypatch):
    retained, calls = [], []
    monkeypatch.setattr(sys.modules[__name__], "_RETAINED_OBJECTS", retained)

    class FakeResource:
        def close(self, **_kwargs):
            calls.append("close")

        def stop(self):
            calls.append("stop")

        def runtime_status(self):
            calls.append("status")

    resources = tuple(FakeResource() for _ in range(6))

    def precheck():
        calls.append("precheck")
        return True

    with pytest.raises(SyntheticCleanupUncertain):
        _finish_case(*resources, precheck, "cleanup_uncertain", "open")
    assert not calls
    assert all(any(item is value for item in retained) for value in resources)


@pytest.mark.parametrize("mutation", [
    "none", "error_before", "error_after", "uncertain_before", "uncertain_after",
    "duplicate_closed", "missing_pid", "wrong_pid", "probe_then_error", "owner_uncertain",
])
def test_fake_terminal_gateway_events(mutation):
    events = [{"event": "ready", "pid": 7},
              {"event": "cleanup_step", "step": "host", "code": "ok", "pid": 7},
              {"event": "cleanup_step", "step": "owner", "code": "ok", "pid": 7},
              {"event": "closed", "pid": 7}]
    if mutation in {"error_before", "uncertain_before"}:
        event = "error" if mutation == "error_before" else "cleanup_uncertain"
        events.insert(1, {"event": event, "pid": 7})
    elif mutation in {"error_after", "uncertain_after"}:
        event = "error" if mutation == "error_after" else "cleanup_uncertain"
        events.append({"event": event, "pid": 7})
    elif mutation == "duplicate_closed":
        events.append({"event": "closed", "pid": 7})
    elif mutation == "missing_pid":
        del events[-1]["pid"]
    elif mutation == "wrong_pid":
        events[-1]["pid"] = 8
    elif mutation == "probe_then_error":
        events[1:1] = [{"event": "reporter_probe", "pid": 7}, {"event": "error", "pid": 7}]
    elif mutation == "owner_uncertain":
        events[2]["code"] = "uncertain"
    assert _gateway_events_valid(events, 7, terminal=True) is (mutation == "none")


@pytest.mark.parametrize("scenario", ["ok", "prior_error", "prior_uncertain", "wrong_pid", "error_after_probe"])
def test_fake_pre_stop_gateway_events(monkeypatch, scenario):
    records = [{"event": "ready", "pid": 7}]
    if scenario == "prior_error":
        records.append({"event": "error", "pid": 7})
    elif scenario == "prior_uncertain":
        records.append({"event": "cleanup_uncertain", "pid": 7})
    elif scenario == "wrong_pid":
        records.append({"event": "reporter_probe", "pid": 8})

    class FakeInput:
        closed = False

        def write(self, data):
            assert data == b"probe\n"
            records.append({"event": "reporter_probe", "pid": 7})
            if scenario == "error_after_probe":
                records.append({"event": "error", "pid": 7})

        def flush(self):
            pass

    class FakeGateway:
        pid = 7
        stdin = FakeInput()

        def poll(self):
            return None

    class FakeRisk:
        def poll(self):
            return None

    monkeypatch.setattr(sys.modules[__name__], "_events", lambda _path: list(records))
    assert _pre_stop_check(FakeGateway(), FakeRisk(), "unused", risk_stopped=False) is (scenario == "ok")
