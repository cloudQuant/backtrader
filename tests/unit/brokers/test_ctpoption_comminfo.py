"""Regression tests for explicit CTP premium style option accounting."""

import datetime as dt
import math

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.commissions.ctpoption import (
    CtpOptionPremium,
    OptionAccountingError,
)
from backtrader.position import Position
from tests.fixtures.fake_btapi import FakeBtApiClient, make_bar, make_store


def _seller_evidence(**overrides):
    evidence = {
        "source_kind": "synthetic",
        "account_fingerprint": "offline-account",
        "trading_day": "20260910",
        "connection_generation": 7,
        "instrument_id": "OPT-C-20261231-1000",
        "exchange_id": "CZCE",
        "hedge_flag": "1",
        "currency": "CNY",
        "price_basis": {
            "option_price": 20.0,
            "underlying_price": 1000.0,
            "as_of_utc": "2026-09-10T00:00:00+00:00",
            "source_hash": "a" * 64,
        },
        "expiry": "20261231",
        "source_hash": "a" * 64,
        "expires_at_utc": "2099-01-01T00:00:00Z",
        "quantity": 1,
        "total_margin": 3500.0,
    }
    evidence.update(overrides)
    return evidence


def _option(**overrides):
    params = {
        "mult": 10.0,
        "premium_style": "premium",
        "option_type": "call",
        "open_commission_by_money": 0.0001,
        "open_commission_by_volume": 3.0,
        "close_commission_by_money": 0.0001,
        "close_commission_by_volume": 3.0,
        "close_today_commission_by_money": 0.0001,
        "close_today_commission_by_volume": 3.0,
        "seller_margin_evidence": _seller_evidence(),
    }
    params.update(overrides)
    return CtpOptionPremium(**params)


def _broker_stack(*, cash, metadata, broker_kwargs=None, supports_dual_side=False):
    symbol = metadata["instrument_id"]
    client = FakeBtApiClient(
        balance={"cash": cash, "value": cash},
        history={symbol: [make_bar(0, 20.0, 20.0, 20.0, 20.0)]},
    )
    store = make_store(
        api=client,
        contract_metadata={symbol: metadata},
        supports_dual_side=supports_dual_side,
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(**(broker_kwargs or {}))
    data._start()
    assert data.load() is True
    broker.start()
    return client, store, data, broker


def _option_metadata(**overrides):
    metadata = {
        "asset_type": "option",
        "premium_style": "premium",
        "option_type": "call",
        "instrument_id": "OPT-C-20261231-1000",
        "exchange_id": "CZCE",
        "multiplier": 10.0,
        "price_tick": 1.0,
        "open_fee_rate": 0.0001,
        "open_fee_amount": 3.0,
        "close_fee_rate": 0.0001,
        "close_fee_amount": 3.0,
        "close_today_fee_rate": 0.0001,
        "close_today_fee_amount": 3.0,
        "seller_margin_evidence": _seller_evidence(),
        "account_fingerprint": "offline-account",
        "trading_day": "20260910",
        "connection_generation": 7,
        "hedge_flag": "1",
        "currency": "CNY",
        "expiry": "20261231",
    }
    metadata.update(overrides)
    return metadata


def test_buyer_premium_has_signed_value_linear_pnl_and_no_cash_adjustment():
    comminfo = _option()

    assert comminfo.getoperationcost(1, 20.0, is_buy=True) == pytest.approx(200.0)
    assert comminfo.getoperationcost(2, 20.0, is_buy=True) == pytest.approx(400.0)
    assert comminfo.getvaluesize(1, 25.0) == pytest.approx(250.0)
    assert comminfo.profitandloss(1, 20.0, 25.0) == pytest.approx(50.0)
    assert comminfo.profitandloss(2, 20.0, 25.0) == pytest.approx(100.0)
    assert comminfo.cashadjust(1, 20.0, 25.0) == pytest.approx(0.0)
    assert comminfo.getcommission(1, 20.0, role="open") == pytest.approx(3.02)
    assert comminfo.getcommission(1, 20.0, role="close") == pytest.approx(3.02)
    assert comminfo.getcommission(1, 20.0, role="close_today") == pytest.approx(3.02)


def test_seller_requires_complete_explicit_margin_evidence_and_scales_quantity():
    comminfo = _option()

    assert comminfo.getoperationcost(1, 20.0, is_buy=False) == pytest.approx(3500.0)
    seller_projection = comminfo.accounting_projection(1, 20.0, is_buy=False)
    assert seller_projection["premium_cashflow"] == pytest.approx(200.0)
    assert seller_projection["cashflow"] == pytest.approx(196.98)
    assert seller_projection["margin"] == pytest.approx(3500.0)
    approved_two_lot = _option(
        seller_margin_evidence=_seller_evidence(quantity=2, total_margin=7000.0)
    )
    assert approved_two_lot.getoperationcost(2, 20.0, is_buy=False) == pytest.approx(7000.0)
    with pytest.raises(OptionAccountingError):
        comminfo.getoperationcost(2, 20.0, is_buy=False)

    for overrides in (
        {"total_margin": None},
        {"account_fingerprint": None},
        {"price_basis": {"option_price": 0.0, "underlying_price": 0.0}},
        {"expires_at_utc": "2000-01-01T00:00:00Z"},
    ):
        with pytest.raises(OptionAccountingError):
            _option(seller_margin_evidence=_seller_evidence(**overrides)).getoperationcost(
                1, 20.0, is_buy=False
            )


def test_option_fees_distinguish_missing_components_from_explicit_zero():
    zero = _option(
        open_commission_by_money=0.0,
        open_commission_by_volume=0.0,
    )
    assert zero.getcommission(1, 20.0, role="open") == pytest.approx(0.0)

    missing = _option(
        open_commission_by_money=None,
        open_commission_by_volume=None,
    )
    with pytest.raises(OptionAccountingError):
        missing.getcommission(1, 20.0, role="open")


def test_broker_materializes_option_comminfo_and_preserves_buy_sell_cash_routes():
    metadata = _option_metadata()
    client, store, data, broker = _broker_stack(cash=4000.0, metadata=metadata)
    try:
        comminfo = broker.getcommissioninfo(data)
        assert isinstance(comminfo, CtpOptionPremium)

        buy_order = broker.buy(owner=None, data=data, size=1, price=20.0)
        assert buy_order.status == bt.Order.Accepted
        assert client.submitted_orders[0]["side"] == "buy"

        # The live cash snapshot remains authoritative; submitting a premium
        # order must not create a second local cash ledger.
        assert broker.getcash() == pytest.approx(4000.0)
    finally:
        broker.stop()

    client, store, data, broker = _broker_stack(cash=3503.02, metadata=metadata)
    try:
        sell_order = broker.sell(owner=None, data=data, size=1, price=20.0)
        assert sell_order.status == bt.Order.Rejected
        assert sell_order.info["error_code"] == "option_seller_margin_blocked"
        assert client.submitted_orders == []
    finally:
        broker.stop()

    # Keep a strong reference during the first stack teardown for debuggers.
    assert store is not None


def test_broker_rejects_cash_below_buyer_premium_or_seller_margin():
    metadata = _option_metadata()
    client, store, data, broker = _broker_stack(cash=203.01, metadata=metadata)
    try:
        order = broker.buy(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "insufficient_cash"
        assert client.submitted_orders == []
    finally:
        broker.stop()

    client, store, data, broker = _broker_stack(cash=3503.01, metadata=metadata)
    try:
        order = broker.sell(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "option_seller_margin_blocked"
        assert client.submitted_orders == []
    finally:
        broker.stop()

    assert store is not None


def test_metadata_without_explicit_option_style_does_not_silently_become_futures():
    metadata = _option_metadata(premium_style=None)
    with pytest.raises((OptionAccountingError, ValueError)):
        BtApiBroker._metadata_to_comminfo(metadata)


def test_expired_evidence_is_rejected_even_if_margin_is_positive():
    comminfo = _option(
        seller_margin_evidence=_seller_evidence(
            expires_at_utc=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        )
    )
    with pytest.raises(OptionAccountingError):
        comminfo.getoperationcost(1, 20.0, is_buy=False)


def test_seller_evidence_rejects_unknown_provenance_and_cross_scope():
    with pytest.raises(OptionAccountingError):
        _option(
            seller_margin_evidence=_seller_evidence(source_kind="reference_only")
        ).getoperationcost(1, 20.0, is_buy=False)

    with pytest.raises(OptionAccountingError):
        _option(
            evidence_scope={"account_fingerprint": "another-account"},
        ).getoperationcost(1, 20.0, is_buy=False)

    with pytest.raises(OptionAccountingError, match="instrument_id_alias_conflict"):
        _option(
            evidence_scope={
                "instrument_id": "m2701",
                "InstrumentID": "M2701",
            },
        ).getoperationcost(1, 20.0, is_buy=False)


def test_broker_blocks_synthetic_seller_evidence_in_live_path():
    metadata = _option_metadata()
    client, store, data, broker = _broker_stack(cash=4000.0, metadata=metadata)
    try:
        order = broker.sell(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "option_seller_margin_blocked"
        assert client.submitted_orders == []
    finally:
        broker.stop()

    assert store is not None


def test_broker_rejects_missing_option_fee_dimension_without_zero_default():
    metadata = _option_metadata(open_fee_amount=None)
    client, store, data, broker = _broker_stack(cash=4000.0, metadata=metadata)
    try:
        order = broker.buy(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "option_fee_open_incomplete"
        assert client.submitted_orders == []
    finally:
        broker.stop()

    # The mandatory option fee gate remains active when the optional cash
    # check is disabled, and an explicit open must use the open fee pair.
    metadata = _option_metadata(open_fee_rate=None, open_fee_amount=None)
    client, store, data, broker = _broker_stack(
        cash=4000.0,
        metadata=metadata,
        broker_kwargs={"cash_check_enabled": False},
    )
    try:
        order = broker.buy(owner=None, data=data, size=1, price=20.0, offset="open")
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "option_fee_open_incomplete"
        assert client.submitted_orders == []
    finally:
        broker.stop()

    metadata = _option_metadata(close_fee_rate=None, close_fee_amount=None)
    client, store, data, broker = _broker_stack(
        cash=4000.0,
        metadata=metadata,
        broker_kwargs={"cash_check_enabled": False},
    )
    try:
        order = broker.buy(owner=None, data=data, size=1, price=20.0, offset="open")
        assert order.status == bt.Order.Accepted
        assert len(client.submitted_orders) == 1

        # The exact resolver rejects an unknown role instead of silently
        # converting it to a close fee check.
        order.addinfo(offset="mystery")
        error = broker._validate_option_order_fee(order)
        assert error[0] == "option_offset_unknown"
    finally:
        broker.stop()

    assert store is not None


def test_broker_keeps_seller_capability_blocked_until_trusted_sdk_issuer_exists():
    metadata = _option_metadata()
    client, store, data, broker = _broker_stack(cash=4000.0, metadata=metadata)
    try:
        order = broker.sell(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "option_seller_margin_blocked"
    finally:
        broker.stop()

    assert client.submitted_orders == []
    assert store is not None


def test_broker_fill_accepts_actual_option_fee_without_mutating_snapshot_cash():
    metadata = _option_metadata()
    client, store, data, broker = _broker_stack(cash=4000.0, metadata=metadata)
    try:
        order = broker.buy(owner=None, data=data, size=1, price=20.0)
        assert (
            broker._apply_trade_update(
                {
                    "order_id": "btapi-1",
                    "trade_id": "offline-trade-2",
                    "side": "buy",
                    "size": 1,
                    "price": 20.0,
                    "commission": 3.02,
                }
            )
            == "applied"
        )
        assert order.executed.value == pytest.approx(200.0)
        assert order.executed.comm == pytest.approx(3.02)
        assert order.info["commission_source"] == "actual"
        assert order.info["pnl_status"] == "COMPLETE"
        assert broker.getcash() == pytest.approx(4000.0)
    finally:
        broker.stop()

    assert client.submitted_orders[0]["side"] == "buy"
    assert store is not None


def test_broker_buy_then_sell_fill_keeps_premium_values_and_linear_pnl():
    metadata = _option_metadata()
    client, store, data, broker = _broker_stack(cash=4000.0, metadata=metadata)
    try:
        opening = broker.buy(owner=None, data=data, size=1, price=20.0)
        assert (
            broker._apply_trade_update(
                {
                    "order_id": "btapi-1",
                    "trade_id": "offline-trade-open",
                    "side": "buy",
                    "size": 1,
                    "price": 20.0,
                    "commission": 3.02,
                }
            )
            == "applied"
        )
        assert opening.executed[0].openedvalue == pytest.approx(200.0)

        closing = broker.sell(owner=None, data=data, size=1, price=25.0, offset="close")
        assert (
            broker._apply_trade_update(
                {
                    "order_id": "btapi-2",
                    "trade_id": "offline-trade-close",
                    "side": "sell",
                    "size": 1,
                    "price": 25.0,
                    "commission": 3.025,
                    "fill_role": "maker",
                }
            )
            == "applied"
        )
        assert closing.executed[0].closedvalue == pytest.approx(200.0)
        assert closing.executed.pnl == pytest.approx(50.0)
        assert closing.executed.comm == pytest.approx(3.025)
        assert broker.getcash() == pytest.approx(4000.0)
    finally:
        broker.stop()

    assert [item["side"] for item in client.submitted_orders] == ["buy", "sell"]
    assert store is not None

    # A dual-side option fill with a now-incomplete fee pair must keep the
    # raw fill quarantined and report that result through the outer dispatcher.
    client, store, data, broker = _broker_stack(
        cash=4000.0,
        metadata=metadata,
        broker_kwargs={"position_mode": "dual_side"},
        supports_dual_side=True,
    )
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=20.0,
            offset="open",
            position_side="long",
        )
        assert order.status == bt.Order.Accepted
        broker.getcommissioninfo(data).set_param("open_commission_by_volume", None)
        update = {
            "order_id": "btapi-1",
            "trade_id": "offline-trade-dual-quarantine",
            "side": "buy",
            "size": 1,
            "price": 20.0,
        }
        assert broker._apply_trade_update(update) == "quarantined"
        assert broker.long_positions[broker._position_key(data)].size == 0
        assert order.executed.size == 0
        assert order.info["pnl_status"] == "PNL_INCOMPLETE"
        assert order.info["invalid_fill_evidence"]["trade_id"] == update["trade_id"]
        assert broker._apply_trade_update(update) in {"ignored", "quarantined"}
    finally:
        broker.stop()


def test_broker_option_execution_value_is_premium_for_all_open_close_sides():
    comminfo = _option()

    assert BtApiBroker._execution_value(comminfo, 1, 20.0, is_buy=True) == pytest.approx(200.0)
    assert BtApiBroker._execution_value(comminfo, 1, 20.0, is_buy=False) == pytest.approx(200.0)
    assert BtApiBroker._execution_value(
        comminfo, -1, 25.0, is_buy=True, role="close"
    ) == pytest.approx(250.0)
    assert BtApiBroker._execution_value(
        comminfo, -1, 25.0, is_buy=False, role="close"
    ) == pytest.approx(250.0)
    with pytest.raises(OptionAccountingError, match="option_price_invalid"):
        BtApiBroker._execution_value(comminfo, 1, math.nan, is_buy=False)
    with pytest.raises(OptionAccountingError, match="option_price_invalid"):
        BtApiBroker._execution_value(comminfo, 1, "not-a-price", is_buy=False)


def test_option_getsize_returns_integer_contract_count():
    comminfo = _option()

    result = comminfo.getsize(20.0, 406.05)

    assert result == 2
    assert isinstance(result, int)


def test_signed_option_size_infers_sell_and_rejects_explicit_side_conflicts():
    comminfo = _option()

    assert comminfo.getoperationcost(-1, 20.0) == pytest.approx(3500.0)
    with pytest.raises(OptionAccountingError, match="option_side_conflict"):
        comminfo.getoperationcost(-1, 20.0, is_buy=True)
    with pytest.raises(OptionAccountingError, match="option_side_conflict"):
        comminfo.getoperationcost(1, 20.0, is_buy=True, side="sell")


def test_sdk_margin_provenance_is_structural_only_until_trusted_issuer_exists():
    comminfo = _option(seller_margin_evidence=_seller_evidence(source_kind="sdk"))

    assert comminfo.seller_margin_status() == "STRUCTURALLY_VALID_UNVERIFIED"
    with pytest.raises(OptionAccountingError, match="seller_margin_evidence_unverified"):
        comminfo.getoperationcost(-1, 20.0)


def test_option_zero_mark_is_valid_for_value_and_pnl():
    comminfo = _option()
    position = Position(size=1, price=20.0)

    assert comminfo.getvalue(position, 0.0) == pytest.approx(0.0)
    assert comminfo.profitandloss(1, 20.0, 0.0) == pytest.approx(-200.0)


def test_seller_evidence_requires_explicit_aware_timestamps_and_real_hash_shape():
    naive_basis = dict(_seller_evidence()["price_basis"])
    naive_basis["as_of_utc"] = "2026-09-10T00:00:00"
    with pytest.raises(OptionAccountingError, match="timezone_missing"):
        _option(seller_margin_evidence=_seller_evidence(price_basis=naive_basis)).get_margin(20.0)

    naive_expiry = _seller_evidence(expires_at_utc="2099-01-01T00:00:00")
    with pytest.raises(OptionAccountingError, match="timezone_missing"):
        _option(seller_margin_evidence=naive_expiry).get_margin(20.0)

    bad_hash_basis = dict(_seller_evidence()["price_basis"])
    bad_hash_basis["source_hash"] = "short"
    with pytest.raises(OptionAccountingError, match="source"):
        _option(
            seller_margin_evidence=_seller_evidence(source_hash="short", price_basis=bad_hash_basis)
        ).get_margin(20.0)


def test_seller_price_basis_is_positive_finite_and_matches_execution_price():
    bad_basis = dict(_seller_evidence()["price_basis"])
    bad_basis["option_price"] = True
    with pytest.raises(OptionAccountingError, match="option_price_invalid"):
        _option(seller_margin_evidence=_seller_evidence(price_basis=bad_basis)).get_margin(20.0)

    bad_basis = dict(_seller_evidence()["price_basis"])
    bad_basis["underlying_price"] = -1.0
    with pytest.raises(OptionAccountingError, match="underlying_price_invalid"):
        _option(seller_margin_evidence=_seller_evidence(price_basis=bad_basis)).get_margin(20.0)

    with pytest.raises(OptionAccountingError, match="price_scope_mismatch"):
        _option().getoperationcost(1, 21.0, is_buy=False)

    incomplete = _seller_evidence()
    incomplete.pop("quantity")
    with pytest.raises(OptionAccountingError, match="quantity_missing"):
        _option(seller_margin_evidence=incomplete).getoperationcost(1, 20.0, is_buy=False)


def test_option_class_and_metadata_multipliers_reject_nonfinite_or_boolean_values():
    with pytest.raises(OptionAccountingError, match="option_multiplier_invalid"):
        _option(mult=math.nan)
    with pytest.raises(OptionAccountingError, match="option_multiplier_invalid"):
        _option(mult=True)
    with pytest.raises(OptionAccountingError, match="option_multiplier_invalid"):
        BtApiBroker._metadata_to_comminfo(_option_metadata(multiplier=math.nan))
    with pytest.raises(OptionAccountingError, match="option_multiplier_invalid"):
        BtApiBroker._metadata_to_comminfo(_option_metadata(multiplier=True))


def test_option_metadata_fee_reader_preserves_units_and_rejects_bad_values():
    with pytest.raises(OptionAccountingError, match="option_fee_open_invalid"):
        BtApiBroker._metadata_to_comminfo(_option_metadata(open_fee_rate=-0.1))
    with pytest.raises(OptionAccountingError, match="option_fee_open_invalid"):
        BtApiBroker._metadata_to_comminfo(_option_metadata(open_fee_rate=True))

    comminfo = BtApiBroker._metadata_to_comminfo(_option_metadata(open_fee_rate=2.0))
    assert comminfo.getcommission(1, 20.0, role="open") == pytest.approx(403.0)

    with pytest.raises(OptionAccountingError, match="option_fee_open_invalid"):
        BtApiBroker._metadata_to_comminfo(
            _option_metadata(open_fee_rate=0.0001, OpenRatioByMoney=0.0002)
        )

    canonical = BtApiBroker._metadata_to_comminfo(
        _option_metadata(
            open_fee_rate=None,
            open_fee_amount=None,
            open_commission_by_money=0.0001,
            open_commission_by_volume=3.0,
        )
    )
    assert canonical.getcommission(1, 20.0, role="open") == pytest.approx(3.02)


def test_option_product_class_codes_are_explicit_and_conflicts_fail_closed():
    for key, product_class in (
        ("ProductClass", "2"),
        ("ProductClass", "6"),
        ("product_class", "2"),
    ):
        metadata = _option_metadata()
        metadata.pop("asset_type")
        metadata[key] = product_class
        assert isinstance(BtApiBroker._metadata_to_comminfo(metadata), CtpOptionPremium)

    metadata = _option_metadata(asset_type="unknown")
    metadata["ProductClass"] = "6"
    assert isinstance(BtApiBroker._metadata_to_comminfo(metadata), CtpOptionPremium)

    metadata = _option_metadata()
    metadata["ProductClass"] = "1"
    with pytest.raises(OptionAccountingError, match="asset_type_conflict"):
        BtApiBroker._metadata_to_comminfo(metadata)

    metadata = _option_metadata()
    metadata["instrument_id"] = "m2701"
    metadata["InstrumentID"] = "M2701"
    with pytest.raises(OptionAccountingError, match="scope_alias_conflict"):
        BtApiBroker._metadata_to_comminfo(metadata)


def test_seller_guard_runs_even_when_cash_check_is_disabled():
    client, store, data, broker = _broker_stack(
        cash=4000.0,
        metadata=_option_metadata(),
        broker_kwargs={"cash_check_enabled": False},
    )
    try:
        order = broker.sell(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "option_seller_margin_blocked"
        assert client.submitted_orders == []
    finally:
        broker.stop()
    assert store is not None


@pytest.mark.parametrize("cash", [math.nan, math.inf, -math.inf])
def test_option_buyer_rejects_nonfinite_account_cash(cash):
    client, store, data, broker = _broker_stack(cash=cash, metadata=_option_metadata())
    try:
        order = broker.buy(owner=None, data=data, size=1, price=20.0)
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "insufficient_cash"
        assert client.submitted_orders == []
    finally:
        broker.stop()
    assert store is not None


def test_ctp_option_close_role_wins_over_generic_maker_taker_label():
    comminfo = _option(
        open_commission_by_money=0.001,
        open_commission_by_volume=1.0,
        close_commission_by_money=0.002,
        close_commission_by_volume=2.0,
    )
    closed, opened = BtApiBroker._execution_commissions(
        comminfo,
        20.0,
        opened_qty=0,
        closed_qty=1,
        offset="close",
        fill_role="maker",
    )

    assert closed == pytest.approx(2.4)
    assert opened == pytest.approx(0.0)
