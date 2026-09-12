"""Pure-local CTP futures/call/put bundle discovery and selection.

The input is a caller-owned result of a public CTP instrument query. This
module creates no Store/client, reads no environment, and has no account or
execution capability. All identities come from returned CTP fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


class BundleSelectionError(ValueError):
    """A deterministic fail-closed discovery or selection rejection."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LegIdentity:
    instrument_id: str
    exchange_id: str
    product_id: str
    asset_type: str
    active: bool
    trading_day: str
    expiry: str
    tick_size: str
    multiplier: str
    underlying_instrument_id: str | None = None
    option_type: str | None = None
    strike: str | None = None


@dataclass(frozen=True)
class ThreeLegBundle:
    exchange_id: str
    product_id: str
    trading_day: str
    future: LegIdentity
    call: LegIdentity
    put: LegIdentity
    option_expiry: str
    strike: str

    def to_dict(self) -> dict[str, Any]:
        """Return only safe identity/metadata, never the source record."""
        return asdict(self)


_ALIASES = {
    "instrument_id": ("InstrumentID", "instrument_id", "instrument"),
    "exchange_id": ("ExchangeID", "exchange_id", "exchange"),
    "product_id": ("ProductID", "product_id", "product"),
    "asset_type": ("asset_type", "assetType", "ProductClass", "product_class"),
    "active": ("IsTrading", "is_trading", "active", "Active"),
    "trading_day": ("TradingDay", "trading_day"),
    "expiry": ("ExpireDate", "expire_date", "expiry", "expiry_date"),
    "tick_size": ("PriceTick", "price_tick", "tick_size"),
    "multiplier": ("VolumeMultiple", "volume_multiple", "multiplier", "contract_multiplier"),
    "underlying": ("UnderlyingInstrID", "underlying_instrument_id", "underlying"),
    "option_type": ("OptionsType", "option_type", "call_put"),
    "strike": ("StrikePrice", "strike_price", "strike"),
}


def discover_three_leg_bundles(
    records: Iterable[Mapping[str, Any]],
    *,
    product_id: str,
    exchange_id: str,
    trading_day: str,
    selector_policy: str = "per_leg",
) -> tuple[ThreeLegBundle, ...]:
    """Return every strict F/C/P match from a prefix-query record set.

    Multiple strikes and expiries are valid results. No candidate is
    preferred. Duplicate identities or conflicting alias values reject all.
    """
    product = _text(product_id, "product_id")
    exchange = _text(exchange_id, "exchange_id").upper()
    day = _date(trading_day, "trading_day")
    if selector_policy not in {"per_leg", "one_to_one"}:
        raise BundleSelectionError("UNSUPPORTED_SELECTOR_POLICY")
    rows = [_normalize(row, day) for row in _materialize_records(records)]
    scoped = [row for row in rows if row["exchange_id"] == exchange]
    _reject_duplicate_identities(scoped)
    futures = [
        row for row in scoped if row["asset_type"] == "future" and row["product_id"] == product
    ]
    options = [row for row in scoped if row["asset_type"] == "option"]
    bundles: list[ThreeLegBundle] = []
    for future in futures:
        matching = [row for row in options if row["underlying"] == future["instrument_id"]]
        for call in (row for row in matching if row["option_type"] == "call"):
            for put in (row for row in matching if row["option_type"] == "put"):
                if call["strike"] != put["strike"] or call["expiry"] != put["expiry"]:
                    continue
                if selector_policy == "one_to_one" and (
                    call["multiplier"] != future["multiplier"]
                    or put["multiplier"] != future["multiplier"]
                ):
                    continue
                bundles.append(_bundle(future, call, put, product, day))
    bundles.sort(
        key=lambda item: (
            item.option_expiry,
            Decimal(item.strike),
            item.future.expiry,
            item.future.instrument_id,
            item.call.instrument_id,
            item.put.instrument_id,
        )
    )
    return tuple(bundles)


def select_three_leg_bundle(
    records: Iterable[Mapping[str, Any]],
    *,
    product_id: str,
    exchange_id: str,
    trading_day: str,
    future_instrument_id: str | None = None,
    call_instrument_id: str | None = None,
    put_instrument_id: str | None = None,
    selector_policy: str = "per_leg",
) -> ThreeLegBundle:
    """Select exact IDs, or require exactly one discovered bundle."""
    ids = (future_instrument_id, call_instrument_id, put_instrument_id)
    if any(value is not None for value in ids) and not all(value is not None for value in ids):
        raise BundleSelectionError("EXACT_BUNDLE_IDS_MUST_BE_COMPLETE")
    bundles = discover_three_leg_bundles(
        records,
        product_id=product_id,
        exchange_id=exchange_id,
        trading_day=trading_day,
        selector_policy=selector_policy,
    )
    if all(value is not None for value in ids):
        wanted = tuple(_text(value, "instrument_id") for value in ids)
        matches = tuple(
            item
            for item in bundles
            if (item.future.instrument_id, item.call.instrument_id, item.put.instrument_id)
            == wanted
        )
        if len(matches) != 1:
            raise BundleSelectionError("EXACT_BUNDLE_NOT_FOUND_OR_AMBIGUOUS")
        return matches[0]
    if len(bundles) != 1:
        raise BundleSelectionError("BUNDLE_MISSING_OR_AMBIGUOUS")
    return bundles[0]


def _bundle(future, call, put, product: str, day: str) -> ThreeLegBundle:
    return ThreeLegBundle(
        exchange_id=future["exchange_id"],
        product_id=product,
        trading_day=day,
        future=_leg(future),
        call=_leg(call),
        put=_leg(put),
        option_expiry=call["expiry"],
        strike=call["strike"],
    )


def _leg(row) -> LegIdentity:
    return LegIdentity(
        instrument_id=row["instrument_id"],
        exchange_id=row["exchange_id"],
        product_id=row["product_id"],
        asset_type=row["asset_type"],
        active=row["active"],
        trading_day=row["trading_day"],
        expiry=row["expiry"],
        tick_size=row["tick_size"],
        multiplier=row["multiplier"],
        underlying_instrument_id=row["underlying"],
        option_type=row["option_type"],
        strike=row["strike"],
    )


def _normalize(record: Mapping[str, Any], requested_day: str) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise BundleSelectionError("INSTRUMENT_RECORD_NOT_MAPPING")
    row = {
        "instrument_id": _required_text(record, "instrument_id"),
        "exchange_id": _required_text(record, "exchange_id").upper(),
        "product_id": _required_text(record, "product_id"),
        "asset_type": _resolved_asset_type(record),
        "active": _resolved_active(record),
        "trading_day": _optional_date(record, "trading_day", requested_day),
        "expiry": _date(_required(record, "expiry"), "record.expiry"),
        "tick_size": _decimal_text(_required(record, "tick_size"), "tick_size", positive=True),
        "multiplier": _decimal_text(_required(record, "multiplier"), "multiplier", positive=True),
        "underlying": _optional_text(record, "underlying"),
        "option_type": _option_type(record),
        "strike": _optional_decimal(record, "strike"),
    }
    if not row["active"]:
        raise BundleSelectionError("INACTIVE_INSTRUMENT")
    if row["expiry"] <= requested_day:
        raise BundleSelectionError("EXPIRED_INSTRUMENT")
    if row["asset_type"] == "future":
        # CTP commonly returns NUL/DBL_MAX/product-underlying sentinels on futures.
        row["underlying"] = None
        row["option_type"] = None
        row["strike"] = None
    elif row["asset_type"] == "option":
        if (
            not row["underlying"]
            or row["option_type"] not in {"call", "put"}
            or row["strike"] is None
        ):
            raise BundleSelectionError("OPTION_METADATA_MISSING")
    else:
        raise BundleSelectionError("UNSUPPORTED_ASSET_TYPE")
    return row


def _reject_duplicate_identities(rows: Iterable[Mapping[str, Any]]) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        identity = (row["exchange_id"], row["instrument_id"])
        if identity in seen:
            raise BundleSelectionError("DUPLICATE_INSTRUMENT_IDENTITY")
        seen.add(identity)


def _materialize_records(records) -> list[Mapping[str, Any]]:
    if isinstance(records, (str, bytes, Mapping)):
        raise BundleSelectionError("INSTRUMENT_RECORDS_MUST_BE_ITERABLE_RECORDS")
    try:
        rows = list(records)
    except TypeError as exc:
        raise BundleSelectionError("INSTRUMENT_RECORDS_NOT_ITERABLE") from exc
    if not rows:
        raise BundleSelectionError("INSTRUMENT_RECORDS_EMPTY")
    return rows


def _required(record: Mapping[str, Any], name: str) -> Any:
    values = [
        record[key] for key in _ALIASES[name] if key in record and record[key] not in (None, "")
    ]
    if not values:
        raise BundleSelectionError(f"MISSING_{name.upper()}")
    if len({_comparison(value) for value in values}) != 1:
        raise BundleSelectionError(f"AMBIGUOUS_{name.upper()}")
    return values[0]


def _optional(record: Mapping[str, Any], name: str) -> Any:
    values = [
        record[key] for key in _ALIASES[name] if key in record and record[key] not in (None, "")
    ]
    if not values:
        return None
    if len({_comparison(value) for value in values}) != 1:
        raise BundleSelectionError(f"AMBIGUOUS_{name.upper()}")
    return values[0]


def _required_text(record, name: str) -> str:
    return _text(_required(record, name), name)


def _optional_text(record, name: str) -> str | None:
    value = _optional(record, name)
    return None if value is None else _text(value, name)


def _optional_date(record, name: str, default: str) -> str:
    value = _optional(record, name)
    if value is None:
        return default
    result = _date(value, f"record.{name}")
    if result != default:
        raise BundleSelectionError("TRADING_DAY_MISMATCH")
    return result


def _canonical_option_type(value: Any) -> str | None:
    key = str(value).strip().lower().replace("\\x00", "").replace("\x00", "")
    if key in {"", "0", "null", "none"}:
        return None
    if key in {"1", "c", "call"}:
        return "call"
    if key in {"2", "p", "put"}:
        return "put"
    raise BundleSelectionError("UNSUPPORTED_OPTION_TYPE")


def _option_type(record) -> str | None:
    values = [
        record[key]
        for key in _ALIASES["option_type"]
        if key in record and record[key] not in (None, "")
    ]
    if not values:
        return None
    # ``OptionsType=1`` and ``option_type='call'`` are one fact in two
    # spellings; canonicalize before comparing so mixed native/normalized
    # records are not misread as an ambiguity.
    canonical = {_canonical_option_type(value) for value in values}
    if None in canonical and len(canonical) > 1:
        # A NUL/empty native sentinel alongside an explicit value is the
        # record spelling difference, not a conflict; keep the explicit one.
        explicit = {value for value in canonical if value is not None}
        if len(explicit) == 1:
            return explicit.pop()
    if len(canonical) != 1:
        raise BundleSelectionError("AMBIGUOUS_OPTION_TYPE")
    return canonical.pop()


def _asset_type(value: Any) -> str:
    key = str(value).strip().lower()
    if key in {"1", "future", "futures", "fut"}:
        return "future"
    if key in {"2", "option", "options", "opt"}:
        return "option"
    raise BundleSelectionError("UNSUPPORTED_ASSET_TYPE")


def _resolved_asset_type(record: Mapping[str, Any]) -> str:
    """Canonicalize every asset-type alias before comparing.

    Records routinely carry both the normalized ``asset_type`` field and the
    raw ``ProductClass``/``product_class`` native fields (``"future"`` vs
    ``"1"``).  Those are the same fact in two spellings, not an ambiguity;
    only genuinely conflicting canonical values are rejected.
    """

    values = [
        record[key]
        for key in _ALIASES["asset_type"]
        if key in record and record[key] not in (None, "")
    ]
    if not values:
        raise BundleSelectionError("MISSING_ASSET_TYPE")
    canonical = {_asset_type(value) for value in values}
    if len(canonical) != 1:
        raise BundleSelectionError("AMBIGUOUS_ASSET_TYPE")
    return canonical.pop()


def _active(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (1, "1", "true", "True", "active", "ACTIVE"):
        return True
    if value in (0, "0", "false", "False", "inactive", "INACTIVE"):
        return False
    raise BundleSelectionError("ACTIVE_FIELD_INVALID")


def _resolved_active(record: Mapping[str, Any]) -> bool:
    """Canonicalize every active alias before comparing.

    Mirrors the asset-type rule: ``IsTrading=1`` and ``active=True`` are one
    fact in two spellings, not an ambiguity.
    """

    values = [
        record[key]
        for key in _ALIASES["active"]
        if key in record and record[key] not in (None, "")
    ]
    if not values:
        raise BundleSelectionError("MISSING_ACTIVE")
    canonical = {_active(value) for value in values}
    if len(canonical) != 1:
        raise BundleSelectionError("AMBIGUOUS_ACTIVE")
    return canonical.pop()


def _date(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 8 or not text.isdigit():
        raise BundleSelectionError(f"INVALID_{name.upper()}")
    return text


def _text(value: Any, name: str) -> str:
    if isinstance(value, bool):
        raise BundleSelectionError(f"INVALID_{name.upper()}")
    text = str(value).strip()
    if not text:
        raise BundleSelectionError(f"MISSING_{name.upper()}")
    return text


def _decimal_text(value: Any, name: str, *, positive: bool = False) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BundleSelectionError(f"INVALID_{name.upper()}") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise BundleSelectionError(f"INVALID_{name.upper()}")
    return format(number.normalize(), "f")


def _optional_decimal(record, name: str) -> str | None:
    value = _optional(record, name)
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BundleSelectionError(f"INVALID_{name.upper()}") from exc
    # DBL_MAX is accepted only as a future sentinel and discarded above.
    if not number.is_finite() or number >= Decimal("1e300") or number <= 0:
        return None
    return format(number.normalize(), "f")


def _comparison(value: Any) -> str:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return _decimal_text(value, "comparison")
    return str(value).strip().lower()


__all__ = [
    "BundleSelectionError",
    "LegIdentity",
    "ThreeLegBundle",
    "discover_three_leg_bundles",
    "select_three_leg_bundle",
]
