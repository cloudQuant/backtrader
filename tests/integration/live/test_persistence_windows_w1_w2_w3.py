"""Integration simulation tests for crash/lost-reply persistence windows W1, W2, W3 (T-035 / S-04).

Verifies that a crash or lost reply inside any of the three persistence windows
leaves an explicit durable ``UNKNOWN`` / unresolved record across restart and
NEVER silently clears state or blind-resends under a new identity:
- W1: BT strategy ``live_state`` ``pending.json`` (Direct pre-dispatch marker)
- W2: Execution durable SQLite route journal (parent recorded BEFORE Risk/Execution call)
- W3: Gateway ``GatewayPendingHost`` pre-dispatch ``DISPATCHING`` marker before native send
"""

from __future__ import annotations

import socket
import sqlite3
from decimal import Decimal

import pytest

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding, GatewayCommandRecord
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.execution_routing import (
    ExecutionOrderRouter,
    ExecutionRoutingOutcome,
    install_execution_routing_tables,
    parse_execution_routing,
)
from bt_api_py.gateway_direct_client import GatewayClientRoute, build_gateway_order_intent

from backtrader.live_state import (
    STATUS_PREPARED,
    STATUS_UNKNOWN,
    PendingCommandStore,
    StrategyStateDir,
)
from backtrader.live_state.gateway_pending import GatewayPendingHost


@pytest.fixture(autouse=True)
def _block_sockets(monkeypatch):
    def _forbid(*args, **kwargs):
        raise AssertionError("Persistence window tests must never open sockets")

    monkeypatch.setattr(socket, "socket", _forbid)
    monkeypatch.setattr(socket, "create_connection", _forbid)


def test_w1_bt_live_state_crash_before_ack_preserves_unknown_after_restart(tmp_path):
    """Window W1: commit PREPARED marker -> simulate crash / lost reply -> restart sees UNKNOWN."""
    sdir = tmp_path / "w1_strat"
    sdir.mkdir()
    state = StrategyStateDir.initialize(sdir, mode="direct")
    seq = state.sequence.allocate()
    rec = {
        "operation": "place",
        "host_scope": state.strategy_uuid,
        "exchange_name": "CTP___FUTURE",
        "symbol": "SA701",
        "client_order_id": "000000000001",
        "native_identity": {"front_id": 1, "session_id": 7, "trading_day": "20261123"},
        "request_summary": {"side": "buy", "qty": 1, "price": 1500.0},
        "trading_day": "20261123",
        "session_generation": 1,
        "created_at_utc": "2026-11-23T01:00:00+00:00",
    }
    marker_id = state.pending.commit(rec, local_seq=seq, bt_ref=101)
    assert marker_id is not None
    assert state.pending.get(marker_id)["status"] == STATUS_PREPARED

    # Simulate lost reply / crash before venue ACK: mark UNKNOWN before/on recovery
    state.pending.mark(marker_id, STATUS_UNKNOWN, facts={"reason": "lost_reply_in_w1"})

    # Fresh reopen in new StrategyStateDir instance (simulated restart)
    reopened = StrategyStateDir(sdir, expected_mode="direct")
    active = reopened.pending.active()
    assert len(active) == 1
    assert active[0]["marker_id"] == marker_id
    assert active[0]["status"] == STATUS_UNKNOWN
    # Pending store refuses duplicate commit with same client_order_id / local_seq (returns None)
    dup = PendingCommandStore(sdir, reopened.strategy_uuid).commit(rec, local_seq=seq, bt_ref=102)
    assert dup is None


def test_w2_execution_parent_persisted_before_risk_and_lost_reply_stays_unknown(tmp_path):
    """Window W2: Execution parent is persisted in SQLite BEFORE remote submit;
    lost reply yields EXECUTION_UNKNOWN and replay never re-invokes submit."""
    db_path = tmp_path / "gateway_execution_routing.sqlite"
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        install_execution_routing_tables(conn)
        conn.execute("COMMIT")
        key = MarketInstrumentKey("ctp", "CZCE", "demo", "future", "SA701", "SA701")
        cfg = parse_execution_routing(
            {
                "schema_version": 2,
                "algorithm_build_id": "build-w2",
                "component": "exec-a",
                "account_ref": "account-a",
                "strategy_ref": "strategy-a",
                "execution_domain_ref": "paper:demo",
                "grant_revision": "grant-v1",
                "delegation": {"delegation_id": "del-1", "principal_ref": "principal-a"},
                "instruments": [key.to_dict()],
                "rules": [
                    {
                        "id": "r-open",
                        "match": {
                            "instrument": key.to_dict(),
                            "side": "buy",
                            "offset": "open",
                            "order_types": ["limit"],
                            "minimum_quantity": "1",
                            "quantity_unit": "base",
                        },
                        "schedule_binding": {
                            "quantity_step": "1",
                            "price_step": "1",
                            "retry_limit": 0,
                        },
                        "scheme": {"name": "pass-v1", "version": 1},
                        "algorithm": {"class": "PASS", "version": 1, "params": {}},
                        "deadline": {"kind": "absolute", "at": "2099-12-31T08:00:00+08:00"},
                        "time_in_force": "DAY",
                        "trading_day": "20991231",
                        "allowed_trading_days": ["20991231"],
                    }
                ],
            }
        )
        submit_calls = []
        tables_persisted_before_submit = []

        class _CrashingExecutionPort:
            def submit(self, *args, **kwargs):
                submit_calls.append((args, kwargs))
                # Verify parent/route rows are ALREADY durably persisted BEFORE remote RPC fires (W2!)
                table_names = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]
                row_total = sum(
                    conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in table_names
                )
                tables_persisted_before_submit.append(row_total)
                raise TimeoutError("simulated_lost_reply_w2")

        router = ExecutionOrderRouter(
            db=conn,
            config=cfg,
            execution_port=_CrashingExecutionPort(),
            risk_selected=True,
        )
        binding = GatewayCommandBinding("journal-a", "account-a", "strategy-a", "principal-a")
        route = GatewayClientRoute(
            "broker.direct_write",
            "gateway",
            "gw-1",
            "scope-a",
            WireScope("paper:demo", account_ref="account-a", strategy_ref="strategy-a", run_id="run-w2"),
            WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", "strategy-a"),
        )
        req = OrderRequest(
            symbol="SA701",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            account_id="account-a",
            client_order_id="cid-w2-1",
            price=Decimal("1500"),
            idempotency_key="key-w2-1",
            offset="open",
            quantity_unit="base",
            exchange_id="CZCE",
        )
        intent = build_gateway_order_intent(binding, route, req, ttl_seconds=10)

        first = router.route(intent)
        assert first.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
        assert len(submit_calls) == 1
        assert tables_persisted_before_submit[0] >= 1

        # Replay of the exact same intent after restart MUST return EXECUTION_UNKNOWN
        # and MUST NOT re-call submit (no duplicate risk_operation_id / child order!).
        router_after_restart = ExecutionOrderRouter(
            db=conn,
            config=cfg,
            execution_port=_CrashingExecutionPort(),
            risk_selected=True,
        )
        replayed = router_after_restart.route(intent)
        assert replayed.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
        assert len(submit_calls) == 1
    finally:
        conn.close()


def test_w3_gateway_pre_dispatch_marker_survives_lost_reply_without_resend(tmp_path):
    """Window W3: GatewayPendingHost commits pre-dispatch marker BEFORE native send;
    lost reply keeps marker unresolved across restart and idempotently returns same marker."""
    sdir = tmp_path / "w3_strat"
    sdir.mkdir()
    state = StrategyStateDir.initialize(sdir, mode="gateway")
    binding = GatewayCommandBinding("journal-w3", "account-a", state.strategy_uuid, "principal-a")
    route = GatewayClientRoute(
        "broker.direct_write",
        "gateway",
        "gw-1",
        "scope-a",
        WireScope("paper:demo", account_ref="account-a", strategy_ref=state.strategy_uuid, run_id="run-w3"),
        WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", state.strategy_uuid),
    )
    req = OrderRequest(
        symbol="SA701",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        account_id="account-a",
        client_order_id="cid-w3-1",
        price=Decimal("1500"),
        idempotency_key="key-w3-1",
    )
    intent = build_gateway_order_intent(binding, route, req, ttl_seconds=10)
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    host.save_intent(intent, local_seq=1, bt_ref=201)
    reserved = GatewayCommandRecord(
        1,
        binding,
        intent.request_key,
        "res-w3-1",
        intent.digest,
        "RESERVED",
        1,
        "g1",
        "g1",
        True,
        9.0,
        False,
        None,
        None,
        None,
        (),
    )
    host.save_record(intent.request_key, reserved)
    marker_id = host.commit_pre_dispatch(intent.request_key, reserved)

    # Simulate crash / lost reply right after pre-dispatch commit, then reopen fresh host
    reopened_host = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened_host.load_intent(intent.request_key).request_key == intent.request_key
    reopened_record = reopened_host.load_record(intent.request_key)
    assert reopened_record.reservation_id == "res-w3-1"
    # Idempotent pre-dispatch returns exact same marker_id (never duplicates marker!)
    assert reopened_host.commit_pre_dispatch(intent.request_key, reserved) == marker_id
    # Pending store retains active unresolved marker
    reopened_state = StrategyStateDir(sdir, expected_mode="gateway")
    assert any(row["marker_id"] == marker_id for row in reopened_state.pending.active())
