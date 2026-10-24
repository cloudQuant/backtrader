"""RegisteredSim may project only callback-bound CTP OrderSysID evidence."""

from types import SimpleNamespace

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.order import BuyOrder, OrderBase
from backtrader.stores.btapistore import _create_ctp_wrapper_class
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper
from tests.test_utils.optional_sdk import optional_sdk


_INSTRUMENT = "rb2611"
_EXCHANGE = "SHFE"
_ORDER_REF = "7001"
_SYS_ID = "SYS7001"


def _callback_payload(**overrides):
    fields = {
        "OrderRef": _ORDER_REF,
        "OrderSysID": _SYS_ID,
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": _EXCHANGE,
        "FrontID": 4,
        "SessionID": 7,
        "OrderStatus": "3",
        "OrderSubmitStatus": "3",
        "StatusMsg": "",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "LimitPrice": 3600.0,
        "VolumeTotalOriginal": 2,
        "VolumeTraded": 0,
        "VolumeTotal": 2,
        "UpdateTime": "09:31:00",
        "InsertTime": "09:30:00",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _system(route_id="simnow-registered-v1", *, capture=True, response=None):
    optional_sdk("bt_api_ctp.ctp.client")
    ctp_wrapper = _create_ctp_wrapper_class()
    api_cls = type(
        "TestRegisteredSimIdentityCtpClient",
        (RegisteredSimWrapper, ctp_wrapper),
        {"__module__": __name__},
    )
    api = api_cls(registered_sim_allow_writes=False)
    api._connected = True
    api._front_id = 4
    api._session_id = 7

    store = RegisteredSimStore(api=api, autostart=False)
    store._connected = True
    store.registered_sim_route_id = route_id
    store.contract_metadata = {
        _INSTRUMENT: {"instrument_id": _INSTRUMENT, "exchange_id": _EXCHANGE}
    }
    broker = BtApiBroker(
        store=store,
        cash=100_000,
        validation_enabled=False,
        cash_check_enabled=False,
        contract_metadata=store.contract_metadata,
    )
    store._broker = broker

    data = SimpleNamespace(
        _name=_INSTRUMENT,
        _dataname=_INSTRUMENT,
        close=[3600.0],
        datetime=[0.0],
        p=SimpleNamespace(dataname=_INSTRUMENT),
    )
    order = BuyOrder(
        data=data,
        size=2,
        price=3600.0,
        exectype=OrderBase.Limit,
        simulated=True,
    )
    order.addinfo(
        front_id=4,
        session_id=7,
        exchange_id=_EXCHANGE,
        factor_session_front_id=4,
        factor_session_id=7,
    )
    order.accept(broker)
    broker.orders[order.ref] = order
    broker._remember_client_ref(
        order,
        _ORDER_REF,
        None,
    )
    if capture:
        broker._capture_registered_sim_ctp_order_identity(
            order,
            order_ref=_ORDER_REF,
            instrument_id=_INSTRUMENT,
            exchange_id=_EXCHANGE,
            front_id=4,
            session_id=7,
        )
        broker._verify_registered_sim_ctp_order_response(
            order,
            response
            or {
                "order_ref": _ORDER_REF,
                "front_id": 4,
                "session_id": 7,
                "exchange_id": _EXCHANGE,
            },
        )

    api._pending_orders[_ORDER_REF] = {
        "order_ref": _ORDER_REF,
        "data_name": _INSTRUMENT,
        "instrument": _INSTRUMENT,
        "exchange_id": _EXCHANGE,
        "side": "buy",
        "offset": "open",
        "price": 3600.0,
        "size": 2,
        "front_id": 4,
        "session_id": 7,
    }
    # Use the same callback binding the production CTP wrapper installs on its
    # TraderClient, while keeping only the native SDK leaf synthetic.
    api.trader_client = SimpleNamespace(
        _front_id=4,
        _session_id=7,
        on_order=api._handle_order,
    )
    return api, store, broker, order


def _deliver(api, broker, payload):
    api.trader_client.on_order(payload)
    broker._drain_store_updates()


def test_real_ctp_callback_projects_sys_id_without_inventing_generation():
    api, _store, broker, order = _system()

    _deliver(api, broker, _callback_payload())

    assert order.info.get("registered_sim_ctp_order_sys_id") == _SYS_ID
    assert order.info.get("registered_sim_ctp_order_sys_id_source") == "ctp_order_callback"
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is None
    assert order.info.get("order_sys_id") is None
    assert order.info.get("connection_generation") is None
    snapshot = broker.execution_order_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].order_sys_id == _SYS_ID
    assert snapshot[0].execution_unknown is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("OrderRef", "7002"),
        ("InstrumentID", "rb2612"),
        ("ExchangeID", "DCE"),
        ("FrontID", 5),
        ("SessionID", 8),
    ],
)
def test_callback_identity_mismatch_fails_closed(field, value):
    api, _store, broker, order = _system()
    if field == "OrderRef":
        # The external ID may correlate a row, but it cannot override the
        # callback's conflicting raw OrderRef.
        order.addinfo(external_order_id=_SYS_ID)
        broker._orders_by_external_id[_SYS_ID] = order

    _deliver(api, broker, _callback_payload(**{field: value}))

    assert order.info.get("registered_sim_ctp_order_sys_id") is None
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is True
    snapshot = broker.execution_order_snapshot()[0]
    assert snapshot.order_sys_id is None
    assert snapshot.execution_unknown is True


def test_missing_raw_sys_id_and_external_id_only_do_not_qualify():
    api, _store, broker, order = _system()
    order.addinfo(external_order_id="external-only")
    broker._orders_by_external_id["external-only"] = order

    _deliver(api, broker, _callback_payload(OrderSysID=""))

    assert order.info.get("registered_sim_ctp_order_sys_id") is None
    snapshot = broker.execution_order_snapshot()[0]
    assert snapshot.order_sys_id is None
    assert snapshot.execution_unknown is False


def test_registered_query_sys_id_with_generation_does_not_project_without_callback():
    _api, _store, broker, order = _system()

    broker._apply_order_update(
        {
            "kind": "order",
            "order_sys_id": _SYS_ID,
            "order_ref": _ORDER_REF,
            "connection_generation": 1,
            "status": "accepted",
            "filled": 0,
            "price": 3600.0,
        },
        from_query=True,
    )

    assert order.info.get("order_sys_id") == _SYS_ID
    assert order.info.get("connection_generation") == 1
    assert order.info.get("registered_sim_ctp_order_sys_id") is None
    assert broker.execution_order_snapshot()[0].order_sys_id is None


def test_registered_submit_response_sys_id_does_not_project_without_callback():
    _api, _store, broker, order = _system(
        response={
            "order_ref": _ORDER_REF,
            "front_id": 4,
            "session_id": 7,
            "exchange_id": _EXCHANGE,
            "order_sys_id": _SYS_ID,
        }
    )
    order.addinfo(order_sys_id=_SYS_ID, front_id=4, session_id=7)

    assert broker.execution_order_snapshot()[0].order_sys_id is None


def test_callback_without_predispatch_capture_cannot_bind_its_own_identity():
    api, _store, broker, order = _system(capture=False)

    _deliver(api, broker, _callback_payload())

    assert order.info.get("_registered_sim_ctp_identity_binding_captured") is None
    assert order.info.get("registered_sim_ctp_order_sys_id") is None
    assert broker.execution_order_snapshot()[0].order_sys_id is None


def test_response_identity_mismatch_cannot_self_certify_callback():
    api, _store, broker, order = _system(
        response={
            "order_ref": _ORDER_REF,
            "front_id": 5,
            "session_id": 8,
            "exchange_id": _EXCHANGE,
        }
    )

    _deliver(api, broker, _callback_payload(FrontID=5, SessionID=8))

    assert order.info.get("_registered_sim_ctp_submitted_front_id") == 4
    assert order.info.get("_registered_sim_ctp_submitted_session_id") == 7
    assert order.info.get("registered_sim_ctp_order_sys_id") is None
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is True
    snapshot = broker.execution_order_snapshot()[0]
    assert snapshot.order_sys_id is None
    assert snapshot.execution_unknown is True


def test_conflicting_callback_never_overwrites_a_prior_source_identity():
    api, _store, broker, order = _system()
    _deliver(api, broker, _callback_payload())
    _deliver(api, broker, _callback_payload(OrderSysID="SYS9999"))

    assert order.info.get("registered_sim_ctp_order_sys_id") == _SYS_ID
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is True
    snapshot = broker.execution_order_snapshot()[0]
    assert snapshot.order_sys_id is None
    assert snapshot.execution_unknown is True


class _SubmitStore:
    registered_sim_route_id = "simnow-registered-v1"
    allow_writes = True
    provider = "test"
    uses_async_commands = True
    contract_metadata = {_INSTRUMENT: {"instrument_id": _INSTRUMENT, "exchange_id": _EXCHANGE}}

    def __init__(self, response):
        self.response = response
        self.submit_calls = []

    def submit_order(self, order):
        self.submit_calls.append(order)
        return self.response


class _SubmitScope:
    def __init__(self, *, front_id=4, session_id=7):
        self.front_id = front_id
        self.session_id = session_id
        self.begin_calls = []
        self.settlements = []

    def begin_order(self, order, *, action):
        from types import SimpleNamespace

        self.begin_calls.append((order, action))
        return SimpleNamespace(
            intent=SimpleNamespace(
                original_identity={"front_id": self.front_id, "session_id": self.session_id}
            ),
            order_ref=_ORDER_REF,
            instrument_id=_INSTRUMENT,
            exchange_id=_EXCHANGE,
        )

    def complete_order(self, order, attempt, *, response=None, error=None):
        state = "UNKNOWN" if error is not None else "KNOWN"
        outcome = getattr(error, "code", "submit_error") if error is not None else "native_ack"
        self.settlements.append(
            {
                "attempt": attempt,
                "state": state,
                "outcome": outcome,
                "response": response,
                "error": error,
            }
        )
        order.addinfo(
            factor_dispatch_state=state,
            factor_dispatch_outcome=outcome,
            execution_unknown=state == "UNKNOWN",
        )
        return SimpleNamespace(state=state, outcome_code=outcome)


def _submit_broker(*, intent_front=4, intent_session=7, response=None):
    store = _SubmitStore(
        response
        or {
            "order_ref": _ORDER_REF,
            "front_id": 4,
            "session_id": 7,
            "exchange_id": _EXCHANGE,
        }
    )
    broker = BtApiBroker(
        store=store,
        provider="test",
        cash=100_000,
        validation_enabled=False,
        cash_check_enabled=False,
        contract_metadata=store.contract_metadata,
    )
    scope = _SubmitScope(front_id=intent_front, session_id=intent_session)
    broker.factor_execution_coordinator = SimpleNamespace(
        broker=broker,
        active_scope_for_order=lambda _order: scope,
    )

    class SubmitData:
        _name = _INSTRUMENT
        _dataname = _INSTRUMENT
        close = [3600.0]
        datetime = [0.0]
        p = SimpleNamespace(dataname=_INSTRUMENT)

        def __len__(self):
            return 0

    data = SubmitData()
    order = BuyOrder(
        data=data,
        size=2,
        price=3600.0,
        exectype=OrderBase.Limit,
        simulated=True,
    )
    order.addinfo(
        offset="open",
        instrument_id=_INSTRUMENT,
        exchange_id=_EXCHANGE,
        factor_position_effect="OPEN",
        factor_session_front_id=4,
        factor_session_id=7,
        front_id=4,
        session_id=7,
    )
    return broker, store, scope, order


def test_submit_does_not_call_store_when_predispatch_identity_capture_fails():
    broker, store, scope, order = _submit_broker(intent_front=5, intent_session=8)

    result = broker.submit(order)

    assert result is order
    assert store.submit_calls == []
    assert len(scope.begin_calls) == 1
    assert len(scope.settlements) == 1
    settlement = scope.settlements[0]
    assert settlement["state"] == "UNKNOWN"
    assert settlement["outcome"] == "REGISTERED_SIM_CTP_IDENTITY_PREFLIGHT_FAILED"
    assert settlement["response"] is None
    assert order.info.get("factor_dispatch_identity_state") == "BLOCKED"
    assert order.info.get("execution_unknown") is True
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is True
    assert len(broker.notifs) == 1
    assert broker.notifs[0].info.get("factor_dispatch_identity_state") == "BLOCKED"

    retry = BuyOrder(
        data=order.data,
        size=1,
        price=3600.0,
        exectype=OrderBase.Limit,
        simulated=True,
    )
    retry.addinfo(offset="open", instrument_id=_INSTRUMENT, exchange_id=_EXCHANGE)
    assert broker.submit(retry).getstatusname() == "Rejected"
    assert store.submit_calls == []
    assert len(scope.begin_calls) == 1
    assert len(scope.settlements) == 1


def test_submit_response_identity_mismatch_is_settled_once_and_not_acknowledged():
    response = {
        "order_ref": _ORDER_REF,
        "front_id": 5,
        "session_id": 8,
        "exchange_id": _EXCHANGE,
    }
    broker, store, scope, order = _submit_broker(response=response)

    result = broker.submit(order)

    assert result is order
    assert store.submit_calls == [order]
    assert len(scope.begin_calls) == 1
    assert len(scope.settlements) == 1
    settlement = scope.settlements[0]
    assert settlement["state"] == "KNOWN"
    assert settlement["outcome"] == "native_ack"
    assert settlement["response"] is response
    assert order.info.get("factor_dispatch_state") == "KNOWN"
    assert order.info.get("factor_dispatch_identity_state") == "CONFLICT"
    assert order.info.get("execution_unknown") is True
    assert order.info.get("error_code") == "REGISTERED_SIM_CTP_RESPONSE_IDENTITY_MISMATCH"
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is True
    assert order.info.get("_registered_sim_ctp_submitted_front_id") == 4
    assert order.info.get("_registered_sim_ctp_submitted_session_id") == 7
    assert order.info.get("front_id") == 4
    assert order.info.get("session_id") == 7
    assert order.info.get("exchange_id") == _EXCHANGE
    assert len(broker.notifs) == 1
    notice = broker.notifs[0]
    assert notice.info.get("factor_dispatch_state") == "KNOWN"
    assert notice.info.get("factor_dispatch_identity_state") == "CONFLICT"
    assert notice.info.get("execution_unknown") is True
    assert notice.info.get("front_id") == 4
    assert notice.info.get("session_id") == 7

    retry = BuyOrder(
        data=order.data,
        size=1,
        price=3600.0,
        exectype=OrderBase.Limit,
        simulated=True,
    )
    retry.addinfo(offset="open", instrument_id=_INSTRUMENT, exchange_id=_EXCHANGE)
    assert broker.submit(retry).getstatusname() == "Rejected"
    assert store.submit_calls == [order]
    assert len(scope.begin_calls) == 1
    assert len(scope.settlements) == 1


def test_identity_mismatch_after_projection_fails_closed_without_raw_sys_id():
    api, _store, broker, order = _system()
    _deliver(api, broker, _callback_payload())
    _deliver(api, broker, _callback_payload(OrderSysID="", FrontID=5))

    assert order.info.get("registered_sim_ctp_order_sys_id") == _SYS_ID
    assert order.info.get("registered_sim_ctp_order_sys_id_conflict") is True
    snapshot = broker.execution_order_snapshot()[0]
    assert snapshot.order_sys_id is None
    assert snapshot.execution_unknown is True


def test_non_registered_route_keeps_generation_guard_for_sys_id_evidence():
    api, store, broker, order = _system(route_id="generic-ctp")

    _deliver(api, broker, _callback_payload())

    assert order.info.get("registered_sim_ctp_order_sys_id") is None
    assert order.info.get("order_sys_id") is None
    assert broker.execution_order_snapshot()[0].order_sys_id is None

    broker._cache_order_identifiers(
        order,
        {
            "kind": "order",
            "order_sys_id": _SYS_ID,
            "order_ref": _ORDER_REF,
            "connection_generation": 0,
        },
    )
    assert order.info.get("order_sys_id") is None

    broker._cache_order_identifiers(
        order,
        {
            "kind": "order",
            "order_sys_id": _SYS_ID,
            "order_ref": _ORDER_REF,
            "connection_generation": 1,
        },
    )
    assert order.info.get("order_sys_id") == _SYS_ID
    assert order.info.get("connection_generation") == 1
