"""Gateway Broker status-file facts (Iter 72 / 73): non-blocking, finite, fail-closed.

``backtrader.live_trading.gateway_run_facts`` runs on the heartbeat thread and
must never issue RPC, touch SQLite, or fabricate an empty ``write_block_reasons``
list before startup or after shutdown.

Evidence: UNIT/FAKE.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from backtrader.live_trading import (
    RunStatusWriter,
    broker_run_facts,
    gateway_run_facts,
    read_run_status,
)


class _FakeOrder:
    def __init__(self, *, alive: bool = True, info: dict | None = None) -> None:
        self._alive = alive
        self.info = dict(info or {})

    def alive(self) -> bool:
        return self._alive


def _make_gateway_broker(
    *,
    started: bool = True,
    closed: bool = False,
    connected: bool = True,
    composition_uncertain: bool = False,
    market_data_only: bool = False,
    risk_selected: bool = True,
    risk_available: bool | None = True,
    exec_selected: bool = True,
    exec_available: bool | None = True,
    monitor_stop_new: bool = False,
    stream_state: str | None = "ACTIVE",
    waiting_feed: bool = False,
    waiting_session: bool = False,
    orders: dict | None = None,
    reserve_unknown: dict | None = None,
):
    api = SimpleNamespace(
        risk_selected=risk_selected,
        risk_available=risk_available,
        execution_selected=exec_selected,
        execution_available=exec_available,
    )
    gw_cfg = SimpleNamespace(
        risk_selection=object() if risk_selected else None,
        execution_selection=object() if exec_selected else None,
    )
    proof = SimpleNamespace(monitor_stop_new_active=monitor_stop_new)
    store = SimpleNamespace(
        _gateway_mode=True,
        _gateway_start_attempted=started,
        _gateway_closed=closed,
        _gateway_composition_uncertain=composition_uncertain,
        is_connected=connected,
        gateway_strategy_config=gw_cfg,
        gateway_api=api,
        gateway_readiness_proof=proof,
        _data_feeds=[],
    )
    broker = SimpleNamespace(
        store=store,
        _run_binding=SimpleNamespace(mode="gateway", market_data_only=market_data_only),
        p=SimpleNamespace(market_data_only=market_data_only),
        orders=dict(orders or {}),
        _direct_active=lambda: False,
        _gateway_waiting_for_feed=waiting_feed,
        _gateway_waiting_for_session=waiting_session,
    )
    if stream_state is not None:
        broker._gateway_stream_binding = SimpleNamespace(
            state=stream_state,
            reserve_unknown=dict(reserve_unknown or {}),
        )
    return broker


def test_gateway_run_facts_healthy_active_broker():
    broker = _make_gateway_broker()
    facts = gateway_run_facts(broker)
    assert facts.write_block_reasons == ()
    assert facts.active_order_count == 0
    assert facts.unknown_unresolved_count == 0
    assert facts.last_error_code is None
    assert broker_run_facts(broker) == facts


def test_gateway_run_facts_unstarted_and_closed_stay_unknown():
    unstarted = _make_gateway_broker(started=False)
    assert gateway_run_facts(unstarted).write_block_reasons is None
    assert gateway_run_facts(unstarted).active_order_count is None
    assert gateway_run_facts(unstarted).unknown_unresolved_count is None

    closed = _make_gateway_broker(closed=True)
    assert gateway_run_facts(closed).write_block_reasons is None
    assert gateway_run_facts(closed).active_order_count is None


def test_gateway_run_facts_reports_real_block_reasons():
    waiting = _make_gateway_broker(stream_state=None, waiting_feed=True)
    assert gateway_run_facts(waiting).write_block_reasons == ("waiting_feed",)

    unbound = _make_gateway_broker(stream_state=None, waiting_feed=False)
    assert gateway_run_facts(unbound).write_block_reasons == ("stream_unbound",)

    degraded = _make_gateway_broker(
        connected=False,
        composition_uncertain=True,
        market_data_only=True,
        risk_available=False,
        exec_available=False,
        monitor_stop_new=True,
        stream_state="RISK_RECOVERY_PENDING",
    )
    assert gateway_run_facts(degraded).write_block_reasons == (
        "execution_unavailable",
        "gateway_composition_uncertain",
        "gateway_unavailable",
        "market_data_only",
        "monitor_stop_new_active",
        "risk_recovery_pending",
        "risk_unavailable",
    )


def test_gateway_run_facts_counts_active_and_unknown_orders():
    broker = _make_gateway_broker(
        orders={
            1: _FakeOrder(alive=True, info={}),
            2: _FakeOrder(alive=True, info={"execution_unknown": True}),
            3: _FakeOrder(alive=False, info={"cancel_execution_unknown": True}),
        },
        reserve_unknown={"req-1": 123.0},
    )
    facts = gateway_run_facts(broker)
    assert facts.write_block_reasons == ()
    assert facts.active_order_count == 2
    assert facts.unknown_unresolved_count == 3


def test_run_status_writer_publishes_empty_list_for_healthy_gateway_broker(tmp_path):
    strategy_dir = tmp_path / "gw_strategy"
    strategy_dir.mkdir()
    broker = _make_gateway_broker()
    writer = RunStatusWriter(
        strategy_dir,
        run_id=str(uuid.uuid4()),
        strategy_uuid=str(uuid.uuid4()),
        heartbeat_interval_s=0.05,
        broker=broker,
    )
    writer.start()
    try:
        doc = read_run_status(writer.path)
    finally:
        writer.stop_heartbeat()
    assert doc["write_block_reasons"] == []
    assert doc["active_order_count"] == 0
    assert doc["unknown_unresolved_count"] == 0
    assert doc["last_error_code"] is None
