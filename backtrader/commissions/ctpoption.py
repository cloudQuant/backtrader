"""Explicit premium-style accounting for CTP options.

The CTP option contract is deliberately separate from the futures commission
schemes.  A long option consumes premium, while a short option needs an
authoritative total-margin observation.  This module only performs the
single-leg accounting projection; it does not reserve cash or maintain a live
account ledger.
"""

from __future__ import annotations

import copy
import datetime as _dt
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..comminfo import CommInfoBase
from ..parameters import ParameterDescriptor


class OptionAccountingError(ValueError):
    """Raised when option cost or evidence cannot be established safely."""

    def __init__(self, code: str, message: str | None = None):
        self.code = str(code)
        super().__init__(message or self.code)


@dataclass(frozen=True)
class CtpOptionSellerMarginEvidence:
    """Typed form of one account-bound seller margin observation.

    ``source_kind='synthetic'`` is intentionally supported for offline
    contract tests only.  It is retained as provenance and is never inferred
    from the futures ``FixedMargin``/``MiniMargin``/``Royalty`` fields.
    """

    account_fingerprint: str
    trading_day: str
    connection_generation: int
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    currency: str
    price_basis: Any
    expiry: Any
    source_hash: str
    expires_at_utc: Any
    total_margin: float
    quantity: float = 1.0
    source_kind: str = "sdk"

    def as_mapping(self) -> dict[str, Any]:
        """Return a plain mapping suitable for validation and serialization."""
        return {
            "account_fingerprint": self.account_fingerprint,
            "trading_day": self.trading_day,
            "connection_generation": self.connection_generation,
            "instrument_id": self.instrument_id,
            "exchange_id": self.exchange_id,
            "hedge_flag": self.hedge_flag,
            "currency": self.currency,
            "price_basis": self.price_basis,
            "expiry": self.expiry,
            "source_hash": self.source_hash,
            "expires_at_utc": self.expires_at_utc,
            "total_margin": self.total_margin,
            "quantity": self.quantity,
            "source_kind": self.source_kind,
        }


def _lookup(mapping: Mapping[str, Any], *keys: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _alias_value(
    mapping: Mapping[str, Any] | None,
    keys: tuple[str, ...],
    code: str,
) -> Any:
    """Read one explicit field and reject contradictory aliases."""
    if not isinstance(mapping, Mapping):
        return None
    values = [(key, mapping[key]) for key in keys if mapping.get(key) not in (None, "")]
    if not values:
        return None
    first = values[0][1]
    for key, value in values[1:]:
        if value != first:
            raise OptionAccountingError(
                code,
                f"{code}: conflicting aliases {values[0][0]!r} and {key!r}",
            )
    return first


def _finite_number(value: Any, code: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise OptionAccountingError(code, f"{code}: boolean is not a numeric value")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OptionAccountingError(code, f"{code}: expected a finite number") from exc
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise OptionAccountingError(code, f"{code}: expected a positive finite number")
    return number


def _as_utc(value: Any, code: str) -> _dt.datetime:
    if isinstance(value, _dt.datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = _dt.datetime.fromtimestamp(float(value), tz=_dt.timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise OptionAccountingError(code, f"{code}: invalid epoch timestamp") from exc
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise OptionAccountingError(code, f"{code}: value is missing")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = _dt.datetime.fromisoformat(text)
        except ValueError as exc:
            raise OptionAccountingError(code, f"{code}: invalid ISO timestamp") from exc
    else:
        raise OptionAccountingError(code, f"{code}: unsupported timestamp type")

    if parsed.tzinfo is None:
        raise OptionAccountingError(
            f"{code}_timezone_missing",
            f"{code}_timezone_missing: timestamp must carry an explicit UTC offset",
        )
    return parsed.astimezone(_dt.timezone.utc)


def _expiry_date(value: Any) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    formats = (
        (r"\d{8}", "%Y%m%d"),
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
        (r"\d{4}/\d{2}/\d{2}", "%Y/%m/%d"),
    )
    for pattern, fmt in formats:
        if not re.fullmatch(pattern, text):
            continue
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _scope_value(mapping: Mapping[str, Any], field: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    aliases = {
        "account_fingerprint": ("account_fingerprint", "account_id", "account"),
        "trading_day": ("trading_day", "trade_date", "TradingDay", "date"),
        "connection_generation": (
            "connection_generation",
            "generation",
            "connectionGeneration",
        ),
        "instrument_id": ("instrument_id", "InstrumentID", "instrument", "symbol"),
        "exchange_id": ("exchange_id", "ExchangeID", "exchange"),
        "hedge_flag": ("hedge_flag", "HedgeFlag", "hedge", "hedge_mode"),
        "currency": ("currency", "margin_currency", "settle_currency"),
        "expiry": ("expiry", "option_expiry", "expiry_date", "ExpireDate"),
        "source_hash": ("source_hash", "source_hash_sha256", "sourcehash"),
    }
    return _alias_value(mapping, aliases[field], f"seller_margin_{field}_alias_conflict")


def _validity_value(mapping: Mapping[str, Any]) -> Any:
    return _alias_value(
        mapping,
        (
            "expires_at_utc",
            "valid_until_utc",
            "valid_until",
            "expires_at",
            "expiry_timestamp",
        ),
        "seller_margin_validity_alias_conflict",
    )


def _normalise_scope_value(field: str, value: Any) -> Any:
    if field == "connection_generation":
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value).strip()
    if field in {"account_fingerprint", "instrument_id", "exchange_id", "hedge_flag", "currency"}:
        return str(value).strip()
    if field == "expiry":
        parsed = _expiry_date(value)
        if parsed is not None:
            return parsed.isoformat()
        return str(value).strip()
    if field == "source_hash":
        return str(value).strip().lower()
    if field == "trading_day":
        parsed = _expiry_date(value)
        if parsed is not None:
            return parsed.isoformat()
        return str(value).strip()
    return value


def _source_hash(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", text):
        raise OptionAccountingError(
            code,
            f"{code}: expected a 64-character hexadecimal source hash",
        )
    return text.lower()


def _finite_result(value: Any, code: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OptionAccountingError(code, f"{code}: result is not numeric") from exc
    if not math.isfinite(number):
        raise OptionAccountingError(code, f"{code}: result is not finite")
    return number


def _validate_price_basis(value: Any) -> Any:
    if isinstance(value, Mapping):
        basis = dict(value)
        option_price = _alias_value(
            basis,
            ("option_price", "premium_price", "input_price"),
            "seller_margin_option_price_alias_conflict",
        )
        underlying_price = _alias_value(
            basis,
            ("underlying_price", "futures_price", "underlying_mark_price"),
            "seller_margin_underlying_price_alias_conflict",
        )
        option_price = _finite_number(
            option_price,
            "seller_margin_option_price_invalid",
            positive=True,
        )
        underlying_price = _finite_number(
            underlying_price,
            "seller_margin_underlying_price_invalid",
            positive=True,
        )
        basis_time = _alias_value(
            basis,
            ("as_of_utc", "basis_time_utc", "timestamp_utc", "observed_at_utc"),
            "seller_margin_price_basis_time_alias_conflict",
        )
        if basis_time in (None, ""):
            raise OptionAccountingError(
                "seller_margin_price_basis_time_missing",
                "seller_margin_price_basis_time_missing: price basis time is required",
            )
        basis_source_hash = _alias_value(
            basis,
            ("source_hash", "source_hash_sha256", "sourcehash"),
            "seller_margin_price_basis_source_alias_conflict",
        )
        if basis_source_hash in (None, ""):
            raise OptionAccountingError(
                "seller_margin_price_basis_source_missing",
                "seller_margin_price_basis_source_missing: price basis source is required",
            )
        normalized = dict(basis)
        normalized["option_price"] = option_price
        normalized["underlying_price"] = underlying_price
        normalized["as_of_utc"] = _as_utc(basis_time, "seller_margin_price_basis_time_invalid")
        normalized["source_hash"] = _source_hash(
            basis_source_hash, "seller_margin_price_basis_source_invalid"
        )
        return normalized

    raise OptionAccountingError(
        "seller_margin_price_basis_invalid",
        "seller_margin_price_basis_invalid: option and underlying prices are required",
    )


def validate_seller_margin_evidence(
    evidence: Mapping[str, Any] | CtpOptionSellerMarginEvidence | None,
    *,
    expected_scope: Mapping[str, Any] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Validate and normalize an account-bound seller margin observation."""
    if isinstance(evidence, CtpOptionSellerMarginEvidence):
        evidence = evidence.as_mapping()
    if not isinstance(evidence, Mapping):
        raise OptionAccountingError(
            "seller_margin_evidence_missing",
            "seller_margin_evidence_missing: explicit total-margin evidence is required",
        )

    required = (
        "account_fingerprint",
        "trading_day",
        "connection_generation",
        "instrument_id",
        "exchange_id",
        "hedge_flag",
        "currency",
        "expiry",
        "source_hash",
        "price_basis",
        "expires_at_utc",
        "total_margin",
    )
    normalized: dict[str, Any] = {}
    for field in required:
        if field == "price_basis":
            value = _alias_value(
                evidence,
                ("price_basis", "pricebasis", "price_basis_evidence"),
                "seller_margin_price_basis_alias_conflict",
            )
        elif field == "expires_at_utc":
            value = _validity_value(evidence)
        elif field == "total_margin":
            value = _alias_value(
                evidence,
                ("total_margin", "seller_total_margin", "TotalMargin"),
                "seller_margin_total_alias_conflict",
            )
        else:
            value = _scope_value(evidence, field)
        if value in (None, ""):
            raise OptionAccountingError(
                f"seller_margin_{field}_missing",
                f"seller_margin_{field}_missing: seller evidence is incomplete",
            )
        normalized[field] = value

    normalized["connection_generation"] = _finite_number(
        normalized["connection_generation"], "seller_margin_generation_invalid", positive=True
    )
    if normalized["connection_generation"] != int(normalized["connection_generation"]):
        raise OptionAccountingError(
            "seller_margin_generation_invalid",
            "seller_margin_generation_invalid: generation must be an integer",
        )
    normalized["connection_generation"] = int(normalized["connection_generation"])
    normalized["price_basis"] = _validate_price_basis(normalized["price_basis"])
    normalized["source_hash"] = _source_hash(
        normalized["source_hash"], "seller_margin_source_hash_invalid"
    )
    normalized["total_margin"] = _finite_number(
        normalized["total_margin"], "seller_margin_total_invalid", positive=True
    )
    quantity_value = _alias_value(
        evidence,
        ("quantity", "qty", "volume"),
        "seller_margin_quantity_alias_conflict",
    )
    if quantity_value in (None, ""):
        raise OptionAccountingError(
            "seller_margin_quantity_missing",
            "seller_margin_quantity_missing: approved evidence quantity is required",
        )
    normalized["quantity"] = _finite_number(
        quantity_value,
        "seller_margin_quantity_invalid",
        positive=True,
    )
    source_kind = _alias_value(
        evidence,
        ("source_kind", "evidence_kind", "provenance", "source"),
        "seller_margin_source_kind_alias_conflict",
    )
    normalized["source_kind"] = str(source_kind or "").strip().lower()
    if not normalized["source_kind"]:
        raise OptionAccountingError(
            "seller_margin_source_kind_missing",
            "seller_margin_source_kind_missing: provenance is required",
        )
    synthetic_sources = {"synthetic", "offline", "fixture", "test"}
    sdk_sources = {
        "sdk",
        "sdk_public",
        "sdk_query",
        "ctp",
        "ctp_sdk",
        "ctp_direct",
        "native",
        "native_sdk",
        "authoritative",
    }
    if (
        normalized["source_kind"] not in synthetic_sources
        and normalized["source_kind"] not in sdk_sources
    ):
        raise OptionAccountingError(
            "seller_margin_source_kind_unknown",
            "seller_margin_source_kind_unknown: evidence provenance is not recognized",
        )
    normalized["expires_at_utc"] = _as_utc(
        normalized["expires_at_utc"], "seller_margin_expiry_invalid"
    )
    check_now = now or _dt.datetime.now(_dt.timezone.utc)
    if check_now.tzinfo is None:
        raise OptionAccountingError(
            "seller_margin_clock_timezone_missing",
            "seller_margin_clock_timezone_missing: validation clock needs an explicit UTC offset",
        )
    check_now = check_now.astimezone(_dt.timezone.utc)
    basis_time = normalized["price_basis"]["as_of_utc"]
    if basis_time > check_now:
        raise OptionAccountingError(
            "seller_margin_price_basis_future",
            "seller_margin_price_basis_future: price basis is from the future",
        )
    if normalized["expires_at_utc"] <= basis_time:
        raise OptionAccountingError(
            "seller_margin_evidence_expiry_invalid",
            "seller_margin_evidence_expiry_invalid: evidence expires before its price basis",
        )
    if normalized["price_basis"]["source_hash"] != normalized["source_hash"]:
        raise OptionAccountingError(
            "seller_margin_source_hash_mismatch",
            "seller_margin_source_hash_mismatch: price basis and evidence source differ",
        )
    if normalized["expires_at_utc"] <= check_now:
        raise OptionAccountingError(
            "seller_margin_evidence_expired",
            "seller_margin_evidence_expired: total-margin evidence is stale",
        )
    trading_day = _expiry_date(normalized["trading_day"])
    if trading_day is None:
        raise OptionAccountingError(
            "seller_margin_trading_day_invalid",
            "seller_margin_trading_day_invalid: trading day must be an explicit date",
        )
    normalized["trading_day"] = trading_day.isoformat()
    expiry_date = _expiry_date(normalized["expiry"])
    if expiry_date is None:
        raise OptionAccountingError(
            "seller_margin_expiry_invalid",
            "seller_margin_expiry_invalid: option expiry must be an explicit date",
        )
    if expiry_date is not None and expiry_date < check_now.date():
        raise OptionAccountingError(
            "seller_margin_contract_expired",
            "seller_margin_contract_expired: option contract has expired",
        )

    for field in required:
        if field in {"price_basis", "expires_at_utc", "total_margin"}:
            continue
        expected = _scope_value(expected_scope, field) if expected_scope else None
        if expected in (None, ""):
            continue
        actual = normalized[field]
        if _normalise_scope_value(field, actual) != _normalise_scope_value(field, expected):
            raise OptionAccountingError(
                f"seller_margin_{field}_scope_mismatch",
                f"seller_margin_{field}_scope_mismatch: evidence scope does not match order",
            )

    expected_basis = (
        _alias_value(
            expected_scope,
            ("price_basis", "pricebasis", "price_basis_evidence"),
            "seller_margin_expected_price_basis_alias_conflict",
        )
        if expected_scope
        else None
    )
    if expected_basis not in (None, ""):
        actual_basis = normalized["price_basis"]
        expected_basis = _validate_price_basis(expected_basis)
        if isinstance(actual_basis, Mapping) and isinstance(expected_basis, Mapping):
            basis_keys = {
                "option_price",
                "premium_price",
                "input_price",
                "price",
                "mark_price",
                "underlying_price",
                "futures_price",
                "reference_price",
            }
            for key in basis_keys.intersection(expected_basis):
                if key not in actual_basis:
                    raise OptionAccountingError(
                        "seller_margin_price_basis_scope_mismatch",
                        "seller_margin_price_basis_scope_mismatch: price basis differs",
                    )
                try:
                    if float(actual_basis[key]) != float(expected_basis[key]):
                        raise OptionAccountingError(
                            "seller_margin_price_basis_scope_mismatch",
                            "seller_margin_price_basis_scope_mismatch: price basis differs",
                        )
                except (TypeError, ValueError) as exc:
                    raise OptionAccountingError(
                        "seller_margin_price_basis_scope_mismatch",
                        "seller_margin_price_basis_scope_mismatch: price basis differs",
                    ) from exc
            for key in ("as_of_utc", "source_hash"):
                if actual_basis.get(key) != expected_basis.get(key):
                    raise OptionAccountingError(
                        "seller_margin_price_basis_scope_mismatch",
                        "seller_margin_price_basis_scope_mismatch: price basis differs",
                    )
        elif actual_basis != expected_basis:
            raise OptionAccountingError(
                "seller_margin_price_basis_scope_mismatch",
                "seller_margin_price_basis_scope_mismatch: price basis differs",
            )

    return normalized


class CtpOptionPremium(CommInfoBase):
    """Commission and value rules for explicit premium-style CTP options."""

    stocklike = ParameterDescriptor(default=True, type_=bool)
    commtype = ParameterDescriptor(default=CommInfoBase.COMM_FIXED, type_=int)
    percabs = ParameterDescriptor(default=True, type_=bool)
    premium_style = ParameterDescriptor(default=None)
    option_type = ParameterDescriptor(default=None)
    open_commission_by_money = ParameterDescriptor(default=None)
    open_commission_by_volume = ParameterDescriptor(default=None)
    close_commission_by_money = ParameterDescriptor(default=None)
    close_commission_by_volume = ParameterDescriptor(default=None)
    close_today_commission_by_money = ParameterDescriptor(default=None)
    close_today_commission_by_volume = ParameterDescriptor(default=None)
    close_yesterday_commission_by_money = ParameterDescriptor(default=None)
    close_yesterday_commission_by_volume = ParameterDescriptor(default=None)
    seller_margin_evidence = ParameterDescriptor(default=None)
    evidence_scope = ParameterDescriptor(default=None)

    _FEE_ALIASES = {
        "open_commission_by_money": (
            "open_fee_rate",
            "open_commission_rate",
            "OpenRatioByMoney",
        ),
        "open_commission_by_volume": (
            "open_fee_amount",
            "open_commission_amount",
            "OpenRatioByVolume",
        ),
        "close_commission_by_money": (
            "close_fee_rate",
            "close_commission_rate",
            "CloseRatioByMoney",
        ),
        "close_commission_by_volume": (
            "close_fee_amount",
            "close_commission_amount",
            "CloseRatioByVolume",
        ),
        "close_today_commission_by_money": (
            "close_today_fee_rate",
            "close_today_commission_rate",
            "CloseTodayRatioByMoney",
        ),
        "close_today_commission_by_volume": (
            "close_today_fee_amount",
            "close_today_commission_amount",
            "CloseTodayRatioByVolume",
        ),
        "close_yesterday_commission_by_money": (
            "close_yesterday_fee_rate",
            "close_yesterday_commission_rate",
            "CloseYesterdayRatioByMoney",
        ),
        "close_yesterday_commission_by_volume": (
            "close_yesterday_fee_amount",
            "close_yesterday_commission_amount",
            "CloseYesterdayRatioByVolume",
        ),
    }

    def __init__(self, **kwargs):
        kwargs = dict(kwargs)
        if "mult" in kwargs:
            _finite_number(kwargs["mult"], "option_multiplier_invalid", positive=True)
        for canonical, aliases in self._FEE_ALIASES.items():
            values = [
                (canonical, kwargs[canonical])
                for _ in (0,)
                if canonical in kwargs and kwargs[canonical] not in (None, "")
            ]
            values.extend(
                (alias, kwargs[alias])
                for alias in aliases
                if alias in kwargs and kwargs[alias] not in (None, "")
            )
            if values:
                numbers = [
                    (
                        name,
                        _finite_number(value, "option_fee_alias_invalid"),
                    )
                    for name, value in values
                ]
                first = numbers[0][1]
                if any(number != first for _, number in numbers[1:]):
                    raise OptionAccountingError(
                        "option_fee_alias_conflict",
                        "option_fee_alias_conflict: contradictory fee aliases",
                    )
                if canonical not in kwargs or kwargs[canonical] in (None, ""):
                    kwargs[canonical] = values[0][1]

        super().__init__(**kwargs)
        _finite_number(self.get_param("mult"), "option_multiplier_invalid", positive=True)
        style = str(self.get_param("premium_style") or "").strip().lower()
        if style not in {"premium", "premium_style", "premium-style"}:
            raise OptionAccountingError(
                "option_premium_style_required",
                "option_premium_style_required: only explicit premium-style options are supported",
            )
        self._premium_style = "premium"
        self._seller_margin_evidence = copy.deepcopy(self.get_param("seller_margin_evidence"))
        self._evidence_scope = copy.deepcopy(self.get_param("evidence_scope"))

    @property
    def seller_margin_source_kind(self) -> str | None:
        evidence = self._seller_margin_evidence
        if isinstance(evidence, CtpOptionSellerMarginEvidence):
            return evidence.source_kind.strip().lower()
        if isinstance(evidence, Mapping):
            return (
                str(_lookup(evidence, "source_kind", "evidence_kind", "provenance", "source") or "")
                .strip()
                .lower()
                or None
            )
        return None

    @property
    def seller_margin_is_synthetic(self) -> bool:
        return self.seller_margin_source_kind in {"synthetic", "offline", "fixture", "test"}

    def validate_seller_margin_evidence(self, *, now: _dt.datetime | None = None) -> dict[str, Any]:
        return validate_seller_margin_evidence(
            self._seller_margin_evidence,
            expected_scope=self._evidence_scope,
            now=now,
        )

    def seller_margin_status(self) -> str:
        if self._seller_margin_evidence is None:
            return "BLOCKED_MISSING"
        try:
            evidence = self.validate_seller_margin_evidence()
        except OptionAccountingError:
            return "BLOCKED_INVALID"
        if evidence["source_kind"] in {"synthetic", "offline", "fixture", "test"}:
            return "SYNTHETIC_OFFLINE_ONLY"
        return "STRUCTURALLY_VALID_UNVERIFIED"

    def _fee_pair(self, role: str | None) -> tuple[float, float]:
        role_text = str(role or "open").strip().lower().replace("-", "_")
        if role_text in {"open", "opened"}:
            prefix = "open"
        elif role_text in {"close_today", "closetoday"}:
            prefix = "close_today"
        elif role_text in {"close_yesterday", "closeyesterday"}:
            prefix = "close_yesterday"
        elif role_text in {"close", "closed"}:
            prefix = "close"
        elif role_text in {"maker", "taker"}:
            prefix = "open"
        else:
            raise OptionAccountingError(
                "option_fee_role_unknown", f"option_fee_role_unknown: unsupported role {role!r}"
            )

        money = self.get_param(f"{prefix}_commission_by_money")
        volume = self.get_param(f"{prefix}_commission_by_volume")
        if prefix == "close_yesterday" and money is None and volume is None:
            # Older CTP metadata has one close dimension.  Inheriting a fully
            # specified close pair is explicit and keeps that compatibility;
            # a partially specified pair still fails closed.
            money = self.get_param("close_commission_by_money")
            volume = self.get_param("close_commission_by_volume")
        if money is None or volume is None:
            raise OptionAccountingError(
                f"option_fee_{prefix}_incomplete",
                f"option_fee_{prefix}_incomplete: ByMoney and ByVolume are both required",
            )
        money = _finite_number(money, f"option_fee_{prefix}_invalid")
        volume = _finite_number(volume, f"option_fee_{prefix}_invalid")
        if money < 0.0 or volume < 0.0:
            raise OptionAccountingError(
                f"option_fee_{prefix}_invalid",
                f"option_fee_{prefix}_invalid: option fees cannot be negative",
            )
        return money, volume

    def _option_price(self, price: Any) -> float:
        return _finite_number(price, "option_price_invalid", positive=True)

    def _valuation_price(self, price: Any) -> float:
        value = _finite_number(price, "option_valuation_price_invalid")
        if value < 0.0:
            raise OptionAccountingError(
                "option_valuation_price_invalid",
                "option_valuation_price_invalid: valuation price cannot be negative",
            )
        return value

    def _option_size(self, size: Any) -> float:
        value = _finite_number(size, "option_size_invalid")
        if value < 0.0:
            value = abs(value)
        return value

    @staticmethod
    def _is_buy_side(is_buy: Any = True, side: Any = None) -> bool:
        value = side if side is not None else is_buy
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"buy", "b", "long", "1", "true"}:
                return True
            if text in {"sell", "s", "short", "0", "false"}:
                return False
            raise OptionAccountingError("option_side_unknown", f"option_side_unknown: {value!r}")
        return bool(value)

    @staticmethod
    def _role_text(role: Any) -> str:
        return str(role or "open").strip().lower().replace("-", "_")

    def _seller_margin_per_unit(self, price: Any = None, quantity: Any = None) -> float:
        evidence = self.validate_seller_margin_evidence()
        if evidence["source_kind"] not in {"synthetic", "offline", "fixture", "test"}:
            raise OptionAccountingError(
                "seller_margin_evidence_unverified",
                "seller_margin_evidence_unverified: no trusted SDK total-margin issuer is available",
            )
        if quantity is not None and not math.isclose(
            float(quantity), evidence["quantity"], rel_tol=0.0, abs_tol=1e-12
        ):
            raise OptionAccountingError(
                "seller_margin_quantity_unapproved",
                "seller_margin_quantity_unapproved: evidence covers a different quantity",
            )
        if price is not None and isinstance(evidence["price_basis"], Mapping):
            sourced_price = _lookup(
                evidence["price_basis"],
                "option_price",
                "premium_price",
                "input_price",
                "price",
            )
            if sourced_price not in (None, ""):
                sourced_price = _finite_number(
                    sourced_price,
                    "seller_margin_price_basis_invalid",
                    positive=True,
                )
                requested_price = self._option_price(price)
                if not math.isclose(requested_price, sourced_price, rel_tol=0.0, abs_tol=1e-12):
                    raise OptionAccountingError(
                        "seller_margin_price_scope_mismatch",
                        "seller_margin_price_scope_mismatch: evidence price differs from order",
                    )
        return _finite_result(
            evidence["total_margin"] / evidence["quantity"],
            "seller_margin_unit_nonfinite",
        )

    def getoperationcost(self, size, price, is_buy=None, *, side=None, role="open"):
        """Return premium cost or an approved opening seller margin."""
        quantity = self._option_size(size)
        if quantity == 0.0:
            return 0.0
        price_value = self._option_price(price)
        signed_size = _finite_number(size, "option_size_invalid")
        if side is not None and is_buy is not None:
            if self._is_buy_side(is_buy) != self._is_buy_side(side):
                raise OptionAccountingError(
                    "option_side_conflict",
                    "option_side_conflict: is_buy and side disagree",
                )
        if is_buy is None and side is None:
            is_buy = signed_size >= 0.0
        elif signed_size < 0.0 and (
            (side is None and self._is_buy_side(is_buy))
            or (side is not None and self._is_buy_side(side))
        ):
            raise OptionAccountingError(
                "option_side_conflict",
                "option_side_conflict: negative size cannot be an explicit buy",
            )
        is_buy = self._is_buy_side(is_buy, side)
        role_text = self._role_text(role)
        if role_text not in {
            "open",
            "opened",
            "close",
            "closed",
            "close_today",
            "closetoday",
            "close_yesterday",
            "closeyesterday",
        }:
            raise OptionAccountingError(
                "option_accounting_role_unknown",
                f"option_accounting_role_unknown: unsupported role {role!r}",
            )
        if role_text not in {"open", "opened"}:
            return _finite_result(
                quantity * price_value * self.get_param("mult"),
                "option_cost_nonfinite",
            )
        if is_buy:
            return _finite_result(
                quantity * price_value * self.get_param("mult"),
                "option_cost_nonfinite",
            )
        return _finite_result(
            quantity * self._seller_margin_per_unit(price_value, quantity),
            "option_cost_nonfinite",
        )

    def getpremiumvalue(self, size, price):
        """Return the premium transaction value for any execution side.

        Opening short risk uses a separately sourced margin value in
        :meth:`getoperationcost`.  A broker fill's executed value is always
        the traded premium, regardless of whether that fill opens or closes a
        long or short position.
        """
        quantity = self._option_size(size)
        price_value = self._option_price(price)
        return _finite_result(
            quantity * price_value * self.get_param("mult"),
            "option_execution_value_invalid",
        )

    def getsize(self, price, cash):
        """Return buyer quantity using premium plus the complete open fee."""
        price_value = self._option_price(price)
        available = max(_finite_number(cash, "option_cash_invalid"), 0.0)
        unit_premium = _finite_result(price_value * self.get_param("mult"), "option_cost_nonfinite")
        money_fee, volume_fee = self._fee_pair("open")
        unit_fee = _finite_result(unit_premium * money_fee + volume_fee, "option_fee_nonfinite")
        if unit_premium + unit_fee <= 0.0:
            return 0
        quantity = _finite_result(available // (unit_premium + unit_fee), "option_size_nonfinite")
        return int(quantity)

    def getvaluesize(self, size, price):
        """Return signed option position value at a mark price."""
        return _finite_result(
            _finite_number(size, "option_size_invalid")
            * self._valuation_price(price)
            * self.get_param("mult"),
            "option_value_nonfinite",
        )

    def getvalue(self, position, price):
        """Return signed position value; shorts remain negative."""
        return self.getvaluesize(position.size, price)

    def _getcommission(self, size, price, pseudoexec, role=None):
        _ = pseudoexec
        quantity = self._option_size(size)
        if quantity == 0.0:
            return 0.0
        price_value = self._option_price(price)
        money_fee, volume_fee = self._fee_pair(role)
        return _finite_result(
            quantity * (price_value * self.get_param("mult") * money_fee + volume_fee),
            "option_fee_nonfinite",
        )

    def profitandloss(self, size, price, newprice):
        """Return linear signed option PnL."""
        return _finite_result(
            _finite_number(size, "option_size_invalid")
            * (self._valuation_price(newprice) - self._valuation_price(price))
            * self.get_param("mult"),
            "option_pnl_nonfinite",
        )

    def cashadjust(self, size, price, newprice):
        """Premium-style options settle through execution; no mark cash flow."""
        _ = size, price, newprice
        return 0.0

    def get_margin(self, price):
        """Return only an explicitly sourced seller margin per contract."""
        return self._seller_margin_per_unit(price)

    def accounting_projection(self, size, price, *, is_buy=True, role="open") -> dict[str, Any]:
        """Return a reviewable single-leg projection without changing cash."""
        quantity = self._option_size(size)
        premium = _finite_result(
            quantity * self._option_price(price) * self.get_param("mult"),
            "option_value_nonfinite",
        )
        commission = self.getcommission(quantity, price, role=role)
        role_text = self._role_text(role)
        is_open = role_text in {"open", "opened"}
        if role_text not in {
            "open",
            "opened",
            "close",
            "closed",
            "close_today",
            "closetoday",
            "close_yesterday",
            "closeyesterday",
        }:
            raise OptionAccountingError(
                "option_accounting_role_unknown",
                f"option_accounting_role_unknown: unsupported role {role!r}",
            )
        if is_open and self._is_buy_side(is_buy):
            margin = 0.0
            cashflow = -(premium + commission)
            premium_cashflow = -premium
            source = "buyer_premium"
        elif is_open:
            margin = _finite_result(
                self._seller_margin_per_unit(price, quantity) * quantity,
                "option_margin_nonfinite",
            )
            cashflow = premium - commission
            premium_cashflow = premium
            source = self.seller_margin_status()
        else:
            margin = 0.0
            premium_cashflow = -premium if self._is_buy_side(is_buy) else premium
            cashflow = premium_cashflow - commission
            source = "closing_premium"
        return {
            "quantity": quantity,
            "premium": premium,
            "premium_cashflow": premium_cashflow,
            "margin": margin,
            "commission": commission,
            "cashflow": cashflow,
            "cashadjust": 0.0,
            "source": source,
        }


# Names used by the surrounding CTP examples and by older integration code.
ComminfoCtpOptionPremium = CtpOptionPremium
CtpOptionComminfo = CtpOptionPremium

__all__ = [
    "CtpOptionPremium",
    "ComminfoCtpOptionPremium",
    "CtpOptionComminfo",
    "CtpOptionSellerMarginEvidence",
    "OptionAccountingError",
    "validate_seller_margin_evidence",
]
