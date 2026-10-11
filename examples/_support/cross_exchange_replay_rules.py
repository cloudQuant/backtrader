"""Load one deliberately small, selected-record public rule snapshot.

This module is pure: it never calls an exchange, reads credentials, or creates
an SDK client.  The fixture contains selected fields plus the digest of each
captured response body; it intentionally does not retain or reconstruct a
complete raw response body.  Consequently, its output is suitable only for
formula/replay checks, never live metadata admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any, Dict, Union

from bt_api_py import CrossVenueLeg as InstrumentRule

CONSERVATIVE_REPLAY_TAKER_FEE = Decimal("0.0006")
SNAPSHOT_SCHEMA_VERSION = 1


class PublicRuleSnapshotError(ValueError):
    """The selected-record fixture is unavailable, malformed, or untrusted."""


# This is intentionally a complete expectation for schema v1.  The raw API
# bodies are not in the repository, so accepting arbitrary values alongside a
# claimed body digest would be a false provenance guarantee.
_EXPECTED_SNAPSHOT_V1 = {
    "schema_version": SNAPSHOT_SCHEMA_VERSION,
    "record_kind": "selected_public_instrument_rule_records",
    "capture": {
        "captured_at": "2026-09-13T23:08:41Z",
        "authentication": "none",
        "repository_content": "SELECTED_RECORDS_ONLY_NO_COMPLETE_RAW_BODIES",
        "raw_body_retention": "OUTSIDE_REPOSITORY_OWNER_ONLY_LOCAL_EVIDENCE",
    },
    "projection_policy": {
        "taker_fee": "CONSERVATIVE_REPLAY_BOUND_NOT_ACCOUNT_FEE",
        "okx_minimum_notional": "ZERO_NO_NOTIONAL_FLOOR_IN_SELECTED_RECORD_FORMULA_ONLY",
    },
    "sources": {
        "okx": {
            "method": "GET",
            "transport": "HTTPS",
            "url": (
                "https://openapi.okx.com/api/v5/public/instruments?"
                "instType=SWAP&instId=BTC-USDT-SWAP"
            ),
            "http_status": 200,
            "body_sha256": "1a6eeb4c4cc625067010d0110718feaee4a6f03becc60f661b800acb4f5ac4e2",
            "selected_record_scope": "BTC-USDT-SWAP_SELECTED_ROW_ONLY",
        },
        "binance": {
            "method": "GET",
            "transport": "HTTPS",
            "url": "https://fapi.binance.com/fapi/v1/exchangeInfo?symbol=BTCUSDT",
            "http_status": 200,
            "body_sha256": "27ceb67d0afca04694ae0ae46d9352b5a1ca1415dd1cf5eefaec72cf2011ac95",
            "selected_record_scope": "BTCUSDT_SELECTED_ROW_ONLY_NOT_COMPLETE_EXCHANGE_INFO_BODY",
        },
    },
    "selected_records": {
        "okx": {
            "instId": "BTC-USDT-SWAP",
            "state": "live",
            "ctType": "linear",
            "ctVal": "0.01",
            "ctMult": "1",
            "lotSz": "0.01",
            "minSz": "0.01",
            "tickSz": "0.1",
        },
        "binance": {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "contractType": "PERPETUAL",
            "priceFilter": {
                "minPrice": "556.80",
                "maxPrice": "4529764",
                "tickSize": ".10",
            },
            "lotSize": {
                "minQty": ".001",
                "maxQty": "1000",
                "stepSize": ".001",
            },
            "marketLotSize": {
                "minQty": ".001",
                "maxQty": "120",
                "stepSize": ".001",
            },
            "minNotional": {"notional": "50"},
        },
    },
}


def _require_expected(value: Any, expected: Any, path: str) -> None:
    """Fail closed on any schema-v1 difference, including unknown fields."""

    if isinstance(expected, Mapping):
        if not isinstance(value, Mapping):
            raise PublicRuleSnapshotError(f"{path} must be a mapping")
        unexpected = set(value) - set(expected)
        missing = set(expected) - set(value)
        if unexpected or missing:
            details = []
            if unexpected:
                details.append("unexpected=" + ",".join(sorted(map(str, unexpected))))
            if missing:
                details.append("missing=" + ",".join(sorted(map(str, missing))))
            raise PublicRuleSnapshotError(f"{path} keys are invalid: {'; '.join(details)}")
        for key, child_expected in expected.items():
            _require_expected(value[key], child_expected, f"{path}.{key}")
        return
    if value != expected or type(value) is not type(expected):
        raise PublicRuleSnapshotError(f"{path} does not match the selected-record capture")


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise PublicRuleSnapshotError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise PublicRuleSnapshotError(f"{field} is not a decimal") from exc
    if not result.is_finite() or result < 0:
        raise PublicRuleSnapshotError(f"{field} must be finite and non-negative")
    return result


def _load_payload(path: Union[str, Path]) -> Dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicRuleSnapshotError(
            "selected public-rule snapshot is unavailable or invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise PublicRuleSnapshotError("selected public-rule snapshot must be an object")
    return payload


def load_selected_public_rules(
    path: Union[str, Path],
    *,
    taker_fee: Union[Decimal, str] = CONSERVATIVE_REPLAY_TAKER_FEE,
) -> Dict[str, InstrumentRule]:
    """Project the immutable selected records into formula-replay rules.

    ``taker_fee`` is deliberately a caller-supplied conservative replay bound,
    not an exchange-account fee asserted by this public instrument snapshot.
    """

    payload = _load_payload(path)
    _require_expected(payload, _EXPECTED_SNAPSHOT_V1, "snapshot")
    fee = _decimal(str(taker_fee), "taker_fee")
    selected = payload["selected_records"]
    okx = selected["okx"]
    binance = selected["binance"]
    return {
        "okx": InstrumentRule(
            multiplier=_decimal(okx["ctVal"], "okx.ctVal") * _decimal(okx["ctMult"], "okx.ctMult"),
            quantity_step=_decimal(okx["lotSz"], "okx.lotSz"),
            minimum_quantity=_decimal(okx["minSz"], "okx.minSz"),
            minimum_notional=Decimal(0),
            price_tick=_decimal(okx["tickSz"], "okx.tickSz"),
            taker_fee=fee,
        ),
        "binance": InstrumentRule(
            multiplier=Decimal(1),
            quantity_step=_decimal(binance["lotSize"]["stepSize"], "binance.lotSize.stepSize"),
            minimum_quantity=_decimal(binance["lotSize"]["minQty"], "binance.lotSize.minQty"),
            minimum_notional=_decimal(
                binance["minNotional"]["notional"], "binance.minNotional.notional"
            ),
            price_tick=_decimal(binance["priceFilter"]["tickSize"], "binance.priceFilter.tickSize"),
            taker_fee=fee,
        ),
    }
