"""Offline managed projection coverage for both order sides and position closes."""

from __future__ import annotations

import socket
from decimal import Decimal

import pytest

from tests.unit.brokers import test_btapibroker_managed_execution_projection as projection


def test_fraction_projection_preserves_sell_sign_and_reverse_closes_positions_offline(
    tmp_path, monkeypatch
) -> None:
    def deny_network(*_args, **_kwargs):
        raise AssertionError("managed projection side coverage must remain offline")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)

    runtime = projection._ProjectionEventRuntime(tmp_path)
    provider = projection._ResponseProvider(
        [{"status": "accepted", "id": f"provider.side-fixture.{index}"} for index in range(1, 6)]
    )
    bridge = projection.ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=projection._cumulative_provider_observation,
    )
    _store, data, broker = projection._make_started_stack(
        runtime, provider, managed_execution_adapter=bridge
    )

    def submit(side: str, size: int, intent_id: str, effect: str):
        info = projection._managed_info(intent_id)
        info["managed_position_effect"] = effect
        info["offset"] = "open" if effect == "OPEN" else "close"
        info["reduce_only"] = effect != "OPEN"
        submit_order = broker.buy if side == "BUY" else broker.sell
        return submit_order(
            owner=None,
            data=data,
            size=size,
            price=110.0,
            exectype=projection.bt.Order.Limit,
            **info,
        )

    def project(order, intent_id: str, provider_order_id: str, facts) -> None:
        for state, quantity, average, commission in facts:
            runtime._record_provider_event(
                projection._CumulativeProviderObservation(
                    intent_id=intent_id,
                    state=state,
                    provider_order_id=provider_order_id,
                    filled_quantity=Decimal(quantity),
                    average_price=Decimal(average),
                    cumulative_commission=Decimal(commission),
                )
            )
            broker._drain_store_updates()
            assert order.info.get("execution_unknown") is not True
            assert not order.info.get("ledger_mismatch")

    try:
        buy_open = submit("BUY", 2, "intent.side.buy-open", "OPEN")
        project(
            buy_open,
            "intent.side.buy-open",
            "provider.side-fixture.1",
            [(projection._ExecutionState.FILLED, "2", "100", "0.03")],
        )
        assert buy_open.status == projection.bt.Order.Completed
        assert buy_open.executed.size == pytest.approx(2.0)
        assert broker.positions[projection.DEFAULT_SYMBOL].size == pytest.approx(2.0)

        sell_close_long = submit("SELL", 2, "intent.side.sell-close-long", "CLOSE")
        project(
            sell_close_long,
            "intent.side.sell-close-long",
            "provider.side-fixture.2",
            [
                (projection._ExecutionState.PARTIALLY_FILLED, "1", "100", "0.02"),
                (projection._ExecutionState.FILLED, "2", "100.5", "0.01"),
            ],
        )
        assert sell_close_long.status == projection.bt.Order.Completed
        assert sell_close_long.executed.size == pytest.approx(-2.0)
        assert [(bit.size, bit.price, bit.comm) for bit in sell_close_long.executed.exbits] == [
            (-1.0, 100.0, 0.02),
            (-1.0, 101.0, -0.01),
        ]
        assert sell_close_long.executed.comm == pytest.approx(0.01)
        assert broker.positions[projection.DEFAULT_SYMBOL].size == pytest.approx(0.0)

        sell_open_short = submit("SELL", 2, "intent.side.sell-open-short", "OPEN")
        project(
            sell_open_short,
            "intent.side.sell-open-short",
            "provider.side-fixture.3",
            [
                (projection._ExecutionState.PARTIALLY_FILLED, "1", "102", "0.03"),
                (projection._ExecutionState.FILLED, "2", "101.5", "0.02"),
            ],
        )
        assert sell_open_short.status == projection.bt.Order.Completed
        assert sell_open_short.executed.size == pytest.approx(-2.0)
        assert [(bit.size, bit.price, bit.comm) for bit in sell_open_short.executed.exbits] == [
            (-1.0, 102.0, 0.03),
            (-1.0, 101.0, -0.01),
        ]
        assert sell_open_short.executed.comm == pytest.approx(0.02)
        assert broker.positions[projection.DEFAULT_SYMBOL].size == pytest.approx(-2.0)

        buy_close_short = submit("BUY", 2, "intent.side.buy-close-short", "CLOSE")
        project(
            buy_close_short,
            "intent.side.buy-close-short",
            "provider.side-fixture.4",
            [
                (projection._ExecutionState.PARTIALLY_FILLED, "1", "99", "0.01"),
                (projection._ExecutionState.FILLED, "2", "98", "0.005"),
            ],
        )
        assert buy_close_short.status == projection.bt.Order.Completed
        assert buy_close_short.executed.size == pytest.approx(2.0)
        assert [(bit.size, bit.price, bit.comm) for bit in buy_close_short.executed.exbits] == [
            (1.0, 99.0, 0.01),
            (1.0, 97.0, -0.005),
        ]
        assert buy_close_short.executed.comm == pytest.approx(0.005)
        assert broker.positions[projection.DEFAULT_SYMBOL].size == pytest.approx(0.0)

        journal = bridge._framework_projection_journal
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 7
        )
        assert bridge._source_projection_blocked is False
        assert getattr(broker, "_managed_provider_projection_failed", False) is False

        next_order = submit("BUY", 1, "intent.side.after-close", "OPEN")
        runtime._record_provider_event(
            projection._CumulativeProviderObservation(
                intent_id="intent.side.after-close",
                state=projection._ExecutionState.ACKED,
                provider_order_id="provider.side-fixture.5",
                filled_quantity=Decimal("0"),
                average_price=None,
                cumulative_commission=Decimal("0"),
            )
        )
        broker._drain_store_updates()
        assert next_order.status == projection.bt.Order.Accepted
        assert next_order.executed.size == pytest.approx(0.0)
        assert len(provider.submitted_orders) == 5
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 8
        )
        assert bridge._source_projection_blocked is False
        assert getattr(broker, "_managed_provider_projection_failed", False) is False
    finally:
        broker.stop()
        bridge.close()
