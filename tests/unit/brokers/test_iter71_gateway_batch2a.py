"""Iteration 71 Batch 2a regression tests: Gateway Events / Notifications / Stream.

Covers:
- R71-001 (== R72-BUG-01): unmapped order status fail-closed + never-raises poll hook
- R71-004 (== R72-BUG-04 + N72-20): SQLite connection cleanup on all __init__ failures
- R71-005: _remember_gateway_order skips per-tick O(N) has_order DB round-trips
- R71-002 (== R72-BUG-02): empty notification batch raises RESTORE_INVALID (no IndexError)
- R71-003 (== R72-BUG-03): pre-check failures do not lock binding.fault='restart_required'
- R71-006: _gateway_graph avoids O(n^2) list(orders.values())[index]
- R71-131: incremental trade_facts index avoids full rescan and >10,000 SCAN_LIMIT
- R71-132: _gateway_stream_next reuses single pass snapshot and skips terminal orders
"""

from __future__ import annotations

import copy
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.brokers import _btapi_gateway_events as gw_events
from backtrader.brokers import _btapi_gateway_stream as gw_stream
from backtrader.brokers._btapi_gateway_events import (
    GatewayExecutionEventsError,
    GatewayExecutionProjectionStore,
    _GatewayExecutionBinding,
    order_update_row,
)
from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_notification_delivery import (
    fill,
    framework as notif_framework,
    setup as notif_setup,
)
from tests.unit.brokers.test_iter63_gateway_stream_consumer import (
    attach,
    deliver,
    event_for,
)
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs


# ---------------------------------------------------------------------------
# Helpers for GatewayExecutionEventsBrokerMixin tests (R71-001, R71-004, R71-005)
# ---------------------------------------------------------------------------


def _make_order_obs(
    *,
    status: object = "open",
    order_id: str = "ext-1",
    client_order_id: str = "cid-1",
    filled_quantity: str = "0",
    quantity: str = "2",
    side: str = "buy",
    qty_unit: str = "contracts",
    intent_binding: str = "verified",
    instrument_id: str = "rb",
    native_symbol: str = "rb",
):
    instrument = SimpleNamespace(instrument_id=instrument_id, native_symbol=native_symbol)
    order = SimpleNamespace(
        status=status,
        order_id=order_id,
        client_order_id=client_order_id,
        filled_quantity=filled_quantity,
        quantity=quantity,
        side=side,
        qty_unit=qty_unit,
        intent_binding=intent_binding,
        instrument=instrument,
    )
    return SimpleNamespace(order=order)


def _setup_gateway_events_broker(tmp_path):
    data, broker, strategy = notif_framework()
    store = GatewayExecutionProjectionStore(
        tmp_path / "proj.sqlite3",
        {"account_ref": "acct-a", "strategy_ref": "strat-a", "consumer": "c-1"},
    )
    events_queue = []
    committed = []
    acked = []

    class FakeConsumer:
        def read(self):
            batch = list(events_queue)
            events_queue.clear()
            return SimpleNamespace(events=batch, cursor=len(committed) + len(batch))

        def commit(self, page):
            committed.append(page)

        def acknowledge(self):
            acked.append(True)

    consumer = FakeConsumer()
    binding = _GatewayExecutionBinding(
        strategy=strategy,
        strategy_ref="strat-a",
        consumer=consumer,
        store=store,
        data_names={"rb": "rb"},
        acknowledge="after_apply",
    )
    broker._gateway_execution_bindings = {id(strategy): binding}
    broker._trading_enabled = True
    return data, broker, strategy, binding, store, events_queue, committed, acked


# ---------------------------------------------------------------------------
# R71-001 (== R72-BUG-01): unmapped order status + never-raises poll contract
# ---------------------------------------------------------------------------


def test_r71_001_unmapped_order_status_projects_unknown_fail_closed(tmp_path):
    from bt_api_base.execution_row_observation_protocol import EXECUTION_ORDER_EVENT_KIND

    # Direct row conversion: undeclared string and unhashable status both map to unknown.
    for bad_status in ("exchange_custom_unmapped_status", None, ["unhashable"]):
        row = order_update_row(_make_order_obs(status=bad_status), data_name="rb", local_ref=1)
        assert row["status"] == "unknown"
        assert row["terminal_confirmed"] is False
        assert row["execution_unknown"] is True

    # End-to-end through _poll_gateway_execution_events on a live order.
    data, broker, strategy, binding, store, events_queue, committed, acked = (
        _setup_gateway_events_broker(tmp_path)
    )
    try:
        order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10.0, exectype=bt.Order.Limit)
        order.addcomminfo(broker.getcommissioninfo(data))
        order.submit(broker)
        order.accept(broker)
        order.addinfo(client_order_id="cid-unmapped")
        broker.orders[order.ref] = order

        obs = _make_order_obs(
            status="vendor_future_state_xyz",
            order_id="ext-unmapped-1",
            client_order_id="cid-unmapped",
            filled_quantity="2",
            quantity="2",
        )
        events_queue.append(
            SimpleNamespace(
                event_id="evt-unmapped-1",
                cursor=1,
                kind=EXECUTION_ORDER_EVENT_KIND,
                observation=obs,
            )
        )

        # Must not raise KeyError; order stays alive, marked execution_unknown, no fills/terminal.
        broker._poll_gateway_execution_events()
        assert order.alive() is True
        assert order.status == order.Accepted
        assert order.executed.size == 0
        assert order.info.get("execution_unknown") is True
        assert binding.state == "ACTIVE"
        assert broker._trading_enabled is True
        assert len(committed) == 1
        assert len(acked) == 1
    finally:
        store.close()


def test_r71_001_poll_hook_never_raises_on_unexpected_exception(tmp_path, monkeypatch):
    data, broker, strategy, binding, store, events_queue, _, _ = _setup_gateway_events_broker(
        tmp_path
    )
    try:
        # Case 1: unexpected sqlite3.Error during store read inside _poll_gateway_binding.
        events_queue.append(SimpleNamespace(event_id="evt-1", cursor=1, kind="order", observation=None))
        monkeypatch.setattr(
            store,
            "has_fact",
            lambda _fact_id: (_ for _ in ()).throw(sqlite3.OperationalError("disk io failed")),
        )
        broker._poll_gateway_execution_events()
        assert binding.state == "FAILED"
        assert broker._trading_enabled is False

        # Reset and verify direct poll_gateway_execution_events wraps it in GatewayExecutionEventsError.
        binding.state = "ACTIVE"
        broker._trading_enabled = True
        events_queue.append(SimpleNamespace(event_id="evt-2", cursor=2, kind="order", observation=None))
        with pytest.raises(GatewayExecutionEventsError) as exc_info:
            broker.poll_gateway_execution_events()
        assert exc_info.value.code == "PROJECTION_STORE_FAILED"
        assert binding.state == "FAILED"
        assert broker._trading_enabled is False

        # Case 2: unexpected non-sqlite exception (e.g. RuntimeError from consumer.read).
        binding.state = "ACTIVE"
        broker._trading_enabled = True
        monkeypatch.setattr(
            binding.consumer,
            "read",
            lambda: (_ for _ in ()).throw(RuntimeError("unexpected consumer crash")),
        )
        broker._poll_gateway_execution_events()
        assert binding.state == "FAILED"
        assert broker._trading_enabled is False
    finally:
        store.close()


# ---------------------------------------------------------------------------
# R71-004 (== R72-BUG-04 + N72-20): SQLite connection close on __init__ errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fail_stage",
    ["pragma", "executescript", "begin", "insert_meta", "unexpected_runtime"],
)
def test_r71_004_projection_store_closes_connection_on_init_errors(
    tmp_path, monkeypatch, fail_stage
):
    real_connect = sqlite3.connect
    tracker = {"opened": 0, "closed": 0, "rollbacks": 0}

    class TrackingConnection:
        def __init__(self, inner):
            self._inner = inner
            self._closed = False
            tracker["opened"] += 1

        @property
        def in_transaction(self):
            return self._inner.in_transaction

        def execute(self, sql, *args):
            upper = sql.strip().upper()
            if fail_stage == "pragma" and upper.startswith("PRAGMA"):
                raise sqlite3.OperationalError("pragma failed")
            if fail_stage == "begin" and upper.startswith("BEGIN IMMEDIATE"):
                raise sqlite3.OperationalError("begin failed")
            if fail_stage == "insert_meta" and upper.startswith("INSERT INTO META"):
                raise sqlite3.OperationalError("insert meta failed")
            if fail_stage == "unexpected_runtime" and upper.startswith("PRAGMA SYNCHRONOUS"):
                raise RuntimeError("boom during init")
            if upper == "ROLLBACK":
                tracker["rollbacks"] += 1
            return self._inner.execute(sql, *args)

        def executescript(self, script):
            if fail_stage == "executescript":
                raise sqlite3.DatabaseError("schema script failed")
            return self._inner.executescript(script)

        def close(self):
            if not self._closed:
                self._closed = True
                tracker["closed"] += 1
            return self._inner.close()

    monkeypatch.setattr(
        gw_events.sqlite3,
        "connect",
        lambda *args, **kwargs: TrackingConnection(real_connect(*args, **kwargs)),
    )

    db_path = tmp_path / f"fail_{fail_stage}.sqlite3"
    if fail_stage == "unexpected_runtime":
        with pytest.raises(RuntimeError, match="boom during init"):
            GatewayExecutionProjectionStore(db_path, {"k": "v"})
    else:
        with pytest.raises(GatewayExecutionEventsError) as exc_info:
            GatewayExecutionProjectionStore(db_path, {"k": "v"})
        assert exc_info.value.code == "PROJECTION_STORE_UNAVAILABLE"

    assert tracker["opened"] == 1
    assert tracker["closed"] == 1  # zero leaked connections
    if fail_stage == "insert_meta":
        assert tracker["rollbacks"] == 1


def test_r71_004_projection_store_closes_connection_on_binding_mismatch(tmp_path, monkeypatch):
    db_path = tmp_path / "mismatch.sqlite3"
    initial = GatewayExecutionProjectionStore(db_path, {"account_ref": "a1"})
    initial.close()

    real_connect = sqlite3.connect
    tracker = {"opened": 0, "closed": 0, "rollbacks": 0}

    class TrackingConnection:
        def __init__(self, inner):
            self._inner = inner
            self._closed = False
            tracker["opened"] += 1

        @property
        def in_transaction(self):
            return self._inner.in_transaction

        def execute(self, sql, *args):
            if sql.strip().upper() == "ROLLBACK":
                tracker["rollbacks"] += 1
            return self._inner.execute(sql, *args)

        def executescript(self, script):
            return self._inner.executescript(script)

        def close(self):
            if not self._closed:
                self._closed = True
                tracker["closed"] += 1
            return self._inner.close()

    monkeypatch.setattr(
        gw_events.sqlite3,
        "connect",
        lambda *args, **kwargs: TrackingConnection(real_connect(*args, **kwargs)),
    )

    with pytest.raises(GatewayExecutionEventsError) as exc_info:
        GatewayExecutionProjectionStore(db_path, {"account_ref": "different"})
    assert exc_info.value.code == "PROJECTION_STORE_BINDING_MISMATCH"
    assert tracker["opened"] == 1
    assert tracker["closed"] == 1
    assert tracker["rollbacks"] == 1


# ---------------------------------------------------------------------------
# R71-005: _remember_gateway_order skips per-tick O(N) has_order DB queries
# ---------------------------------------------------------------------------


def test_r71_005_remember_gateway_order_caches_known_orders_per_store(tmp_path, monkeypatch):
    data, broker, strategy, binding, store, _, _, _ = _setup_gateway_events_broker(tmp_path)
    store2 = GatewayExecutionProjectionStore(
        tmp_path / "proj2.sqlite3",
        {"account_ref": "acct-a", "strategy_ref": "strat-a", "consumer": "c-1"},
    )
    try:
        has_order_calls = []
        orig_has_order = store.has_order

        def counting_has_order(cid):
            has_order_calls.append(cid)
            return orig_has_order(cid)

        monkeypatch.setattr(store, "has_order", counting_has_order)

        # Create 8 orders belonging to this strategy.
        created = []
        for idx in range(8):
            order = bt.BuyOrder(
                owner=strategy, data=data, size=1, price=10.0, exectype=bt.Order.Limit
            )
            order.addcomminfo(broker.getcommissioninfo(data))
            order.submit(broker)
            order.addinfo(client_order_id=f"cid-{idx}")
            broker.orders[order.ref] = order
            created.append(order)

        # Poll 15 consecutive ticks: has_order should be called once per order on tick 1 only.
        for _ in range(15):
            broker.poll_gateway_execution_events(strategy)

        assert len(has_order_calls) == 8

        # Add one new order -> exactly 1 additional has_order query across 5 more ticks.
        extra = bt.BuyOrder(owner=strategy, data=data, size=1, price=11.0, exectype=bt.Order.Limit)
        extra.addcomminfo(broker.getcommissioninfo(data))
        extra.submit(broker)
        extra.addinfo(client_order_id="cid-extra")
        broker.orders[extra.ref] = extra
        for _ in range(5):
            broker.poll_gateway_execution_events(strategy)
        assert len(has_order_calls) == 9

        # Duplicate client_order_id on a different Order instance still fails closed.
        dup = bt.BuyOrder(owner=strategy, data=data, size=1, price=12.0, exectype=bt.Order.Limit)
        dup.addcomminfo(broker.getcommissioninfo(data))
        dup.submit(broker)
        dup.addinfo(client_order_id="cid-0")
        with pytest.raises(GatewayExecutionEventsError) as exc_info:
            broker._remember_gateway_order(binding, dup)
        assert exc_info.value.code == "CLIENT_ORDER_ID_REUSED"

        # If put_order fails on a brand-new order, it must NOT be cached as persisted.
        failing = bt.BuyOrder(
            owner=strategy, data=data, size=1, price=13.0, exectype=bt.Order.Limit
        )
        failing.addcomminfo(broker.getcommissioninfo(data))
        failing.submit(broker)
        failing.addinfo(client_order_id="cid-fail")
        orig_put = store.put_order
        monkeypatch.setattr(
            store,
            "put_order",
            lambda _cid, _rec: (_ for _ in ()).throw(
                GatewayExecutionEventsError("PROJECTION_STORE_FAILED")
            ),
        )
        with pytest.raises(GatewayExecutionEventsError) as exc_info:
            broker._remember_gateway_order(binding, failing)
        assert exc_info.value.code == "PROJECTION_STORE_FAILED"
        assert "cid-fail" not in binding.live
        assert "cid-fail" not in binding._persisted_orders
        monkeypatch.setattr(store, "put_order", orig_put)

        # Swapping binding.store must invalidate the store-bound cache and re-check has_order.
        store2_calls = []
        orig_has_order2 = store2.has_order

        def counting_has_order2(cid):
            store2_calls.append(cid)
            return orig_has_order2(cid)

        monkeypatch.setattr(store2, "has_order", counting_has_order2)
        binding.store = store2
        broker.poll_gateway_execution_events(strategy)
        broker.poll_gateway_execution_events(strategy)
        assert len(store2_calls) == 9
    finally:
        store.close()
        store2.close()


# ---------------------------------------------------------------------------
# R71-002 (== R72-BUG-02): empty notification batch raises RESTORE_INVALID
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("with_fee", [False, True])
def test_r71_002_restore_empty_notifications_batch_raises_restore_invalid(
    state, ready, monkeypatch, with_fee
):
    host, data, broker, strategy, order = notif_setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy._notify()

    new_data, new_broker, new_strategy = notif_framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )

    real_checkpoint = reopened.load_execution_checkpoint()
    real_batch = reopened.load_execution_notification_batch()
    empty_batch = dict(real_batch, notifications=[])

    if with_fee:
        tampered_proj = copy.deepcopy(real_checkpoint.projection)
        tampered_proj["state"]["_gateway_strategy"]["fee"] = {
            "notification_id": "a" * 64,
            "kind": "fee",
            "object_key": next(iter(tampered_proj["state"]["orders"])),
            "payload": {"trade_key": None, "delta": 0.1, "currency": "CNY", "sequence": 1},
        }
        tampered_cp = replace(real_checkpoint, projection=tampered_proj)
        monkeypatch.setattr(reopened, "load_execution_checkpoint", lambda: tampered_cp)

    monkeypatch.setattr(reopened, "load_execution_notification_batch", lambda: empty_batch)

    # Must raise GATEWAY_NOTIFICATION_RESTORE_INVALID, never bare IndexError.
    with pytest.raises(ValueError, match="GATEWAY_NOTIFICATION_RESTORE_INVALID"):
        new_broker.restore_gateway_notification_state(new_strategy)

    binding = new_broker._gateway_binding(new_strategy, required=True)
    assert binding.armed is None
    assert binding.arm_checkpoint is None


# ---------------------------------------------------------------------------
# R71-003 (== R72-BUG-03): pre-check failures do not lock binding.fault
# ---------------------------------------------------------------------------


def test_r71_003_trade_only_and_scope_mismatch_do_not_lock_restart_required(ready, inputs):
    host, data, broker, strategy, order_a = notif_setup(ready)
    binding_cmd, route, intent_fn = inputs
    # Persist a second order ("key-b") on the same host and bind it.
    intent_b = intent_fn("key-b")
    host.save_intent(intent_b)
    rec_a = host.load_record("key-a")
    rec_b = replace(
        rec_a,
        request_key="key-b",
        reservation_id="res-b",
        digest=intent_b.digest,
        native_identity=replace(
            rec_a.native_identity,
            client_order_id="cid-b",
            fields={**rec_a.native_identity.fields, "order_ref": "2"},
        ),
        strong_identity_key_digests=("9" * 64,),
    )
    host.save_record("key-b", rec_b)

    order_b = bt.BuyOrder(owner=strategy, data=data, size=2, price=10.0, exectype=bt.Order.Limit)
    order_b.addcomminfo(broker.getcommissioninfo(data))
    order_b.submit(broker)
    order_b.accept(broker)
    broker.register_gateway_notification_order(strategy, "key-b", order_b)

    # Arm sequence 3 (which belongs to key-a).
    broker.arm_gateway_notification_state(strategy, 3)
    binding = broker._gateway_binding(strategy, required=True)
    assert binding.fault is None

    # 1) Trade-only batch (empty orders) -> EVENT_SCOPE, binding.fault stays None!
    dummy_trade = bt.Trade(data=data)
    with pytest.raises(ValueError, match="GATEWAY_NOTIFICATION_EVENT_SCOPE"):
        broker._gateway_prepare_notifications(strategy, [], [dummy_trade])
    assert binding.fault is None

    # 2) Order scope mismatch (key-b order while key-a is armed) -> EVENT_SCOPE, fault stays None!
    with pytest.raises(ValueError, match="GATEWAY_NOTIFICATION_EVENT_SCOPE"):
        broker._gateway_prepare_notifications(strategy, [order_b.clone()], [])
    assert binding.fault is None

    # 3) Because fault was NOT falsely locked, valid key-a notification still succeeds!
    fill(broker, strategy, order_a)
    strategy._notify()
    assert [ev[0] for ev in strategy.events] == ["order", "trade"]
    assert host.load_execution_notification_batch()["status"] == "confirmed"
    assert binding.fault is None


def test_r71_003_real_post_validation_failure_still_sets_restart_required(ready, monkeypatch):
    host, data, broker, strategy, order = notif_setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    monkeypatch.setattr(
        broker,
        "_gateway_graph",
        lambda *_args: (_ for _ in ()).throw(ValueError("graph_broken")),
    )
    with pytest.raises(ValueError, match="graph_broken"):
        strategy._notify()
    binding = broker._gateway_binding(strategy, required=True)
    assert binding.fault == "restart_required"


# ---------------------------------------------------------------------------
# R71-006: _gateway_graph linear traversal over linked order graph
# ---------------------------------------------------------------------------


def test_r71_006_gateway_graph_linear_traversal_and_completeness(ready, inputs):
    host, data, broker, strategy, root_order = notif_setup(ready)
    binding = broker._gateway_binding(strategy, required=True)
    broker.arm_gateway_notification_state(strategy, 3)

    # Build a 120-node chain of distinct BuyOrder instances referencing each other via
    # parent/oco/info. Each shares root_order.ref so _gateway_request resolves to "key-a".
    chain = [root_order]
    for idx in range(120):
        node = bt.BuyOrder(
            owner=strategy,
            data=data,
            size=2,
            price=10.0,
            exectype=bt.Order.Limit,
            parent=chain[-1],
            oco=chain[-2] if idx >= 2 else None,
        )
        node.addcomminfo(broker.getcommissioninfo(data))
        node.submit(broker)
        node.accept(broker)
        node.ref = root_order.ref
        node.addinfo(prev=chain[-1], nested=[chain[0]])
        chain.append(node)

    snapshot, order_map, _trades, qorders, _qtrades, _op, _tp = broker._gateway_graph(
        binding, [chain[-1]], []
    )
    # Every order in the 121-node chain must be captured exactly once, in deterministic order.
    captured_ids = {id(o) for o in order_map.values()}
    assert len(order_map) == len(chain)
    assert captured_ids == {id(o) for o in chain}
    assert len(qorders) == 1
    assert order_map[qorders[0]] is chain[-1]
    assert len(snapshot["state"]["orders"]) == len(chain)


# ---------------------------------------------------------------------------
# R71-131: incremental trade_facts cursor + index (>10,000 events, no rescan)
# ---------------------------------------------------------------------------


def test_r71_131_incremental_trade_facts_exceeds_10000_without_rescan(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, [])
    binding = broker._gateway_stream_binding

    base_trade = event_for(host, seq=1, quantity="0.1", fact="a" * 64, trade="b" * 64)
    # Build 10,500 synthetic events in memory (10,498 filler events + trade + metadata).
    total_events = 10_500
    trade_seq = 10_499
    meta_seq = 10_500
    target_digest = "e" * 64
    trade_ev = replace(
        base_trade,
        sequence=trade_seq,
        fact_digest="c" * 64,
        observation=replace(
            base_trade.observation,
            trade_key_digest=target_digest,
            trade_date=None,
            trade_time=None,
            trade_metadata_only=False,
        ),
    )
    meta_ev = replace(
        base_trade,
        sequence=meta_seq,
        fact_digest="d" * 64,
        observation=replace(
            base_trade.observation,
            trade_key_digest=target_digest,
            trade_date="20261107",
            trade_time="09:30:00",
            trade_metadata_only=True,
        ),
    )

    # Create lightweight filler events for sequences 1..10498.
    filler_obs = replace(
        base_trade.observation,
        trade_key_digest=None,
        trade_date=None,
        trade_time=None,
        trade_metadata_only=False,
    )
    stream_events = [
        SimpleNamespace(
            sequence=seq,
            request_key="key-a",
            fact_digest=f"{seq:064x}",
            observation=filler_obs,
        )
        for seq in range(1, trade_seq)
    ]
    stream_events.extend([trade_ev, meta_ev])

    read_after_args = []
    available_until = [0]

    def fake_read_events(after_sequence=None, *, limit=256):
        after = 0 if after_sequence is None else after_sequence
        read_after_args.append(after)
        cap = available_until[0]
        if after >= cap:
            return ()
        end = min(cap, after + limit)
        return tuple(stream_events[after:end])

    monkeypatch.setattr(host, "read_execution_events", fake_read_events)

    # Advance in 11 incremental batches of ~1,000 events each (total = 10,500 > 10,000!).
    for step_end in range(1000, total_events + 1, 1000):
        available_until[0] = step_end
        cp = SimpleNamespace(epoch="epoch-1", stored_sequence=step_end)
        broker._refresh_gateway_trade_facts(binding, cp)
    available_until[0] = total_events
    cp_final = SimpleNamespace(epoch="epoch-1", stored_sequence=total_events)
    broker._refresh_gateway_trade_facts(binding, cp_final)

    # Verify incremental cursor reached 10,500 without hitting SCAN_LIMIT, and
    # sequence 0 was only scanned once (at the very beginning).
    assert binding.trade_fact_last_sequence == total_events
    assert read_after_args.count(0) == 1
    assert all(a >= b for a, b in zip(read_after_args[1:], read_after_args))

    # Target trade at seq 10,499 extracted metadata from seq 10,500 cleanly.
    entry = binding.trade_fact_index[("key-a", target_digest)]
    assert entry.min_non_metadata_seq == trade_seq
    assert entry.date == "20261107"
    assert entry.date_digest == meta_ev.fact_digest
    assert entry.time == "09:30:00"
    assert entry.time_digest == meta_ev.fact_digest
    assert entry.date_conflict is False
    assert entry.time_conflict is False

    # Calling refresh again at the same stored_sequence performs ZERO extra reads.
    before_calls = len(read_after_args)
    broker._refresh_gateway_trade_facts(binding, cp_final, target_sequence=trade_seq)
    assert len(read_after_args) == before_calls

    # Epoch change resets cursor and index cleanly.
    available_until[0] = 0
    broker._refresh_gateway_trade_facts(binding, SimpleNamespace(epoch="epoch-2", stored_sequence=0))
    assert binding.trade_fact_last_sequence == 0
    assert binding.trade_fact_index == {}
    assert binding.trade_fact_epoch == "epoch-2"


def test_r71_131_single_step_scan_limit_and_non_advancing_fail_closed(ready, inputs, monkeypatch):
    host, broker, strategy, order, _, _ = attach(ready, inputs, monkeypatch, [])
    monkeypatch.setattr(gw_stream, "_STREAM_EVENT_PAGE_SIZE", 4)
    monkeypatch.setattr(gw_stream, "_STREAM_EVENT_SCAN_LIMIT", 10)

    # 1) Single incremental step exceeding scan limit fails closed with SCAN_LIMIT.
    class OverflowHost:
        def read_execution_events(self, after_sequence=0, limit=256):
            return tuple(
                SimpleNamespace(sequence=after_sequence + i + 1) for i in range(limit)
            )

    with pytest.raises(GatewayExecutionStreamError, match="GATEWAY_STREAM_SCAN_LIMIT"):
        list(broker._gateway_stream_events(OverflowHost(), after=0))

    # 2) Non-advancing page source fails closed with SCAN_LIMIT (no infinite loop).
    class StuckHost:
        def read_execution_events(self, after_sequence=0, limit=256):
            return (SimpleNamespace(sequence=after_sequence),)

    with pytest.raises(GatewayExecutionStreamError, match="GATEWAY_STREAM_SCAN_LIMIT"):
        list(broker._gateway_stream_events(StuckHost(), after=5))


# ---------------------------------------------------------------------------
# R71-132: single-pass host snapshot reuse & terminal-order skip
# ---------------------------------------------------------------------------


def test_r71_132_stream_next_single_snapshot_and_terminal_skip(ready, inputs, monkeypatch):
    monkeypatch.setattr(gw_stream, "_IDLE_READ_INTERVAL_SECONDS", 0.0)
    event1 = event_for(ready[0], seq=3, quantity="0.4", fact="a" * 64, trade="b" * 64)
    event2 = event_for(ready[0], seq=8, quantity="0.6", fact="f" * 64, trade="c" * 64)
    host, broker, strategy, order_a, calls, api = attach(
        ready, inputs, monkeypatch, [event1, event2]
    )
    binding = broker._gateway_stream_binding
    notice = broker._gateway_binding(strategy, required=True)
    _, _, intent_fn = inputs
    rec_a = host.load_record("key-a")

    # Add 20 terminal orders to notice.orders & host.
    for idx in range(20):
        key = f"key-term-{idx}"
        intent_t = intent_fn(key)
        host.save_intent(intent_t)
        rec_t = replace(
            rec_a,
            request_key=key,
            reservation_id=f"res-term-{idx}",
            digest=intent_t.digest,
            native_identity=replace(
                rec_a.native_identity,
                client_order_id=f"cid-term-{idx}",
                fields={**rec_a.native_identity.fields, "order_ref": str(100 + idx)},
            ),
            strong_identity_key_digests=(f"{idx + 10:064x}",),
        )
        host.save_record(key, rec_t)
        term_order = bt.BuyOrder(
            owner=strategy, data=order_a.data, size=1, price=10.0, exectype=bt.Order.Limit
        )
        term_order.addcomminfo(broker.getcommissioninfo(order_a.data))
        term_order.submit(broker)
        term_order.completed()
        notice.orders[key] = term_order
        broker.orders[term_order.ref] = term_order

    # Count actual host._store._load() calls across steps.
    load_count = [0]
    orig_load = host._store._load

    def counting_load():
        load_count[0] += 1
        return orig_load()

    monkeypatch.setattr(host._store, "_load", counting_load)

    # Step 1: ingests and applies event1 (with 21 orders in notice.orders!).
    # Before R71-132, lines 1556-1639 alone performed 2 + 21 + 2 = 25+ _store._load() calls.
    load_count[0] = 0
    broker.next()
    loads_step1 = load_count[0]
    assert order_a.executed.size == pytest.approx(0.4)
    deliver(broker, strategy)

    # Step 2: ACKs seq 3 and applies event2.
    load_count[0] = 0
    broker.next()
    assert calls["ack"] == [3]
    assert order_a.executed.size == pytest.approx(1.0)
    deliver(broker, strategy)

    # Step 3: ACKs seq 8 and hits idle (now all 21 orders are terminal!).
    broker.next()
    assert calls["ack"] == [3, 8]

    # Idle tick with 21 orders: must perform O(1) loads, NOT O(N)!
    # Breakdown on an idle tick: _gateway_stream_check (1) + load_execution_checkpoint (1)
    # + single pass snapshot (1) + read_execution_events (1) + ingest empty page (1) + read_events (1) <= 8.
    load_count[0] = 0
    broker.next()
    loads_idle_21 = load_count[0]
    assert loads_idle_21 <= 8, f"Expected O(1) loads with 21 orders, got {loads_idle_21}"
    assert loads_step1 < 25, f"Expected snapshot reuse during active step, got {loads_step1}"

    # Verify fallback path (when host.local_order_notifications is monkeypatched) calls it ONCE per pass.
    local_calls = [0]
    orig_local = host.local_order_notifications

    def counting_local():
        local_calls[0] += 1
        return orig_local()

    monkeypatch.setattr(host, "local_order_notifications", counting_local)
    broker.next()
    assert local_calls[0] == 1
    assert binding.state == "ACTIVE"
