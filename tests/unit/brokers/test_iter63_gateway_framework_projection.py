"""Real BT object graph serialization; no provider or live account access."""

import copy
import datetime as dt
import json

import pytest
import backtrader as bt
from backtrader.feed import DataBase
from backtrader.brokers._btapi_gateway_projection import (
    capture_framework_state,
    restore_framework_state,
)


def feed(name="rb"):
    data = DataBase()
    data._name = name
    data._tz = None
    data.forward()
    data.datetime[0] = bt.date2num(dt.datetime(2026, 11, 9, 9, 30))
    data.close[0] = 10.0
    return data


def graph():
    data = feed()
    broker = bt.brokers.BackBroker()
    owner = object()
    comm = broker.getcommissioninfo(data)
    order = bt.BuyOrder(
        owner=owner,
        data=data,
        size=4,
        price=10.0,
        exectype=bt.Order.Limit,
        tradeid=7,
        transmit=True,
        histnotify=True,
    )
    order.submit(broker)
    order.accept(broker)
    order.addcomminfo(comm)
    order.info.custom = {"finite": [1, 2.5, None]}
    order.execute(data.datetime[0], 1, 10, 0, 0, 0, 1, 10, 0.1, 0, 0, 1, 10)
    notification = order.clone()
    trade = bt.Trade(data=data, tradeid=(7, "long"), historyon=True)
    trade.update(notification, 1, 10, 10, 0.1, 0, comm)
    trade_notice = copy.copy(trade)
    second = bt.SellOrder(
        owner=owner,
        data=data,
        size=1,
        price=11.0,
        exectype=bt.Order.Limit,
        tradeid=7,
        parent=order,
        oco=notification,
    )
    second.submit(broker)
    second.accept(broker)
    pos = bt.Position()
    pos.update(1, 10, dt=dt.datetime(2026, 11, 9, 9, 30))
    pos.updt = dt.datetime(2026, 11, 9, 9, 31, tzinfo=dt.timezone.utc)
    order.setposition(pos)
    return (
        data,
        broker,
        owner,
        {"orig": order, "notice": notification, "sell": second},
        {"rb": pos},
        {"trade": trade, "trade_notice": trade_notice},
    )


def capture(g):
    data, broker, owner, orders, positions, trades = g
    return capture_framework_state(
        orders=orders,
        positions=positions,
        trades=trades,
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
    )


def test_real_objects_share_graph_and_resume_without_duplicate_fill():
    data, broker, owner, orders, positions, trades = g = graph()
    before_pending = (orders["orig"].executed.p1, orders["orig"].executed.p2)
    snapshot = capture(g)
    assert snapshot == json.loads(json.dumps(snapshot, allow_nan=False))
    assert (orders["orig"].executed.p1, orders["orig"].executed.p2) == before_pending
    new_data, new_broker, new_owner = feed(), bt.brokers.BackBroker(), object()
    restored = restore_framework_state(
        snapshot,
        data_by_ref={"rb": new_data},
        owner=new_owner,
        broker=new_broker,
        commission_for_data=new_broker.getcommissioninfo,
    )
    original, notice, sell = (
        restored.orders["orig"],
        restored.orders["notice"],
        restored.orders["sell"],
    )
    trade, trade_notice = restored.trades["trade"], restored.trades["trade_notice"]
    assert original is not notice and original.ref == notice.ref != orders["orig"].ref
    assert restored.order_refs[orders["orig"].ref] == original.ref
    assert (
        original.p is notice.p
        and original.info is notice.info
        and original.created is notice.created
    )
    assert (
        original.executed is not notice.executed
        and original.executed.exbits is notice.executed.exbits
    )
    assert [bit.size for bit in notice.executed.getpending()] == [1]
    assert sell.parent is original and sell.oco is notice
    assert original.position is restored.positions["rb"]
    assert restored.positions["rb"].datetime == positions["rb"].datetime
    assert restored.positions["rb"].updt == positions["rb"].updt
    assert trade is not trade_notice and trade.ref == trade_notice.ref
    assert trade.history is trade_notice.history and trade.history[0].event.order is notice
    assert restored.trade_refs[trades["trade"].ref] == trade.ref
    assert (trade.size, trade.price, trade.commission) == (1, 10.0, 0.1)
    original.execute(new_data.datetime[0], 1, 11, 0, 0, 0, 1, 11, 0.2, 0, 0, 2, 10.5)
    trade.update(original, 1, 11, 11, 0.2, 0, new_broker.getcommissioninfo(new_data))
    assert original.executed.size == 2 and len(original.executed.exbits) == 2
    assert trade.size == 2 and len(trade.history) == 2
    assert len(trade_notice.history) == 2


def test_invalid_input_rejected_without_mutating_sources():
    g = graph()
    data, broker, owner, orders, positions, trades = g
    snapshot = capture(g)
    corrupt = copy.deepcopy(snapshot)
    corrupt["state"]["orders"]["sell"]["status"] = 999
    unchanged = copy.deepcopy(corrupt)
    with pytest.raises(ValueError):
        restore_framework_state(
            corrupt,
            data_by_ref={"rb": feed()},
            owner=object(),
            broker=bt.brokers.BackBroker(),
            commission_for_data=lambda data: None,
        )
    assert corrupt == unchanged
    with pytest.raises(ValueError):
        capture_framework_state(
            orders={"orig": orders["orig"]},
            positions=positions,
            trades=trades,
            data_by_ref={"rb": data},
            owner=owner,
            broker=broker,
        )
    orders["orig"].info["unsupported"] = object()
    with pytest.raises(ValueError):
        capture(g)


def test_feed_scope_and_invalid_numeric_rejected():
    data, broker, owner, orders, positions, trades = g = graph()
    snapshot = capture(g)
    with pytest.raises(ValueError):
        restore_framework_state(
            snapshot,
            data_by_ref={"rb": feed("other")},
            owner=object(),
            broker=bt.brokers.BackBroker(),
            commission_for_data=lambda data: None,
        )
    positions["rb"].price = float("nan")
    with pytest.raises(ValueError):
        capture(g)


def test_broker_notification_info_aliases_oco_fee_ids_and_unbound_broker():
    from collections import deque

    data, broker, owner, orders, positions, trades = g = graph()
    original, notice, child = orders["orig"], orders["notice"], orders["sell"]
    notice.info = copy.copy(original.info)  # BtApiBroker.notify top-level snapshot
    original.info["later"] = True
    original.info["oco"] = child
    original.info["restart_notice"] = ("waiting", "req-a")
    notice.fee_correction_ids = ("fee-a", "fee-b")
    notice.executed.exbits = deque(notice.executed.exbits)
    original.broker = None
    assert notice.info["custom"] is original.info["custom"]
    snapshot = capture(g)
    target_data, target_broker, target_owner = feed(), bt.brokers.BackBroker(), object()
    result = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target_data},
        owner=target_owner,
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    restored, notification = result.orders["orig"], result.orders["notice"]
    assert restored.broker is None and notification.broker is target_broker
    assert restored.brokerstatus() == restored.status
    assert restored.info is not notification.info
    assert restored.info["custom"] is notification.info["custom"]
    assert restored.info["later"] is True and "later" not in notification.info
    assert restored.info["oco"] is result.orders["sell"]
    assert restored.info["restart_notice"] == ("waiting", "req-a")
    assert type(restored.info["restart_notice"]) is tuple
    assert notification.fee_correction_ids == ("fee-a", "fee-b")
    assert restored.executed.exbits is not notification.executed.exbits
    assert restored.executed.exbits[0] is notification.executed.exbits[0]


def test_history_close_short_reversal_and_economics_are_preserved():
    data, broker, owner = feed(), bt.brokers.BackBroker(), object()
    comm = broker.getcommissioninfo(data)
    sell = bt.SellOrder(owner=owner, data=data, size=3, price=10.0, exectype=bt.Order.Limit)
    buy = bt.BuyOrder(owner=owner, data=data, size=3, price=9.0, exectype=bt.Order.Limit)
    sell.submit(broker)
    buy.submit(broker)
    short = bt.Trade(data=data, tradeid=(9, "short"), historyon=True)
    short.update(sell, -3, 10, 30, 0.3, 0, comm)
    short.update(buy, 1, 9, 9, 0.1, 0, comm)
    short.update(buy, 2, 8, 16, 0.2, 0, comm)
    assert short.isclosed and short.pnl != 0 and len(short.history) == 3
    reversal = bt.Trade(data=data, tradeid=10, historyon=True)
    reversal.update(buy, 2, 10, 20, 0.2, 0, comm)
    reversal.update(sell, -3, 11, 33, 0.3, 0, comm)
    snapshot = capture_framework_state(
        orders={"sell": sell, "buy": buy},
        positions={},
        trades={"short": short, "reversal": reversal},
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
    )
    target_data, target_broker = feed(), bt.brokers.BackBroker()
    restored = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target_data},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    for key, source in (("short", short), ("reversal", reversal)):
        actual = restored.trades[key]
        for field in (
            "status",
            "size",
            "price",
            "value",
            "commission",
            "pnl",
            "pnlcomm",
            "long",
            "isclosed",
            "isopen",
            "barlen",
        ):
            assert getattr(actual, field) == getattr(source, field)
        assert len(actual.history) == len(source.history)
    assert restored.trades["short"].history[-1].event.order is restored.orders["buy"]


def test_timezone_fold_is_anchored_to_trusted_feed():
    from zoneinfo import ZoneInfo

    data, broker, owner = feed(), bt.brokers.BackBroker(), object()
    tz = ZoneInfo("America/New_York")
    data._tz = tz
    order = bt.BuyOrder(owner=owner, data=data, size=1, price=10.0, simulated=True)
    order.submit(broker)
    trade = bt.Trade(data=data, historyon=True)
    trade.update(order, 1, 10, 10, 0.1, 0, broker.getcommissioninfo(data))
    position = bt.Position(1, 10)
    position.datetime = dt.datetime(2026, 11, 1, 1, 30, tzinfo=tz, fold=1)
    position.updt = dt.datetime(2026, 11, 1, 1, 30, tzinfo=tz, fold=0)
    snapshot = capture_framework_state(
        orders={"a": order},
        positions={"rb": position},
        trades={"t": trade},
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
    )
    target = feed()
    target._tz = ZoneInfo("America/New_York")
    target_broker = bt.brokers.BackBroker()
    restored = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    assert restored.positions["rb"].datetime.fold == 1
    assert restored.positions["rb"].updt.fold == 0
    assert restored.positions["rb"].datetime.tzinfo is target._tz
    assert restored.trades["t"].history[0].status.tz is target._tz


def test_unknown_extensions_and_outside_oco_ref_fail_closed():
    data, broker, owner, orders, positions, trades = g = graph()
    outside = bt.BuyOrder(owner=owner, data=data, size=1, price=10.0, simulated=True)
    orders["orig"].info["oco"] = outside
    with pytest.raises(ValueError):
        capture(g)
    del orders["orig"].info["oco"]
    orders["orig"].unknown_extension = 5
    with pytest.raises(ValueError):
        capture(g)


def test_commission_parameters_cache_class_and_no_double_percent_scaling():
    data, broker, owner, orders, positions, trades = g = graph()
    source = bt.CommInfoBase(
        commission=1.0,
        open_commission=0.5,
        mult=3.0,
        commtype=bt.CommInfoBase.COMM_PERC,
        percabs=False,
    )
    broker.addcommissioninfo(source)
    orders["orig"].comminfo = source
    orders["notice"].comminfo = source
    assert source.get_param("commission") == 0.01
    snapshot = capture(g)
    target, target_broker = feed(), bt.brokers.BackBroker()
    equivalent = bt.CommInfoBase(
        commission=1.0,
        open_commission=0.5,
        mult=3.0,
        commtype=bt.CommInfoBase.COMM_PERC,
        percabs=False,
    )
    target_broker.addcommissioninfo(equivalent)
    restored = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    assert restored.orders["orig"].comminfo is equivalent
    assert equivalent.get_param("commission") == 0.01
    assert equivalent.getcommission(2, 10, role="open") == source.getcommission(2, 10, role="open")
    for altered in (
        bt.CommInfoBase(commission=1.0, open_commission=0.5, mult=4.0, commtype=0, percabs=False),
        bt.CommInfoBase(commission=1.0, open_commission=0.6, mult=3.0, commtype=0, percabs=False),
        bt.CommissionInfo(
            commission=0.01, open_commission=0.005, mult=3.0, commtype=0, percabs=True
        ),
    ):
        target_broker.addcommissioninfo(altered)
        with pytest.raises(ValueError):
            restore_framework_state(
                snapshot,
                data_by_ref={"rb": target},
                owner=object(),
                broker=target_broker,
                commission_for_data=target_broker.getcommissioninfo,
            )
    equivalent._mult = 4
    target_broker.addcommissioninfo(equivalent)
    with pytest.raises(ValueError):
        restore_framework_state(
            snapshot,
            data_by_ref={"rb": target},
            owner=object(),
            broker=target_broker,
            commission_for_data=target_broker.getcommissioninfo,
        )
    equivalent._mult = 3
    equivalent._getcommission_accepts_role = False
    with pytest.raises(ValueError):
        restore_framework_state(
            snapshot,
            data_by_ref={"rb": target},
            owner=object(),
            broker=target_broker,
            commission_for_data=target_broker.getcommissioninfo,
        )


def test_stale_commission_rejected_and_shared_across_feeds_must_remain_shared():
    a, b = feed("a"), feed("b")
    broker, owner = bt.brokers.BackBroker(), object()
    original = bt.CommInfoBase(commission=0.01, percabs=True)
    broker.addcommissioninfo(original)
    one = bt.BuyOrder(owner=owner, data=a, size=1, price=10, simulated=True)
    two = bt.BuyOrder(owner=owner, data=b, size=1, price=10, simulated=True)
    for order in (one, two):
        order.submit(broker)
        order.addcomminfo(original)
    kwargs = dict(
        orders={"one": one, "two": two},
        positions={},
        trades={},
        data_by_ref={"a": a, "b": b},
        owner=owner,
        broker=broker,
    )
    snapshot = capture_framework_state(**kwargs)
    broker.addcommissioninfo(bt.CommInfoBase(commission=0.01, percabs=True))
    with pytest.raises(ValueError):
        capture_framework_state(**kwargs)
    target_a, target_b = feed("a"), feed("b")
    target_broker = bt.brokers.BackBroker()
    shared = bt.CommInfoBase(commission=0.01, percabs=True)
    target_broker.addcommissioninfo(shared)
    result = restore_framework_state(
        snapshot,
        data_by_ref={"a": target_a, "b": target_b},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    assert result.orders["one"].comminfo is result.orders["two"].comminfo is shared
    target_broker.addcommissioninfo(bt.CommInfoBase(commission=0.01, percabs=True), name="b")
    with pytest.raises(ValueError):
        restore_framework_state(
            snapshot,
            data_by_ref={"a": target_a, "b": target_b},
            owner=object(),
            broker=target_broker,
            commission_for_data=target_broker.getcommissioninfo,
        )


def test_same_ref_trade_long_can_move_from_none_but_cannot_conflict():
    data, broker, owner, orders, positions, trades = g = graph()
    trades["trade_notice"].long = None
    assert capture(g)
    trades["trade_notice"].long = False
    with pytest.raises(ValueError):
        capture(g)


def test_shared_info_dag_rechecks_subtree_depth_for_each_root():
    data, broker, owner, orders, positions, _ = graph()
    shallow, deep = orders["orig"], orders["notice"]
    from backtrader.utils.autodict import AutoOrderedDict

    shared = {"leaf": 1}
    for _ in range(6):
        shared = {"child": shared}
    shallow.info = AutoOrderedDict()
    shallow.info["x"] = shared
    deep.info = AutoOrderedDict()
    deep.info["x"] = {"first": shared}
    kwargs = dict(
        orders={"a": shallow, "b": deep},
        positions=positions,
        trades={},
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
    )
    snapshot = capture_framework_state(**kwargs)
    target_data, target_broker = feed(), bt.brokers.BackBroker()
    restored = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target_data},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    assert restored.orders["a"].info["x"] is restored.orders["b"].info["x"]["first"]

    # Each parent adds one level; a shared node validated at the shallow root
    # cannot bypass the deeper root's logical nesting bound.
    deep.info["x"] = {"a": {"b": {"c": shared}}}
    with pytest.raises(ValueError):
        capture_framework_state(**kwargs)

    # A malformed flattened wire DAG gets the same per-root check.
    corrupt = copy.deepcopy(snapshot)
    groups = corrupt["state"]["groups"]
    info_a = corrupt["state"]["orders"]["a"]["info"]
    info_b = corrupt["state"]["orders"]["b"]["info"]
    root_a = groups["info"][info_a]["root"]["ref"]
    root_b = groups["info"][info_b]["root"]["ref"]
    shared_ref = groups["info_nodes"][root_a]["items"]["x"]["ref"]
    target = {"ref": shared_ref}
    for i in range(4):
        key = f"extra-{i}"
        groups["info_nodes"][key] = {"kind": "dict", "closed": False, "items": {"x": target}}
        target = {"ref": key}
    groups["info_nodes"][root_b]["items"]["x"] = target
    with pytest.raises(ValueError):
        restore_framework_state(
            corrupt,
            data_by_ref={"rb": feed()},
            owner=object(),
            broker=bt.brokers.BackBroker(),
            commission_for_data=lambda d: None,
        )


def test_commission_snapshot_does_not_mutate_parameter_cache():
    data, broker, owner, orders, positions, trades = g = graph()
    source = orders["orig"].comminfo
    cache_before = dict(source._param_manager._value_cache)
    capture(g)
    assert source._param_manager._value_cache == cache_before


def test_unsupported_commission_model_fails_closed():
    class Custom(bt.CommInfoBase):
        pass

    data, broker, owner, orders, positions, trades = g = graph()
    custom = Custom()
    broker.addcommissioninfo(custom)
    orders["orig"].comminfo = orders["notice"].comminfo = custom
    with pytest.raises(ValueError):
        capture(g)


@pytest.mark.parametrize("status", [bt.Order.Completed, bt.Order.Canceled, bt.Order.Rejected])
def test_terminal_order_preserves_late_execution_bits(status):
    data, broker, owner, orders, positions, trades = g = graph()
    order = orders["orig"]
    order.status = status
    order.execute(data.datetime[0], 1, 11, 0, 0, 0, 1, 11, 0.2, 0, 0, 2, 10.5)
    order.status = status  # an externally observed terminal state after late execution
    order.executed.markpending()
    snapshot = capture(g)
    target_data, target_broker = feed(), bt.brokers.BackBroker()
    result = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target_data},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    restored = result.orders["orig"]
    assert restored.status == status
    assert restored.executed.size == order.executed.size
    assert [b.size for b in restored.executed.exbits] == [1, 1]
    assert (restored.executed.p1, restored.executed.p2) == (order.executed.p1, order.executed.p2)
    assert [b.size for b in restored.executed.getpending()] == [1]


def test_distinct_source_commission_groups_cannot_be_merged():
    a, b = feed("a"), feed("b")
    broker, owner = bt.brokers.BackBroker(), object()
    first, second = (
        bt.CommInfoBase(commission=0.01, percabs=True),
        bt.CommInfoBase(commission=0.01, percabs=True),
    )
    broker.addcommissioninfo(first, name="a")
    broker.addcommissioninfo(second, name="b")
    order_a = bt.BuyOrder(owner=owner, data=a, size=1, price=10, simulated=True)
    order_b = bt.BuyOrder(owner=owner, data=b, size=1, price=10, simulated=True)
    for order, comm in ((order_a, first), (order_b, second)):
        order.submit(broker)
        order.addcomminfo(comm)
    snapshot = capture_framework_state(
        orders={"a": order_a, "b": order_b},
        positions={},
        trades={},
        data_by_ref={"a": a, "b": b},
        owner=owner,
        broker=broker,
    )
    a2, b2, target = feed("a"), feed("b"), bt.brokers.BackBroker()
    target.addcommissioninfo(bt.CommInfoBase(commission=0.01, percabs=True))
    with pytest.raises(ValueError):
        restore_framework_state(
            snapshot,
            data_by_ref={"a": a2, "b": b2},
            owner=object(),
            broker=target,
            commission_for_data=target.getcommissioninfo,
        )


def test_continuous_vs_restored_trade_close_pnl_and_commission():
    data, broker, owner, orders, positions, trades = g = graph()
    snapshot = capture(g)
    target_data, target_broker = feed(), bt.brokers.BackBroker()
    result = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target_data},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    before, after = trades["trade"], result.trades["trade"]
    before.update(orders["sell"], -1, 12, 12, 0.2, 0, broker.getcommissioninfo(data))
    after.update(
        result.orders["sell"], -1, 12, 12, 0.2, 0, target_broker.getcommissioninfo(target_data)
    )
    assert before.isclosed and after.isclosed
    assert (
        before.size,
        before.price,
        before.value,
        before.commission,
        before.pnl,
        before.pnlcomm,
    ) == (after.size, after.price, after.value, after.commission, after.pnl, after.pnlcomm)


def _supported_commission_types():
    from backtrader import comminfo, commissions

    return [
        comminfo.CommInfoBase,
        comminfo.CommissionInfo,
        comminfo.ComminfoDC,
        comminfo.ComminfoFuturesPercent,
        comminfo.ComminfoFuturesMixed,
        comminfo.ComminfoFuturesInverse,
        comminfo.ComminfoFuturesFixed,
        comminfo.ComminfoFundingRate,
        commissions.CommInfo,
        commissions.CommInfoFutures,
        commissions.CommInfoFuturesPerc,
        commissions.CommInfoFuturesFixed,
        commissions.CommInfoStocks,
        commissions.CommInfoStocksPerc,
        commissions.CommInfoStocksFixed,
    ]


@pytest.mark.parametrize("model", _supported_commission_types(), ids=lambda model: model.__name__)
def test_each_supported_commission_model_roundtrips_actual_behavior(model):
    data, broker, owner = feed(), bt.brokers.BackBroker(), object()
    source = model(commission=1.0, percabs=False)
    broker.addcommissioninfo(source)
    order = bt.BuyOrder(owner=owner, data=data, size=2, price=10, simulated=True)
    order.submit(broker)
    order.addcomminfo(source)
    snapshot = capture_framework_state(
        orders={"a": order},
        positions={},
        trades={},
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
    )
    snapshot = json.loads(json.dumps(snapshot, allow_nan=False))
    target_data, target_broker = feed(), bt.brokers.BackBroker()
    target_model = model(commission=1.0, percabs=False)
    target_broker.addcommissioninfo(target_model)
    restored = restore_framework_state(
        snapshot,
        data_by_ref={"rb": target_data},
        owner=object(),
        broker=target_broker,
        commission_for_data=target_broker.getcommissioninfo,
    )
    comm = restored.orders["a"].comminfo
    assert comm is target_model and type(comm) is model
    assert comm.getcommission(2, 10, role="open") == source.getcommission(2, 10, role="open")
    assert comm.profitandloss(2, 10, 12) == source.profitandloss(2, 10, 12)


def test_codec_rejects_sensitive_keys_and_oversized_json_without_r24():
    g = graph()
    orders = g[3]
    orders["orig"].info["api_key"] = "not-a-real-secret"
    with pytest.raises(ValueError):
        capture(g)
    del orders["orig"].info["api_key"]
    orders["orig"].info["large"] = "x" * (16 * 1024 * 1024)
    with pytest.raises(ValueError):
        capture(g)


def test_codec_rejects_too_many_valid_nodes_directly(monkeypatch):
    from backtrader.brokers import _btapi_gateway_projection as codec

    snapshot = capture(graph())
    groups = snapshot["state"]["groups"]
    order = snapshot["state"]["orders"]["orig"]
    info = groups["info"][order["info"]]
    root = groups["info_nodes"][info["root"]["ref"]]
    for index in range(11):
        node_id = f"many-{index}"
        root["items"][f"branch-{index}"] = {"ref": node_id}
        groups["info_nodes"][node_id] = {
            "kind": "dict",
            "closed": False,
            "items": {f"item-{n}": 0 for n in range(9_999)},
        }
    assert len(json.dumps(snapshot).encode("utf-8")) < 16 * 1024 * 1024
    target, broker = feed(), bt.brokers.BackBroker()
    kwargs = dict(
        data_by_ref={"rb": target},
        owner=object(),
        broker=broker,
        commission_for_data=broker.getcommissioninfo,
    )
    with pytest.raises(ValueError):
        restore_framework_state(snapshot, **kwargs)
    # The same structure satisfies every other schema and reference check.
    with monkeypatch.context() as patch:
        patch.setattr(codec, "_bounded", lambda value: None)
        restored = restore_framework_state(snapshot, **kwargs)
    assert len(restored.orders["orig"].info["branch-0"]) == 9_999
    assert len(restored.orders["orig"].info["branch-10"]) == 9_999


def test_codec_rejects_valid_tradeid_wire_exceeding_json_depth(monkeypatch):
    from backtrader.brokers import _btapi_gateway_projection as codec

    snapshot = capture(graph())
    groups = snapshot["state"]["groups"]
    order = snapshot["state"]["orders"]["orig"]
    tradeid = {"kind": "scalar", "value": 7}
    for _ in range(6):
        tradeid = {"kind": "tuple", "items": [tradeid]}
    groups["params"][order["params"]]["tradeid"] = tradeid
    target, broker = feed(), bt.brokers.BackBroker()
    kwargs = dict(
        data_by_ref={"rb": target},
        owner=object(),
        broker=broker,
        commission_for_data=broker.getcommissioninfo,
    )
    with pytest.raises(ValueError):
        restore_framework_state(snapshot, **kwargs)
    # Six tradeid tuple layers remain valid to the tradeid decoder; the full
    # JSON document exceeds its separate depth limit because of its envelope.
    with monkeypatch.context() as patch:
        patch.setattr(codec, "_bounded", lambda value: None)
        restored = restore_framework_state(snapshot, **kwargs)
    assert restored.orders["orig"].tradeid == ((((((7,),),),),),)
