from datetime import datetime, timezone
from decimal import Decimal
from importlib import import_module

import pytest

from bt_api_py.cross_venue import (
    CrossVenueLeg as InstrumentRule,
    CrossVenueValueError as CrossExchangeValueError,
    InsufficientDepth,
    aggregate_confirmed_fills,
    coerce_funding_snapshot,
    executable_vwap,
    funding_settlement_count,
    quantity_lattice,
    realized_round_trip_economics,
    round_trip_cost,
    signed_funding_cashflow,
)

D = Decimal


def test_typed_funding_state_requires_fresh_future_complete_schedule():
    now = D("1700000000")
    value = {
        "available": True,
        "exchange_name": "OKX___SWAP",
        "symbol": "BTC-USDT-SWAP",
        "rate": D("0.0001"),
        "next_funding_time": datetime.fromtimestamp(float(now + 60), tz=timezone.utc),
        "settlement_interval_seconds": 28800,
        "source": "exchange",
        "freshness": {
            "observed_at": datetime.fromtimestamp(float(now - 1), tz=timezone.utc),
            "source": "exchange",
            "stale": False,
        },
        "cache_age_seconds": D("1.25"),
    }

    state = coerce_funding_snapshot(value, now_epoch=now)

    assert state.rate == D("0.0001")
    assert state.next_funding_epoch == now + 60
    assert state.settlement_interval_seconds == 28800

    for change, reason in (
        (
            {"available": False, "unavailable_reason": "funding_unavailable"},
            "funding_unavailable",
        ),
        ({"next_funding_time": datetime.fromtimestamp(float(now), tz=timezone.utc)}, "expired"),
        ({"settlement_interval_seconds": 0}, "interval"),
        (
            {
                "freshness": {
                    "observed_at": datetime.fromtimestamp(float(now - 1), tz=timezone.utc),
                    "source": "exchange",
                    "stale": True,
                }
            },
            "stale",
        ),
    ):
        invalid = {**value, **change}
        with pytest.raises(CrossExchangeValueError, match=reason):
            coerce_funding_snapshot(invalid, now_epoch=now)


def _rule(multiplier, step, minimum):
    return InstrumentRule(
        multiplier=D(multiplier),
        quantity_step=D(step),
        minimum_quantity=D(minimum),
        minimum_notional=D("0"),
        price_tick=D("0.1"),
        taker_fee=D("0.001"),
    )


def _mid_cost_qualification(module, venue_rules, risk, direction=("okx", "binance")):
    """Build a provenance-complete zero-exit-basis model for cost-oracle tests."""
    return module.BasisModelQualification(
        basis_series_sha256="a" * 64,
        method=module.QUALIFICATION_METHOD,
        sample_count=risk.minimum_qualification_samples,
        lag1_coefficient=D("0.5"),
        ar1_intercept=D("0"),
        equilibrium_basis=D("0"),
        equilibrium_upper_confidence=D("0"),
        half_life_seconds=D("1"),
        maximum_half_life_seconds=risk.maximum_half_life_seconds,
        qualified=True,
        valid_from_epoch=D("0"),
        valid_until_epoch=D("99999999999"),
        source_data_sha256="b" * 64,
        provenance="unit-test-cost-oracle",
        sample_interval_seconds=D("1"),
        lag1_upper_confidence=D("0.6"),
        unit_root_pvalue=D("0"),
        bootstrap_replications=module.QUALIFICATION_BOOTSTRAP_REPLICATIONS,
        basis_definition=module.BASIS_DEFINITION,
        venue_symbols_sha256=module._venue_symbols_sha256(),
        qualification_contract_sha256=module.qualification_contract_sha256(
            venue_rules, risk, *direction
        ),
        buy_venue=direction[0],
        sell_venue=direction[1],
    )


def test_common_quantity_lattice_respects_both_native_contract_steps():
    lattice = quantity_lattice(D("0.037"), [_rule("0.01", "1", "1"), _rule("1", ".001", ".001")])

    assert lattice.common_step_base == D("0.01")
    assert lattice.quantity_base == D("0.03")
    assert lattice.minimum_base == D("0.01")
    assert lattice.tradable is True


def test_executable_vwap_consumes_multiple_levels_and_rejects_short_depth():
    result = executable_vwap((("100", "1"), ("102", "1")), D("2"), "buy")

    assert result.price == D("101")
    assert result.notional == D("202")
    assert result.depth_impact == D("2")
    assert result.levels_consumed == 2
    assert result.marginal_price == D("102")
    sell = executable_vwap((("110", "1"), ("108", "1")), D("2"), "sell")
    assert sell.price == D("109")
    assert sell.marginal_price == D("108")
    with pytest.raises(InsufficientDepth):
        executable_vwap((("100", "1"),), D("2"), "buy")


def test_confirmed_fill_aggregation_preserves_decimal_actual_notional():
    result = aggregate_confirmed_fills(
        (("100.1", ".004"), ("100.2", ".006")),
        side="buy",
        expected_quantity_base=D(".01"),
    )

    assert result.quantity_base == D(".01")
    assert result.notional == D("1.0016")
    assert result.price == D("100.16")
    with pytest.raises(CrossExchangeValueError, match="expected quantity"):
        aggregate_confirmed_fills(
            (("100.1", ".004"),),
            side="buy",
            expected_quantity_base=D(".01"),
        )


def test_round_trip_ledger_counts_four_fees_and_does_not_double_count_entry_impact():
    buy = executable_vwap((("100", "1"), ("102", "1")), D("2"), "buy")
    sell = executable_vwap((("110", "1"), ("108", "1")), D("2"), "sell")

    result = round_trip_cost(
        quantity_base=D("2"),
        entry_buy=buy,
        entry_sell=sell,
        buy_fee_rate=D("0.001"),
        sell_fee_rate=D("0.002"),
        expected_exit_basis=D("0"),
        expected_exit_buy_price=D("107"),
        expected_exit_sell_price=D("103"),
        expected_exit_execution_cost=D("0.5"),
        signed_funding=D("-0.1"),
        latency_reserve=D("0.2"),
        failure_reserve=D("0.3"),
        model_buffer=D("0.4"),
    )

    assert result.entry_executable_edge == D("16")
    assert result.expected_exit_basis_notional == D("0")
    assert result.expected_gross_convergence == D("16")
    assert result.entry_fees == D("0.638")
    assert result.predicted_exit_fees == D("0.634")
    assert result.entry_buy_depth_impact_audit == D("2")
    assert result.entry_sell_depth_impact_audit == D("2")
    assert result.total_cost == D("2.772")
    assert result.expected_net == D("13.228")
    result.assert_conserved()


def test_round_trip_ledger_only_counts_convergence_beyond_persistent_basis():
    buy = executable_vwap((("100", "2"),), D("2"), "buy")
    sell = executable_vwap((("111", "2"),), D("2"), "sell")

    result = round_trip_cost(
        quantity_base=D("2"),
        entry_buy=buy,
        entry_sell=sell,
        buy_fee_rate=D("0"),
        sell_fee_rate=D("0"),
        expected_exit_basis=D("10"),
        expected_exit_buy_price=D("110"),
        expected_exit_sell_price=D("100"),
        expected_exit_execution_cost=D("0"),
    )

    assert result.entry_executable_edge == D("22")
    assert result.expected_exit_basis_notional == D("20")
    assert result.expected_gross_convergence == D("2")
    assert result.expected_net == D("2")
    result.assert_conserved()


def test_realized_economics_uses_four_actual_fills_without_forecast_exit_reserve():
    entry_buy = executable_vwap((("100", "1"), ("102", "1")), D("2"), "buy")
    entry_sell = executable_vwap((("110", "1"), ("108", "1")), D("2"), "sell")
    exit_sell = executable_vwap((("104", "1"), ("102", "1")), D("2"), "sell")
    exit_buy = executable_vwap((("106", "1"), ("108", "1")), D("2"), "buy")

    result = realized_round_trip_economics(
        quantity_base=D("2"),
        entry_buy=entry_buy,
        entry_sell=entry_sell,
        exit_sell=exit_sell,
        exit_buy=exit_buy,
        buy_venue_fee_rate=D("0.001"),
        sell_venue_fee_rate=D("0.002"),
        entry_fees_paid=D("0.7"),
        exit_fees_paid=D("0.8"),
        signed_funding=D("0.1"),
        latency_reserve=D("0.2"),
        failure_reserve=D("0.3"),
        model_buffer=D("0.4"),
    )

    assert result.entry_executable_edge == D("16")
    assert result.exit_executable_edge == D("-8")
    assert result.gross_pnl == D("8")
    assert result.realized_net == D("6.6")
    assert result.total_preview_reserve == D("0.9")
    assert result.risk_adjusted_net == D("5.7")
    result.assert_conserved()


def test_realized_economics_rejects_wrong_side_or_quantity():
    buy_one = executable_vwap((("100", "1"),), D("1"), "buy")
    sell_one = executable_vwap((("101", "1"),), D("1"), "sell")
    buy_two = executable_vwap((("100", "2"),), D("2"), "buy")

    with pytest.raises(CrossExchangeValueError, match="quantities"):
        realized_round_trip_economics(
            quantity_base=D("1"),
            entry_buy=buy_two,
            entry_sell=sell_one,
            exit_sell=sell_one,
            exit_buy=buy_one,
            buy_venue_fee_rate=0,
            sell_venue_fee_rate=0,
        )
    with pytest.raises(CrossExchangeValueError, match="entry VWAP sides"):
        realized_round_trip_economics(
            quantity_base=D("1"),
            entry_buy=sell_one,
            entry_sell=sell_one,
            exit_sell=sell_one,
            exit_buy=buy_one,
            buy_venue_fee_rate=0,
            sell_venue_fee_rate=0,
        )


def test_signed_funding_uses_side_and_exact_settlement_count():
    assert funding_settlement_count(D("100"), D("110"), D("31"), D("10")) == 3
    assert funding_settlement_count(D("125"), D("110"), D("16"), D("10")) == 2
    assert signed_funding_cashflow(D("1000"), D("0.001"), "long", 3) == D("-3")
    assert signed_funding_cashflow(D("1000"), D("0.001"), "short", 3) == D("3")


def test_ac_cost_001_both_strategies_call_same_oracle_for_same_fixture():
    mid = import_module("examples.012_1_midfreq_cross_exchange.strategy")
    hft = import_module("examples.012_2_event_driven_cross_exchange.strategy")
    venue_rules = {
        "okx": _rule(".01", "1", "1"),
        "binance": _rule("1", ".001", ".001"),
    }
    shared_reserves = {
        "exit_reserve_bps": D("2"),
        "latency_reserve_bps": D("1"),
        "failure_reserve_bps": D("2"),
        "model_buffer_bps": D("3"),
    }
    mid_risk = mid.MidFrequencyRisk(
        zscore_window=3,
        minimum_samples=3,
        **shared_reserves,
    )
    mid_engine = mid.MidFrequencyEngine(
        venue_rules,
        mid_risk,
        {("okx", "binance"): _mid_cost_qualification(mid, venue_rules, mid_risk)},
    )
    hft_engine = hft.EventArbitrageEngine(
        venue_rules,
        hft.EventDrivenRisk(**shared_reserves),
    )
    mid_engine.update_book(
        mid.BookState(
            "okx",
            ((D("59999"), D(".1")),),
            ((D("60000"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    mid_engine.update_book(
        mid.BookState(
            "binance",
            ((D("60400"), D(".1")),),
            ((D("60401"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    hft_engine.update_book(
        hft.EventBook(
            "okx",
            ((D("59999"), D(".1")),),
            ((D("60000"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    hft_engine.update_book(
        hft.EventBook(
            "binance",
            ((D("60400"), D(".1")),),
            ((D("60401"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )

    mid_engine._candidate("okx", "binance", D("1"))
    _quantity, _buy, _sell, _exit_sell, _exit_buy, hft_cost = hft_engine._cost(
        "okx", "binance", D("1")
    )

    assert mid_engine.cost_history[-1].as_dict() == hft_cost.as_dict()


def test_strategy_exit_cost_counts_only_projected_exit_half_spread_and_depth():
    mid = import_module("examples.012_1_midfreq_cross_exchange.strategy")
    event = import_module("examples.012_2_event_driven_cross_exchange.strategy")
    venue_rules = {
        "okx": _rule(".01", "1", "1"),
        "binance": _rule("1", ".001", ".001"),
    }
    mid_risk = mid.MidFrequencyRisk(
        zscore_window=3,
        minimum_samples=3,
        depth_fraction=D("1"),
        exit_reserve_bps=D("0"),
        latency_reserve_bps=D("0"),
        failure_reserve_bps=D("0"),
        model_buffer_bps=D("0"),
    )
    event_risk = event.EventDrivenRisk(
        depth_fraction=D("1"),
        exit_reserve_bps=D("0"),
        latency_reserve_bps=D("0"),
        failure_reserve_bps=D("0"),
        model_buffer_bps=D("0"),
        minimum_markout_samples=D("0"),
    )
    mid_engine = mid.MidFrequencyEngine(
        venue_rules,
        mid_risk,
        {("okx", "binance"): _mid_cost_qualification(mid, venue_rules, mid_risk)},
    )
    event_engine = event.EventArbitrageEngine(venue_rules, event_risk)
    mid_engine.update_book(
        mid.BookState(
            "okx",
            ((D("99"), D(".1")),),
            ((D("100"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    mid_engine.update_book(
        mid.BookState(
            "binance",
            ((D("101"), D(".1")),),
            ((D("102"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    event_engine.update_book(
        event.EventBook(
            "okx",
            ((D("99"), D(".1")),),
            ((D("100"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    event_engine.update_book(
        event.EventBook(
            "binance",
            ((D("101"), D(".1")),),
            ((D("102"), D(".1")),),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )

    mid_engine._candidate("okx", "binance", D("1"))
    *_, event_cost = event_engine._cost("okx", "binance", D("1"))

    # 0.01 BTC pays 0.5 quote/BTC half-spread at each venue: 0.005 + 0.005.
    assert mid_engine.cost_history[-1].expected_exit_execution_cost == D(".01")
    assert event_cost.expected_exit_execution_cost == D(".01")
