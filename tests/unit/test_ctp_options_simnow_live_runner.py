from __future__ import annotations

import datetime as dt
import copy
import time
from types import SimpleNamespace

import pytest

from examples.ctp_options_simnow_live_runner import (
    SimNowLiveRunner,
    SimNowLiveRunnerBlocked,
)

SYMBOLS = ("DCE.m2701", "DCE.m2701-C-3400", "DCE.m2701-P-3400")


def _identity(**changes):
    value = {
        "account_fingerprint": "acct-test-sha256",
        "trading_day": "20260911",
        "connection_generation": 7,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
    }
    value.update(changes)
    return value


def _records():
    return [
        {
            "InstrumentID": "m2701",
            "ExchangeID": "DCE",
            "ProductID": "m",
            "ProductClass": "1",
            "IsTrading": 1,
            "TradingDay": "20260911",
            "ExpireDate": "20261207",
            "PriceTick": 0.5,
            "VolumeMultiple": 10,
        },
        {
            "InstrumentID": "m2701-C-3400",
            "ExchangeID": "DCE",
            "ProductID": "m",
            "ProductClass": "2",
            "OptionsType": "1",
            "UnderlyingInstrID": "m2701",
            "StrikePrice": 3400,
            "IsTrading": 1,
            "TradingDay": "20260911",
            "ExpireDate": "20261207",
            "PriceTick": 0.5,
            "VolumeMultiple": 10,
        },
        {
            "InstrumentID": "m2701-P-3400",
            "ExchangeID": "DCE",
            "ProductID": "m",
            "ProductClass": "2",
            "OptionsType": "2",
            "UnderlyingInstrID": "m2701",
            "StrikePrice": 3400,
            "IsTrading": 1,
            "TradingDay": "20260911",
            "ExpireDate": "20261207",
            "PriceTick": 0.5,
            "VolumeMultiple": 10,
        },
    ]


def _bundle():
    return _identity(
        schema_version="backtrader.ctp.bundle-preflight.v2",
        legs=[
            {"exchange_id": "DCE", "instrument_id": symbol.split(".", 1)[1], "is_primary": i == 0}
            for i, symbol in enumerate(SYMBOLS)
        ],
        snapshot_sha256="b" * 64,
    )


def _execution_reference(received_monotonic=None):
    received_monotonic = (
        received_monotonic if received_monotonic is not None else time.monotonic() - 0.1
    )
    received_at = dt.datetime.now(dt.timezone.utc)
    bundle_legs = [
        {"exchange_id": "DCE", "instrument_id": symbol.split(".", 1)[1], "is_primary": i == 0}
        for i, symbol in enumerate(SYMBOLS)
    ]
    quote_legs = [
        {
            "exchange_id": "DCE",
            "instrument_id": symbol.split(".", 1)[1],
            "bid_price": 9.5,
            "ask_price": 10.0,
            "bid_volume": 3,
            "ask_volume": 3,
            "entry_buy_price": 10.0,
            "exit_sell_price": 9.5,
            "requested_at_utc": (received_at - dt.timedelta(milliseconds=20)).isoformat(),
            "received_at_utc": received_at.isoformat(),
            "requested_monotonic": received_monotonic - 0.02,
            "received_monotonic": received_monotonic,
        }
        for i, symbol in enumerate(SYMBOLS)
    ]
    bundle_preflight = _identity(
        schema_version="backtrader.ctp.bundle-preflight.v2",
        legs=bundle_legs,
        snapshot_sha256="b" * 64,
    )
    return {
        "schema_version": "backtrader.ctp.bundle-execution-reference.v1",
        "read_only": True,
        "execution_eligible": False,
        "bundle_preflight": bundle_preflight,
        "query_results": {},
        "prices": {},
        "legs": quote_legs,
        "broker_contract_metadata": None,
        "request_count_delta": {},
        "write_request_free": True,
        "evidence_complete": True,
        "evidence_errors": [],
        "snapshot_sha256": "e" * 64,
    }


def _quote_reference(received_monotonic=None):
    full = _execution_reference(received_monotonic)
    bundle = full["bundle_preflight"]
    primary = next(leg for leg in bundle["legs"] if leg["is_primary"] is True)
    scope = {
        "instrument": f"{primary['exchange_id']}.{primary['instrument_id']}",
        "authorized_instruments": sorted(
            f"{leg['exchange_id']}.{leg['instrument_id']}" for leg in bundle["legs"]
        ),
        "connection_generation": bundle["connection_generation"],
        "account_fingerprint": bundle["account_fingerprint"],
        "trading_day": bundle["trading_day"],
        "exchange_id": primary["exchange_id"],
    }
    return {
        "schema_version": "backtrader.ctp.bundle-quote-reference.v1",
        "read_only": True,
        "evidence_complete": True,
        "write_request_free": True,
        "bundle_scope": scope,
        "bundle_preflight": copy.deepcopy(bundle),
        "legs": copy.deepcopy(full["legs"]),
        "snapshot_sha256": "q" * 64,
    }


def _raw_reconciliation(**changes):
    value = _identity(
        schema_version="backtrader.ctp.preflight.v1",
        unmatched_trade_count=None,
        reconciliation_fingerprint="f" * 64,
        query_results={
            "account": {"request_id": 1},
            "positions": {"request_id": 2},
            "orders": {"request_id": 3},
            "trades": {"request_id": 4},
        },
        execution_summary={"unmatched_trade_count": 0},
    )
    value.update(changes)
    return value


def _snapshots():
    stage_a = _identity(
        schema_version="backtrader.ctp.preflight.v1",
        exchange_id="DCE",
        product_id="m",
        snapshot_sha256="a" * 64,
    )
    stage_b = _identity(
        schema_version="backtrader.ctp.preflight.v1",
        exchange_id="DCE",
        instrument_id="m2701",
        snapshot_sha256="c" * 64,
    )
    return {
        "settlement_verified": True,
        "preflight_context": {"market_data_only": True, "execution_armed": False},
        "stage_a": stage_a,
        "stage_b": stage_b,
        "bundle_execution_reference": _execution_reference(),
        "public_capabilities": {"get_ctp_bundle_execution_reference_snapshot": True},
        "raw_reconciliation_rounds": [_raw_reconciliation(), _raw_reconciliation()],
    }


class FakeStore:
    def __init__(self):
        self.calls = []

    def get_ctp_preflight_snapshot(self, *args, **kwargs):
        self.calls.append(("preflight", args, kwargs))
        return _identity(schema_version="backtrader.ctp.preflight.v1")

    def get_ctp_bundle_preflight_snapshot(self, *args, **kwargs):
        self.calls.append(("bundle", args, kwargs))
        return _bundle()

    def get_ctp_bundle_execution_reference_snapshot(
        self, legs, *, primary_leg=None, primary_instrument_id=None, timeout=15.0
    ):
        self.calls.append(
            (
                "execution_reference",
                (legs,),
                {
                    "primary_leg": primary_leg,
                    "primary_instrument_id": primary_instrument_id,
                    "timeout": timeout,
                },
            )
        )
        return _execution_reference()

    def get_ctp_reconciliation_snapshot(self, *args, **kwargs):
        self.calls.append(("reconciliation", args, kwargs))
        return _identity(schema_version="backtrader.ctp.preflight.v1")


class FakeBroker:
    def __init__(self):
        self.writes = []
        self.orders = []
        self.reconciliation_calls = []
        self._reconciliation_state = {
            "complete": False,
            "consecutive_complete_rounds": 0,
            "account_fingerprint": "acct-test-sha256",
            "connection_generation": 7,
            "unknown_intent_count": 0,
            "unmatched_trade_count": 0,
            "reconciliation_fingerprint": "f" * 64,
        }

    def buy(self, **kwargs):
        self.writes.append(("buy", kwargs))
        order = SimpleNamespace(ref=len(self.orders) + 1, info=dict(kwargs), status=0)
        self.orders.append(order)
        return order

    def sell(self, **kwargs):
        self.writes.append(("sell", kwargs))
        order = SimpleNamespace(ref=len(self.orders) + 1, info=dict(kwargs), status=0)
        self.orders.append(order)
        return order

    def cancel(self, order):
        self.writes.append(("cancel", order))
        return order

    def record_ctp_reconciliation(self, snapshot):
        self.reconciliation_calls.append(snapshot)
        if snapshot.get("unmatched_trade_count") is None:
            assert snapshot["execution_summary"]["unmatched_trade_count"] == 0
        self._reconciliation_state["consecutive_complete_rounds"] += 1
        self._reconciliation_state["complete"] = (
            self._reconciliation_state["consecutive_complete_rounds"] >= 2
        )
        return self.get_ctp_reconciliation_state()

    def get_ctp_reconciliation_state(self):
        return dict(self._reconciliation_state)


def _authorization():
    return {
        "armed": True,
        "hmac_grant_configured": True,
        "signature_hmac_sha256": "s" * 64,
        "account_fingerprint": "acct-test-sha256",
        "connection_generation": 7,
    }


def _execution_state():
    return {
        "store_armed": True,
        "broker_started": True,
        "account_fingerprint": "acct-test-sha256",
        "trading_day": "20260911",
        "connection_generation": 7,
    }


def _runner(broker=None, authorization=None):
    broker = broker or FakeBroker()
    return (
        SimNowLiveRunner(
            store=FakeStore(),
            broker=broker,
            feeds={symbol: object() for symbol in SYMBOLS},
            owner=object(),
            instrument_records=_records(),
            product_id="m",
            exchange_id="DCE",
            trading_day="20260911",
            snapshots=_snapshots(),
            execution_authorization=authorization or _authorization(),
        ),
        broker,
    )


def _execute(runner, prices=None):
    runner.preflight()
    return runner.execute_preflighted(
        prices=prices or dict.fromkeys(SYMBOLS, 10.0),
        execution_state=_execution_state(),
    )


def _native_fill(order, generation=7, trade_id="T1", system_id="SYS1"):
    order.status = 4
    order.getstatusname = lambda: "Completed"
    order.info.update(
        {
            "execution_fill_source": "trade",
            "trade_id": trade_id,
            "external_order_id": system_id,
            "ctp_order_ref": "R1",
            "front_id": 1,
            "session_id": 2,
            "connection_generation": generation,
        }
    )
    return order


def test_default_preflight_is_read_only_and_import_has_no_runtime_side_effects():
    runner, broker = _runner()

    report = runner.start()

    assert report["status"] == "PREFLIGHT_PASS"
    assert report["execution_admitted"] is False
    assert report["iteration_25"] == "HFT_NOT_ADMITTED"
    assert broker.writes == []
    assert len(broker.reconciliation_calls) == 2
    assert runner.store.calls == []


def test_real_store_reference_contract_inherits_identity_and_scope_from_nested_bundle():
    reference = _execution_reference()
    assert "account_fingerprint" not in reference
    assert "read_only_safe" not in reference
    runner, _broker = _runner()
    runner.snapshots["bundle_execution_reference"] = reference

    assert runner.preflight()["status"] == "PREFLIGHT_PASS"


def test_real_store_reference_contract_rejects_nested_bundle_identity_or_leg_drift():
    reference = _execution_reference()
    reference["bundle_preflight"]["account_fingerprint"] = "other-account"
    runner, _broker = _runner()
    runner.snapshots["bundle_execution_reference"] = copy.deepcopy(reference)

    with pytest.raises(SimNowLiveRunnerBlocked, match="STAGE_BUNDLE_IDENTITY_MISMATCH"):
        runner.preflight()


def test_quote_only_reference_cannot_replace_full_preflight():
    runner, _broker = _runner()
    runner.snapshots["bundle_execution_reference"] = _quote_reference()

    with pytest.raises(SimNowLiveRunnerBlocked, match="EXECUTION_REFERENCE_SCHEMA_INVALID"):
        runner.preflight()


def test_exit_accepts_quote_only_reference_after_frozen_full_preflight():
    runner, broker = _runner()
    session = _execute(runner)
    for index in range(3):
        session.on_order_update(_native_fill(broker.orders[-1], trade_id=f"T{index}"))

    session.plan_exit(
        dict.fromkeys(SYMBOLS, 9.5),
        intent_id="exit",
        reference_snapshot=_quote_reference(),
    )
    assert session.cycle.phase == "CLOSE"


def test_quote_only_reference_rejects_bundle_scope_drift():
    runner, broker = _runner()
    session = _execute(runner)
    for index in range(3):
        session.on_order_update(_native_fill(broker.orders[-1], trade_id=f"T{index}"))
    reference = _quote_reference()
    reference["bundle_scope"]["exchange_id"] = "CZCE"

    with pytest.raises(SimNowLiveRunnerBlocked, match="QUOTE_REFERENCE_SCOPE_MISMATCH"):
        session.plan_exit(
            dict.fromkeys(SYMBOLS, 9.5),
            intent_id="exit",
            reference_snapshot=reference,
        )


def test_preflight_freezes_once_and_execute_does_not_record_raw_again():
    runner, broker = _runner()
    first = runner.preflight()
    second = runner.preflight()
    assert first == second
    assert len(broker.reconciliation_calls) == 2

    runner.execute_preflighted(
        prices=dict.fromkeys(SYMBOLS, 10.0),
        execution_state=_execution_state(),
    )
    assert len(broker.reconciliation_calls) == 2


def test_execute_without_preflight_or_with_changed_lifecycle_identity_blocks():
    runner, broker = _runner()
    with pytest.raises(SimNowLiveRunnerBlocked, match="PREFLIGHT_REQUIRED"):
        runner.execute_preflighted(
            prices=dict.fromkeys(SYMBOLS, 10.0),
            execution_state=_execution_state(),
        )
    runner.preflight()
    changed = dict(_execution_state(), connection_generation=8)
    with pytest.raises(SimNowLiveRunnerBlocked, match="IDENTITY_MISMATCH"):
        runner.begin(prices=dict.fromkeys(SYMBOLS, 10.0), execution_state=changed)
    assert len(broker.reconciliation_calls) == 2


def test_compat_start_execute_still_requires_frozen_preflight():
    runner, broker = _runner()
    with pytest.raises(SimNowLiveRunnerBlocked, match="PREFLIGHT_REQUIRED"):
        runner.start(
            execute=True,
            prices=dict.fromkeys(SYMBOLS, 10.0),
            execution_state=_execution_state(),
        )
    assert broker.writes == []


def test_execute_cannot_bypass_hmac_gate():
    runner, broker = _runner(authorization={"armed": True})

    with pytest.raises(SimNowLiveRunnerBlocked, match="HMAC_GRANT"):
        _execute(runner)
    assert broker.writes == []


def test_preflight_requires_execution_reference_capability_and_does_not_requery_store():
    runner, _broker = _runner()
    runner.snapshots["public_capabilities"] = {}

    with pytest.raises(SimNowLiveRunnerBlocked, match="PUBLIC_CAPABILITY_MISSING"):
        runner.start()
    assert runner.store.calls == []


def test_explicit_collection_uses_scopes_and_nonzero_timeout():
    runner, _broker = _runner()

    collected = runner.collect_public_evidence(timeout=3.0)

    assert collected["public_capabilities"]["get_ctp_bundle_execution_reference_snapshot"] is True
    assert [call[0] for call in runner.store.calls] == [
        "preflight",
        "preflight",
        "execution_reference",
    ]
    assert runner.store.calls[0][2]["product_id"] == "m"
    assert runner.store.calls[0][2]["exchange_id"] == "DCE"
    assert runner.store.calls[0][2]["timeout"] == 3.0
    assert runner.store.calls[1][1] == ("DCE.m2701",)


def test_prices_must_match_reference_ticks_before_first_write():
    runner, broker = _runner()

    with pytest.raises(SimNowLiveRunnerBlocked, match="ENTRY_PRICE_MUST_EQUAL_REFERENCE_ASK"):
        _execute(runner, dict.fromkeys(SYMBOLS, 10.25))
    assert broker.writes == []


def test_three_leg_entry_then_exit_requires_native_callbacks_and_two_flat_rounds():
    runner, broker = _runner()
    session = _execute(runner)
    assert len(broker.writes) == 1
    assert broker.writes[0][0] == "buy"

    for index in range(3):
        session.on_order_update(_native_fill(broker.orders[-1], trade_id=f"T{index + 1}"))
        if index < 2:
            assert len(broker.writes) == index + 2
    exit_reference = _quote_reference()
    session.plan_exit(
        dict.fromkeys(SYMBOLS, 9.5),
        intent_id="exit",
        reference_snapshot=exit_reference,
    )
    session.submit_next_exit()
    assert broker.writes[3][0] == "sell"
    for index in range(3):
        session.on_order_update(_native_fill(broker.orders[-1], trade_id=f"C{index + 1}"))
        if index < 2:
            assert broker.writes[4 + index][0] == "sell"

    first = _raw_reconciliation()
    second = _raw_reconciliation()
    assert session.finalize_flat(first, second)["status"] == "MECHANICAL_PASS"
    assert session.status()["iteration_25"] == "HFT_NOT_ADMITTED"


def test_missing_native_callback_evidence_blocks_before_exit():
    runner, broker = _runner()
    session = _execute(runner)
    order = broker.orders[-1]
    order.status = 4
    order.getstatusname = lambda: "Completed"

    with pytest.raises(Exception, match="NATIVE_FILL_IDENTITY_INCOMPLETE"):
        session.on_order_update(order)
    assert session.cycle.state == "RECOVERY_REQUIRED"
    assert len(broker.writes) == 1


def test_final_flat_requires_two_stable_rounds():
    runner, broker = _runner()
    session = _execute(runner)
    for index in range(3):
        session.on_order_update(_native_fill(broker.orders[-1], trade_id=f"T{index}"))
    exit_reference = _quote_reference()
    session.plan_exit(
        dict.fromkeys(SYMBOLS, 9.5),
        intent_id="exit",
        reference_snapshot=exit_reference,
    )
    session.submit_next_exit()
    for index in range(3):
        session.on_order_update(_native_fill(broker.orders[-1], trade_id=f"C{index}"))
    changed = _raw_reconciliation(trading_day="20260912")
    with pytest.raises(Exception, match="BROKER_RECONCILIATION"):
        session.finalize_flat(_raw_reconciliation(), changed)
