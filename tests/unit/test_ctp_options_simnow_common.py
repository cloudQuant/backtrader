"""Pure-local tests for the shared CTP option bundle selector."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ctp_options_simnow_common", ROOT / "examples/ctp_options_simnow_common.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


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
            "ProductClass": "2",
            "ProductID": "m-C",
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
            "ProductClass": "2",
            "ProductID": "m-P",
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


def _select(records):
    return MODULE.select_three_leg_bundle(
        records, product_id="m", exchange_id="DCE", trading_day="20260911"
    )


def test_selects_exact_current_future_and_matching_call_put_metadata_only():
    bundle = _select(_records())

    assert bundle.future.instrument_id == "m2701"
    assert bundle.call.instrument_id == "m2701-C-3400"
    assert bundle.put.instrument_id == "m2701-P-3400"
    assert bundle.strike == "3400"
    assert bundle.option_expiry == "20261207"
    assert set(bundle.to_dict()) == {
        "exchange_id",
        "product_id",
        "trading_day",
        "future",
        "call",
        "put",
        "option_expiry",
        "strike",
    }
    assert "account" not in str(bundle.to_dict()).lower()
    assert "order" not in str(bundle.to_dict()).lower()


@pytest.mark.parametrize("field", ["ExpireDate", "TradingDay"])
def test_expired_or_wrong_day_records_fail_closed(field):
    records = _records()
    records[0][field] = "20260910"
    with pytest.raises(MODULE.BundleSelectionError) as exc:
        _select(records)
    assert exc.value.reason in {"EXPIRED_INSTRUMENT", "TRADING_DAY_MISMATCH"}


def test_multiple_matching_calls_are_ambiguous():
    records = _records()
    duplicate = deepcopy(records[1])
    duplicate["InstrumentID"] = "m2701-C-3400-ALT"
    records.append(duplicate)

    with pytest.raises(MODULE.BundleSelectionError, match="AMBIGUOUS"):
        _select(records)


def test_missing_option_metadata_is_not_inferred_from_symbol():
    records = _records()
    del records[1]["UnderlyingInstrID"]

    with pytest.raises(MODULE.BundleSelectionError, match="OPTION_METADATA_MISSING"):
        _select(records)


@pytest.mark.parametrize(
    ("field", "value"),
    [("UnderlyingInstrID", "other"), ("StrikePrice", 3500), ("OptionsType", "1")],
)
def test_call_put_or_underlying_mismatch_is_rejected(field, value):
    records = _records()
    records[2][field] = value

    with pytest.raises(MODULE.BundleSelectionError):
        _select(records)


def test_tick_and_multiplier_mismatch_is_rejected():
    records = _records()
    records[2]["PriceTick"] = 1
    assert _select(records).put.tick_size == "1"

    records = _records()
    records[1]["VolumeMultiple"] = 20
    assert _select(records).call.multiplier == "20"
    with pytest.raises(MODULE.BundleSelectionError, match="BUNDLE"):
        MODULE.select_three_leg_bundle(
            records,
            product_id="m",
            exchange_id="DCE",
            trading_day="20260911",
            selector_policy="one_to_one",
        )


def test_ambiguous_alias_values_and_inactive_records_fail_closed():
    records = _records()
    records[0]["price_tick"] = 1
    with pytest.raises(MODULE.BundleSelectionError, match="AMBIGUOUS_TICK_SIZE"):
        _select(records)

    records = _records()
    records[2]["IsTrading"] = 0
    with pytest.raises(MODULE.BundleSelectionError, match="INACTIVE"):
        _select(records)


def test_real_sa701_shape_allows_future_sentinels_missing_trading_day_and_tick_difference():
    records = [
        {
            "InstrumentID": "SA701",
            "ExchangeID": "CZCE",
            "ProductID": "SA",
            "ProductClass": "1",
            "OptionsType": "\x00",
            "UnderlyingInstrID": "SA",
            "StrikePrice": 1.7976931348623157e308,
            "IsTrading": 1,
            "ExpireDate": "20270115",
            "PriceTick": 1.0,
            "VolumeMultiple": 20,
        }
    ]
    for strike in (640, 650):
        records.extend(
            [
                {
                    "InstrumentID": f"SA701C{strike}",
                    "ExchangeID": "CZCE",
                    "ProductID": "SAC",
                    "ProductClass": "2",
                    "OptionsType": "1",
                    "UnderlyingInstrID": "SA701",
                    "StrikePrice": strike,
                    "IsTrading": 1,
                    "ExpireDate": "20270115",
                    "PriceTick": 0.5,
                    "VolumeMultiple": 20,
                },
                {
                    "InstrumentID": f"SA701P{strike}",
                    "ExchangeID": "CZCE",
                    "ProductID": "SAP",
                    "ProductClass": "2",
                    "OptionsType": "2",
                    "UnderlyingInstrID": "SA701",
                    "StrikePrice": strike,
                    "IsTrading": 1,
                    "ExpireDate": "20270115",
                    "PriceTick": 0.5,
                    "VolumeMultiple": 20,
                },
            ]
        )
    bundles = MODULE.discover_three_leg_bundles(
        records, product_id="SA", exchange_id="CZCE", trading_day="20260911"
    )
    assert [bundle.strike for bundle in bundles] == ["640", "650"]
    assert all(
        bundle.future.tick_size == "1" and bundle.call.tick_size == "0.5" for bundle in bundles
    )
    with pytest.raises(MODULE.BundleSelectionError, match="AMBIGUOUS"):
        MODULE.select_three_leg_bundle(
            records, product_id="SA", exchange_id="CZCE", trading_day="20260911"
        )
    selected = MODULE.select_three_leg_bundle(
        records,
        product_id="SA",
        exchange_id="CZCE",
        trading_day="20260911",
        future_instrument_id="SA701",
        call_instrument_id="SA701C650",
        put_instrument_id="SA701P650",
        selector_policy="one_to_one",
    )
    assert selected.strike == "650"


def test_duplicate_identity_is_rejected_even_when_payload_is_identical():
    records = _records()
    records.append(deepcopy(records[1]))
    with pytest.raises(MODULE.BundleSelectionError, match="DUPLICATE"):
        _select(records)


def test_exact_ids_must_be_complete():
    with pytest.raises(MODULE.BundleSelectionError, match="EXACT_BUNDLE_IDS"):
        MODULE.select_three_leg_bundle(
            _records(),
            product_id="m",
            exchange_id="DCE",
            trading_day="20260911",
            future_instrument_id="m2701",
        )


def test_one_to_one_multiplier_policy_is_explicit():
    records = _records()
    records[1]["VolumeMultiple"] = 5
    assert (
        len(
            MODULE.discover_three_leg_bundles(
                records, product_id="m", exchange_id="DCE", trading_day="20260911"
            )
        )
        == 1
    )
    with pytest.raises(MODULE.BundleSelectionError, match="BUNDLE"):
        MODULE.select_three_leg_bundle(
            records,
            product_id="m",
            exchange_id="DCE",
            trading_day="20260911",
            selector_policy="one_to_one",
        )
