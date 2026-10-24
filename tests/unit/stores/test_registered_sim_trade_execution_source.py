"""RegisteredSim binds CTP order updates to their native trade fill source."""

from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStoreError, _create_ctp_wrapper_class
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper
from tests.test_utils.optional_sdk import optional_sdk


def _registered_store():
    optional_sdk("bt_api_ctp.ctp.client")
    ctp_wrapper = _create_ctp_wrapper_class()
    api_cls = type(
        "TestRegisteredSimCtpClient",
        (RegisteredSimWrapper, ctp_wrapper),
        {"__module__": __name__},
    )
    api = api_cls(registered_sim_allow_writes=False)
    api._connected = True
    store = RegisteredSimStore(api=api, autostart=False)
    store._connected = True
    return store, api


def _order_payload(*, status="5", filled=1, remaining=1):
    return SimpleNamespace(
        OrderRef="7001",
        OrderSysID="SYS7001",
        InstrumentID="rb2611",
        ExchangeID="SHFE",
        FrontID=4,
        SessionID=7,
        OrderStatus=status,
        OrderSubmitStatus="3",
        StatusMsg="",
        Direction="0",
        CombOffsetFlag="0",
        LimitPrice=3600.0,
        VolumeTotalOriginal=2,
        VolumeTraded=filled,
        VolumeTotal=remaining,
        UpdateTime="09:31:00",
        InsertTime="09:30:00",
    )


def _pending_order(api):
    api._pending_orders["7001"] = {
        "order_ref": "7001",
        "data_name": "rb2611",
        "instrument": "rb2611",
        "exchange_id": "SHFE",
        "side": "buy",
        "offset": "open",
        "price": 3600.0,
        "size": 2,
        "front_id": 4,
        "session_id": 7,
    }


def test_registered_sim_binds_real_ctp_order_normalization_before_broker_poll():
    store, api = _registered_store()
    _pending_order(api)

    # The production CTP normalizer sees a native-shaped callback and emits
    # cumulative volume plus limit price; it does not trust a caller marker.
    api._handle_order(_order_payload())
    normalized = api._order_updates[-1]
    assert normalized["kind"] == "order"
    assert normalized["filled"] == 1
    assert normalized["price"] == 3600.0
    assert "execution_source" not in normalized

    # RegisteredSimStore binds its fixed CTP contract on the Store-to-Broker
    # return path, before Broker can apply cumulative quantity as a fill.
    projected = store.poll_broker_update()
    assert projected["execution_source"] == "trades"
    assert normalized.get("execution_source") is None  # shared queue row untouched


def test_registered_sim_keeps_trade_events_distinct_from_order_fill_mode():
    store, api = _registered_store()
    _pending_order(api)
    trade = SimpleNamespace(
        OrderRef="7001",
        OrderSysID="SYS7001",
        TradeID="TRADE7001",
        InstrumentID="rb2611",
        ExchangeID="SHFE",
        Direction="0",
        OffsetFlag="0",
        Price=3599.0,
        Volume=1,
        TradeDate="20261025",
        TradeTime="09:31:01",
    )

    api._handle_trade(trade)
    projected = store.poll_broker_update()

    assert projected["kind"] == "trade"
    assert projected["trade_id"] == "TRADE7001"
    assert projected["price"] == 3599.0
    assert "execution_source" not in projected


def test_registered_sim_binds_open_order_and_terminal_query_rows_without_mutating_inputs():
    store, api = _registered_store()
    raw_open_row = {
        "kind": "order",
        "order_ref": "7001",
        "status": "partial",
        "filled": 1,
        "price": 3600.0,
    }
    api.fetch_open_orders = lambda: [raw_open_row]

    open_orders = store.fetch_open_orders(force=True)

    assert open_orders == [{**raw_open_row, "execution_source": "trades"}]
    assert "execution_source" not in raw_open_row

    query_order = {
        "OrderRef": "7001",
        "OrderSysID": "SYS7001",
        "OrderStatus": "5",
        "VolumeTotalOriginal": 2,
        "VolumeTraded": 1,
        "VolumeTotal": 1,
        "LimitPrice": 3600.0,
    }
    query_provenance = {"orders": {"request_id": 17, "complete": True}}
    raw_snapshot = {"orders": [query_order], "query_results": query_provenance}
    store._build_ctp_query_snapshot = lambda **_kwargs: raw_snapshot

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["orders"] == [{**query_order, "execution_source": "trades"}]
    assert "execution_source" not in query_order
    assert snapshot["query_results"] is query_provenance


def test_registered_sim_rejects_conflicting_order_source_instead_of_overwriting():
    with pytest.raises(BtApiStoreError, match="execution source conflicts"):
        RegisteredSimStore._project_trade_driven_order(
            {"kind": "order", "execution_source": "cumulative"}
        )
