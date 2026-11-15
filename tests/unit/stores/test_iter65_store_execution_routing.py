"""Iteration 65: the Store composes the SDK Execution routing selection.

UNIT/FAKE with a temporary strategy directory and a fake Execution parent
port. Nothing here starts a service, opens a socket, contacts a provider or an
account, or constructs the SDK client. A composed router file and a local
PREPARED row are local facts only; they prove no Gateway acceptance, no Risk
approval and no venue state.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="iteration 65 routing needs the bt_api_py SDK")

from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_py.gateway_strategy_config import parse_gateway_strategy_config
from bt_api_py.service_config import parse_client_config

from backtrader.stores._btapi_errors import BtApiStoreError
from backtrader.stores.btapistore import (
    EXECUTION_ROUTING_DB_FILENAME,
    EXECUTION_ROUTING_TTL_SECONDS,
    BtApiStore,
)

ROUTE = "CTP___FUTURE"
ACCOUNT = "account"
STRATEGY = "strategy-ref"
DOMAIN = "paper"
INSTRUMENT = MarketInstrumentKey("ctp", "SHFE", "demo", "future", "rb2701", "rb2701")


class FakeExecutionParentPort:
    """The injected ``service.execution_parent`` port; every reply is a fake."""

    def __init__(self, *, reply=None, cancel_reply=None, with_cancel: bool = True):
        self.submit_reply = (
            {"status": "ACCEPTED", "parent_ref": "parent-1"} if reply is None else reply
        )
        self.cancel_reply = {"status": "ACCEPTED"} if cancel_reply is None else cancel_reply
        self.submit_calls = []
        self.cancel_calls = []
        if with_cancel:
            self.cancel = self._cancel

    def submit(self, request):
        self.submit_calls.append(request)
        if isinstance(self.submit_reply, BaseException):
            raise self.submit_reply
        return self.submit_reply

    def _cancel(self, payload):
        self.cancel_calls.append(payload)
        if isinstance(self.cancel_reply, BaseException):
            raise self.cancel_reply
        return self.cancel_reply


def routing_option(**overrides):
    value = {
        "schema_version": 1,
        "component": "exec-instance",
        "account_ref": ACCOUNT,
        "strategy_ref": STRATEGY,
        "execution_domain_ref": DOMAIN,
        "grant_revision": "grant-v1",
        "delegation": {"delegation_id": "delegation-1", "principal_ref": "principal-a"},
        "instruments": [INSTRUMENT.to_dict()],
        "rules": [
            {
                "id": "rule-1",
                "match": {
                    "instrument": INSTRUMENT.to_dict(),
                    "side": "buy",
                    "offset": "open",
                    "order_types": ["limit"],
                    "minimum_quantity": "1",
                    "quantity_unit": "lots",
                },
                "scheme": {"name": "pass-v1", "version": 1},
                "algorithm": {"class": "PASS", "version": 1, "params": {}},
                "deadline": {"kind": "absolute", "at": "2099-12-31T08:00:00+08:00"},
                "time_in_force": "DAY",
                "trading_day": "20261109",
            }
        ],
    }
    value.update(overrides)
    return value


def client_tree(
    *, routing=True, gateway_account=ACCOUNT, execution_instance="exec-instance", strategy=STRATEGY
):
    """One parsed strategy-client configuration; the Execution block selects routing."""
    clients = {
        "gateway": {
            "config_schema_version": 1,
            "settings": {
                "bindings": [
                    {
                        "mount": "broker.direct_write",
                        "service_id": "gateway",
                        "instance_id": "gw-instance",
                        "scope_ref": "gw-scope",
                        "transport_ref": "transport",
                        "account_ref": gateway_account,
                    }
                ]
            },
        }
    }
    if routing:
        settings = {
            "bindings": [
                {
                    "mount": "broker.execution_parent",
                    "service_id": "execution",
                    "instance_id": execution_instance,
                    "scope_ref": "exec-scope",
                    "transport_ref": "transport",
                    "account_ref": ACCOUNT,
                }
            ],
            "options": {"execution_routing": routing_option(strategy_ref=strategy)},
        }
        clients["execution"] = {"config_schema_version": 1, "settings": settings}
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": strategy},
        "clients": clients,
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "transport": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": "tcp://127.0.0.1:12345"},
                    "security_profile_ref": "security",
                }
            },
        },
    }


def gateway_tree(*, account=ACCOUNT, strategy=STRATEGY, gateway_client=None):
    """One parsed Gateway strategy configuration: exact binding and route."""
    return {
        "schema_version": 1,
        "exchange_name": ROUTE,
        "client_config": client_tree(routing=False) if gateway_client is None else gateway_client,
        "binding": {
            "journal_id": "journal",
            "account_scope": account,
            "strategy_scope": strategy,
            "principal": "principal",
        },
        "route": {
            "mount": "broker.direct_write",
            "service_id": "gateway",
            "instance_id": "gw-instance",
            "scope_ref": "gw-scope",
            "scope": {
                "execution_domain_ref": DOMAIN,
                "account_ref": account,
                "account_refs": [],
                "strategy_ref": strategy,
                "run_id": "run-1",
                "manual_book_ref": None,
                "portfolio_ref": None,
                "group_id": None,
                "leg_id": None,
            },
            "identity": {
                "role": "strategy_client",
                "principal_ref": "principal",
                "actor_ref": strategy,
                "delegate_ref": None,
            },
        },
        "peer": {
            "role": "service",
            "principal_ref": "service-principal",
            "actor_ref": "gateway",
            "delegate_ref": None,
        },
        "requested_operations": [
            "direct.reserve",
            "direct.release",
            "direct.dispatch",
            "direct.command_status",
        ],
        "execution_time_policy": {
            "route": ROUTE,
            "timezone": "Asia/Shanghai",
            "format": "date_hms_seconds_v1",
            "schema_version": 1,
        },
        "instruments_by_ref": {"rb2701": INSTRUMENT.to_dict()},
        "risk": "none",
    }


def parsed_client(**overrides):
    return parse_client_config(client_tree(**overrides))


def parsed_gateway(**overrides):
    return parse_gateway_strategy_config(gateway_tree(**overrides))


def make_store(*, client="default", gateway="default", port="default"):
    values = {}
    values["service_client_config"] = parsed_client() if client == "default" else client
    values["gateway_client_config"] = parsed_gateway() if gateway == "default" else gateway
    values["execution_parent_port"] = FakeExecutionParentPort() if port == "default" else port
    return BtApiStore(
        provider="ctp",
        exchange_kwargs={ROUTE: {"synthetic": True}},
        write_admission={ROUTE: True},
        **values,
    )


def refuse(make):
    with pytest.raises(BtApiStoreError) as info:
        make()
    return getattr(info.value, "code", None) or str(info.value)


def broker_stub(strategy_dir):
    return SimpleNamespace(p=SimpleNamespace(strategy_dir=str(strategy_dir)))


# ---------------------------------------------------------------------------
# composition matrix
# ---------------------------------------------------------------------------


def test_unselected_store_composes_nothing_and_keeps_the_existing_path(tmp_path):
    store = BtApiStore(
        provider="ctp",
        exchange_kwargs={ROUTE: {"synthetic": True}},
        write_admission={ROUTE: True},
    )

    assert store.execution_routing_selection is None
    assert store.execution_routing_db_path is None
    assert store._compose_execution_routing(broker_stub(tmp_path)) is None
    assert store.execution_routing_selection is None
    assert not (tmp_path / "state").exists()  # nothing was created either


def test_selection_without_a_port_is_refused_before_anything_exists():
    code = refuse(lambda: make_store(port=None))

    assert code == "EXECUTION_ROUTING_CONFIGURATION_INCOMPLETE"


def test_port_without_a_selection_is_refused():
    code = refuse(lambda: make_store(client=None))

    assert code == "EXECUTION_ROUTING_CONFIGURATION_INCOMPLETE"


def test_configuration_without_routing_is_refused():
    code = refuse(lambda: make_store(client=parsed_client(routing=False)))

    assert code == "EXECUTION_ROUTING_NOT_SELECTED"


def test_wrong_configuration_types_are_refused():
    assert refuse(lambda: make_store(client=client_tree())) == (
        "EXECUTION_ROUTING_CONFIGURATION_INVALID"
    )
    assert refuse(lambda: make_store(gateway=gateway_tree())) == (
        "EXECUTION_ROUTING_CONFIGURATION_INVALID"
    )


def test_port_without_submit_is_refused():
    code = refuse(lambda: make_store(port=SimpleNamespace()))

    assert code == "EXECUTION_ROUTING_PORT_INVALID"


def test_non_callable_cancel_is_refused():
    port = FakeExecutionParentPort()
    port.cancel = "not-callable"

    assert refuse(lambda: make_store(port=port)) == "EXECUTION_ROUTING_PORT_INVALID"


def test_borrowed_api_is_refused():
    def factory(**options):
        raise AssertionError("a routing Store must refuse before construction")

    code = refuse(
        lambda: BtApiStore(
            provider="ctp",
            api_cls=factory,
            exchange_kwargs={ROUTE: {"synthetic": True}},
            write_admission={ROUTE: True},
            service_client_config=parsed_client(),
            gateway_client_config=parsed_gateway(),
            execution_parent_port=FakeExecutionParentPort(),
        )
    )

    assert code == "EXECUTION_ROUTING_REQUIRES_OWNED_API"


def test_gateway_and_service_configuration_must_name_one_identity():
    code = refuse(
        lambda: make_store(
            client=parse_client_config(client_tree(strategy="other-strategy")),
        )
    )

    assert code == "EXECUTION_ROUTING_CONFIGURATION_MISMATCH"


def test_the_sdk_parser_refuses_a_routing_option_without_its_parent_writer():
    # Ambiguity is refused where the configuration is parsed, so the Store
    # never receives a selection whose parent writer is unproven.
    from bt_api_py.service_config import ServiceConfigError

    tree = client_tree()
    tree["clients"]["execution"]["settings"]["bindings"][0]["instance_id"] = "other-instance"
    with pytest.raises(ServiceConfigError) as info:
        parse_client_config(tree)

    assert info.value.code == "EXECUTION_ROUTING_COMPONENT_MISMATCH"


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------


def test_composed_selection_matches_the_gateway_route_and_the_state_dir(tmp_path):
    from bt_api_py.bt_api import ExecutionRoutingSelection
    from bt_api_py.execution_routing import ExecutionOrderRouter

    store = make_store()

    selection = store._compose_execution_routing(broker_stub(tmp_path))

    assert type(selection) is ExecutionRoutingSelection
    assert type(selection.router) is ExecutionOrderRouter
    assert selection.binding == parsed_gateway().binding
    assert selection.route == parsed_gateway().route
    assert selection.ttl_seconds == EXECUTION_ROUTING_TTL_SECONDS
    assert 0 < selection.ttl_seconds <= 30
    assert store.execution_routing_selection is selection
    db_path = Path(store.execution_routing_db_path)
    assert db_path == tmp_path / "state" / EXECUTION_ROUTING_DB_FILENAME
    assert db_path.is_file()
    names = {
        row[0]
        for row in sqlite3.connect(db_path).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"execution_parent_requests_v1"} <= names
    # Composing again is idempotent: the same router and the same file.
    assert store._compose_execution_routing(broker_stub(tmp_path)) is selection
    assert store.execution_routing_db_path == str(db_path)


def test_the_composed_selection_is_accepted_by_the_real_sdk_facade(tmp_path, monkeypatch):
    """The Store's selection passes the SDK's own construction-time validation.

    The facade is built over a synthetic feed; nothing connects, subscribes or
    sends. This proves the composed router, binding, route and lifetime are the
    exact objects ``BtApi`` accepts, not merely similarly shaped ones.
    """
    import bt_api_py.bt_api as facade_module
    from bt_api_py.bt_api import BtApi, ExecutionRoutingSelection

    class FakeFeed:
        def disconnect(self):
            pass

    monkeypatch.setattr(facade_module, "_ensure_plugins_loaded", lambda: None)
    monkeypatch.setattr(
        facade_module.ExchangeRegistry,
        "create_feed",
        lambda name, queue, **settings: FakeFeed(),
    )
    store = make_store()
    selection = store._compose_execution_routing(broker_stub(tmp_path))

    api = BtApi(
        {ROUTE: {"synthetic": True}},
        debug=False,
        write_admission={ROUTE: True},
        execution_order_routing=selection,
    )
    try:
        assert type(selection) is ExecutionRoutingSelection
        assert api._execution_order_routing is selection
    finally:
        api.close()


def test_start_composes_before_the_sdk_client_is_created(tmp_path, monkeypatch):
    from backtrader.stores import btapistore

    observed = {}

    def fake_start_store(store, data=None, broker=None, **kwargs):
        observed["selection"] = store.execution_routing_selection
        return {"shutdown_state": "PASS"}

    monkeypatch.setattr(btapistore, "_start_store", fake_start_store)
    store = make_store()

    store.start(broker=broker_stub(tmp_path))

    assert observed["selection"] is store.execution_routing_selection
    assert observed["selection"] is not None


def test_start_without_a_strategy_directory_is_refused(tmp_path, monkeypatch):
    from backtrader.stores import btapistore

    monkeypatch.setattr(btapistore, "_start_store", lambda *a, **k: {"shutdown_state": "PASS"})
    store = make_store()

    with pytest.raises(BtApiStoreError) as info:
        store.start()

    assert getattr(info.value, "code", None) == "EXECUTION_ROUTING_STATE_DIR_REQUIRED"


def test_an_sdk_client_cannot_be_assembled_before_composition(tmp_path):
    store = make_store()

    with pytest.raises(BtApiStoreError) as info:
        store._ensure_sdk_direct_api_assembly()

    assert getattr(info.value, "code", None) == "EXECUTION_ROUTING_NOT_COMPOSED"
    assert store._sdk_direct_api_assembly is None


def test_a_missing_strategy_directory_is_refused(tmp_path):
    store = make_store()

    with pytest.raises(BtApiStoreError) as info:
        store._compose_execution_routing(broker_stub(tmp_path / "missing"))

    assert getattr(info.value, "code", None) == "EXECUTION_ROUTING_STATE_DIR_MISSING"


def test_composition_never_touches_the_injected_port(tmp_path):
    port = FakeExecutionParentPort()
    store = make_store(port=port)

    store._compose_execution_routing(broker_stub(tmp_path))

    assert port.submit_calls == []
    assert port.cancel_calls == []


def test_closing_the_store_closes_the_router_file(tmp_path, monkeypatch):
    from backtrader.stores import btapistore

    monkeypatch.setattr(btapistore, "_stop_store", lambda *a, **k: {"shutdown_state": "PASS"})
    store = make_store()
    selection = store._compose_execution_routing(broker_stub(tmp_path))
    connection = store._execution_routing_connection

    store.stop()

    assert store.execution_routing_selection is None
    assert store.execution_routing_db_path is None
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    # The file itself stays durable for the next run.
    assert (tmp_path / "state" / EXECUTION_ROUTING_DB_FILENAME).is_file()
    assert selection is not None


# ---------------------------------------------------------------------------
# import isolation
# ---------------------------------------------------------------------------


def test_unselected_store_never_imports_the_routing_or_execution_modules():
    repo = Path(__file__).resolve().parents[3]
    code = (
        "import sys\n"
        "from backtrader.stores.btapistore import BtApiStore\n"
        "store = BtApiStore(provider='ctp', exchange_kwargs={'CTP___FUTURE': {}},"
        " write_admission={'CTP___FUTURE': True})\n"
        "assert store.execution_routing_selection is None\n"
        "bad = [n for n in sorted(sys.modules) if n == 'bt_api_py.execution_routing'"
        " or n == 'bt_api_execution' or n.startswith('bt_api_execution.')]\n"
        "assert bad == [], bad\n"
    )
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
