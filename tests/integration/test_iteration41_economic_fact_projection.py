"""Fake-provider acceptance for durable cumulative execution quality facts.

The execution and monitor packages are independent products. This integration
test runs when both packages are available on ``PYTHONPATH`` and remains
skipped in the base Backtrader install, where they are optional dependencies.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

execution = pytest.importorskip("bt_api_execution")
monitor = pytest.importorskip("bt_api_monitor")

from backtrader_runtime.economic_fact_projection import pump_execution_quality


def test_durable_cumulative_events_project_and_replay_without_summing(tmp_path):
    scope = execution.ExecutionScope(
        "SIM", "simulation", "local-account-ref", "strategy.alpha", "20260926"
    )
    store = execution.SqliteExecutionStore(tmp_path / "execution.sqlite3")
    facade = execution.ManagedExecutionFacade(
        store, scope, writer_id="fake-projector", allow_unprotected=True
    )
    read_model = monitor.EconomicFactReadModel(monitor.DurableOutbox(tmp_path / "monitor.sqlite3"))
    intent = execution.OrderIntent.limit(
        intent_id="intent-1",
        scope=scope,
        signal_id="signal-1",
        instrument="XYZ.TEST",
        side=execution.Side.BUY,
        quantity=Decimal("2"),
        price=Decimal("100"),
        metadata_version="fake-v1",
    )
    try:
        facade.submit(
            intent,
            lambda value: execution.ProviderObservation.accepted(
                value.intent_id, "provider-order-1"
            ),
        )
        facade.record_provider_observation(
            execution.ProviderObservation(
                "intent-1",
                execution.ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider-order-1",
                filled_quantity=Decimal("0.5"),
                average_price=Decimal("100"),
            )
        )

        first_partial = next(
            event for event in store.read_outbox() if event.event_type == "reconciled_observation"
        )
        old_payload = dict(first_partial.payload)
        old_payload.pop("average_price")
        store._connection.execute(
            "UPDATE execution_outbox SET payload_json = ? WHERE sequence = ?",
            (
                json.dumps(old_payload, separators=(",", ":"), sort_keys=True),
                first_partial.sequence,
            ),
        )

        fee_completion = facade.record_provider_observation_event(
            execution.ProviderObservation(
                "intent-1",
                execution.ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider-order-1",
                filled_quantity=Decimal("0.5"),
                average_price=Decimal("100"),
                cumulative_commission=Decimal("0.10"),
            )
        )
        assert fee_completion is not None
        second_partial = facade.record_provider_observation_event(
            execution.ProviderObservation(
                "intent-1",
                execution.ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider-order-1",
                filled_quantity=Decimal("1"),
                average_price=Decimal("101"),
                cumulative_commission=Decimal("0.15"),
            )
        )
        filled = facade.record_provider_observation_event(
            execution.ProviderObservation(
                "intent-1",
                execution.ExecutionState.FILLED,
                provider_order_id="provider-order-1",
                filled_quantity=Decimal("2"),
                average_price=Decimal("102"),
                cumulative_commission=Decimal("0.20"),
            )
        )
        assert second_partial is not None and filled is not None

        batch = pump_execution_quality(store, read_model, scope, limit=100)
        assert batch.published == 4
        assert batch.skipped_without_fill == 1
        identity = store.journal_source_identity()
        wire_scope = {
            "provider": scope.provider,
            "environment": scope.environment,
            "account_fingerprint": scope.account_key.partition(":")[2],
            "generation_kind": identity["generation_kind"],
            "generation": identity["generation"],
            "trading_day": scope.trading_day,
            "epoch": identity["epoch"],
            "strategy_id": scope.strategy_id,
        }
        page = read_model.read_execution_quality(wire_scope, limit=20)
        assert len(page.records) == 4
        facts = [record.fact for record in page.records]
        execution_values = [fact["execution"] for fact in facts]
        assert [fact["completeness"] for fact in facts] == ["INCOMPLETE"] * 4
        assert [value["native_quantity"] for value in execution_values] == [
            "0.5",
            "0.5",
            "1",
            "2",
        ]
        assert [value["fee"] for value in execution_values] == [None, "0.10", "0.15", "0.20"]
        assert [value["native_quantity_basis"] for value in execution_values] == [
            "ORDER_CUMULATIVE"
        ] * 4
        assert [value["fee_basis"] for value in execution_values] == [
            None,
            "ORDER_CUMULATIVE",
            "ORDER_CUMULATIVE",
            "ORDER_CUMULATIVE",
        ]
        assert execution_values[0]["vwap"] is None
        assert execution_values[0]["vwap_basis"] is None
        for fact in facts:
            assert fact["arrival"]["bid"] is None
            assert fact["arrival"]["ask"] is None
            assert fact["arrival"]["mid"] is None
            assert fact["execution"]["fee_currency"] is None
            assert fact["execution"]["contract_multiplier"] is None
            assert fact["execution"]["stage_durations_ns"] == {}
            assert fact["lineage"]["trade_id"] is None
            assert "local-account-ref" not in repr(fact)

        replay = pump_execution_quality(store, read_model, scope, after_sequence=0, limit=100)
        assert replay.published == 4
        assert len(read_model.read_execution_quality(wire_scope, limit=20).records) == 4
        latest = max(page.records, key=lambda record: record.sequence).fact["execution"]
        assert latest["native_quantity"] == "2"
        assert latest["fee"] == "0.20"
        assert sum(Decimal(value["native_quantity"]) for value in execution_values) == Decimal("4")
        assert sum(Decimal(value["fee"]) for value in execution_values if value["fee"]) == Decimal(
            "0.45"
        )
        assert latest["native_quantity"] != "4"
        assert latest["fee"] != "0.45"
    finally:
        facade.close()
        store.close()
