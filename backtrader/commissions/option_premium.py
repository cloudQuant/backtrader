"""Provider-neutral premium-style option accounting.

A long option consumes premium, while a short option needs an authoritative
pre-fee margin observation. This module performs local single-leg accounting
only; it does not reserve cash or maintain a live account ledger.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from ..comminfo import CommInfoBase
from ..parameters import ParameterDescriptor

_HEDGE_CLASSES = frozenset({"speculation", "arbitrage", "hedge"})


class OptionAccountingError(ValueError):
    """Raised when option accounting facts are missing or inconsistent."""

    def __init__(self, code: str, message: str | None = None):
        self.code = str(code)
        super().__init__(message or self.code)


def _finite_number(value: Any, code: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise OptionAccountingError(code, f"{code}: boolean is not numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OptionAccountingError(code, f"{code}: expected a finite number") from exc
    if not math.isfinite(number) or (positive and number <= 0.0):
        raise OptionAccountingError(code, f"{code}: expected a finite{' positive' if positive else ''} number")
    return number


def _finite_result(value: Any, code: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OptionAccountingError(code, f"{code}: result is not numeric") from exc
    if not math.isfinite(number):
        raise OptionAccountingError(code, f"{code}: result is not finite")
    return number


def _execution_rule_snapshot_types():
    """Load the neutral SDK snapshot contract only when this class is used."""
    try:
        from bt_api_py.facade_protocol import (
            CommissionRuleFacts,
            ExecutionRulesSnapshotPort,
            InstrumentExecutionFacts,
            InstrumentExecutionRulesSnapshot,
            MarketInstrumentKey,
        )
    except Exception as exc:
        raise OptionAccountingError("option_sdk_snapshot_contract_unavailable") from exc
    return (
        CommissionRuleFacts,
        ExecutionRulesSnapshotPort,
        InstrumentExecutionFacts,
        InstrumentExecutionRulesSnapshot,
        MarketInstrumentKey,
    )


def _validated_execution_snapshot(
    port: Any,
    instrument: Any,
    hedge_class: Any,
    snapshot: Any,
    *,
    now: _dt.datetime | None = None,
):
    (
        _fee_type,
        port_type,
        facts_type,
        snapshot_type,
        instrument_type,
    ) = _execution_rule_snapshot_types()
    if type(instrument) is not instrument_type:
        raise OptionAccountingError("option_instrument_key_unavailable")
    if type(hedge_class) is not str or hedge_class not in _HEDGE_CLASSES:
        raise OptionAccountingError("option_hedge_class_unavailable")
    if not isinstance(port, port_type):
        raise OptionAccountingError("option_sdk_snapshot_port_unavailable")
    if type(snapshot) is not snapshot_type:
        raise OptionAccountingError("option_sdk_snapshot_unavailable")
    try:
        snapshot_type.__post_init__(snapshot)
    except Exception as exc:
        raise OptionAccountingError("option_sdk_snapshot_invalid") from exc
    facts = snapshot.facts
    if type(facts) is facts_type:
        try:
            facts_type.__post_init__(facts)
        except Exception as exc:
            raise OptionAccountingError("option_contract_facts_invalid") from exc
    if (
        type(facts) is not facts_type
        or facts.status != "available"
        or facts.asset_kind != "option"
        or facts.option_right not in {"call", "put"}
        or facts.option_strike is None
        or facts.option_expiry is None
        or facts.option_premium_style != "premium"
        or facts.contract_multiplier is None
        or facts.session_generation is None
        or facts.source_ref is None
        or facts.observed_at_utc is None
        or facts.expires_at_utc is None
        or facts.instrument != instrument
        or facts.hedge_class != hedge_class
    ):
        raise OptionAccountingError("option_contract_facts_unavailable")
    clock = now or _dt.datetime.now(_dt.timezone.utc)
    if (
        type(clock) is not _dt.datetime
        or clock.tzinfo is None
        or clock.utcoffset() != _dt.timedelta(0)
    ):
        raise OptionAccountingError("option_rule_clock_invalid")
    clock = clock.astimezone(_dt.timezone.utc)
    if facts.observed_at_utc > clock:
        raise OptionAccountingError("option_rule_observation_from_future")
    if facts.expires_at_utc <= clock:
        raise OptionAccountingError("option_rule_evidence_expired")
    try:
        current = port.validate_execution_rules_snapshot(snapshot, now_utc=clock)
    except Exception as exc:
        raise OptionAccountingError("option_rule_snapshot_currentness_unavailable") from exc
    if current is not True:
        raise OptionAccountingError("option_rule_snapshot_not_current")
    return facts


class OptionPremiumCommInfo(CommInfoBase):
    """Premium option accounting over neutral, source-bound SDK rule facts.

    This class retains Backtrader's ordinary premium, value, PnL and fee math.
    Contract and fee facts arrive through an SDK-issued
    ``InstrumentExecutionRulesSnapshot`` scoped to an explicit neutral hedge
    class and must pass its route-bound currentness check before use. Fee cash
    calculations additionally require verified currency provenance. The
    snapshot is accounting evidence, not a write capability. Seller margin
    remains unavailable until a neutral pre-fee margin fact can be consumed
    without double counting.
    """

    stocklike = ParameterDescriptor(default=True, type_=bool)
    commtype = ParameterDescriptor(default=CommInfoBase.COMM_FIXED, type_=int)
    percabs = ParameterDescriptor(default=True, type_=bool)
    premium_style = ParameterDescriptor(default=None)
    option_type = ParameterDescriptor(default=None)
    instrument_key = ParameterDescriptor(default=None)
    hedge_class = ParameterDescriptor(default=None)
    execution_rules_snapshot_port = ParameterDescriptor(default=None)

    _RETIRED_FEE_INPUTS = frozenset(
        {
            "open_commission_by_money",
            "open_commission_by_volume",
            "close_commission_by_money",
            "close_commission_by_volume",
            "close_today_commission_by_money",
            "close_today_commission_by_volume",
            "close_yesterday_commission_by_money",
            "close_yesterday_commission_by_volume",
            "open_fee_rate",
            "open_commission_rate",
            "open_fee_amount",
            "open_commission_amount",
            "close_fee_rate",
            "close_commission_rate",
            "close_fee_amount",
            "close_commission_amount",
            "close_today_fee_rate",
            "close_today_commission_rate",
            "close_today_fee_amount",
            "close_today_commission_amount",
            "close_yesterday_fee_rate",
            "close_yesterday_commission_rate",
            "close_yesterday_fee_amount",
            "close_yesterday_commission_amount",
        }
    )
    _RETIRED_MARGIN_INPUTS = frozenset({"seller_margin_evidence", "evidence_scope"})

    def __init__(self, **kwargs):
        kwargs = dict(kwargs)
        for name in self._RETIRED_FEE_INPUTS:
            if name in kwargs:
                value = kwargs.pop(name)
                if value not in (None, ""):
                    raise OptionAccountingError("option_fee_sdk_facts_required")
        for name in self._RETIRED_MARGIN_INPUTS:
            if name in kwargs:
                value = kwargs.pop(name)
                if value not in (None, ""):
                    raise OptionAccountingError("seller_margin_provider_mapping_retired")

        if "execution_rule_decision" in kwargs:
            kwargs.pop("execution_rule_decision")
            raise OptionAccountingError("option_rule_sdk_snapshot_required")
        port = kwargs.get("execution_rules_snapshot_port")
        instrument = kwargs.get("instrument_key")
        hedge_class = kwargs.get("hedge_class")
        if hedge_class is None:
            raise OptionAccountingError("option_hedge_class_required")
        if port is None or instrument is None:
            raise OptionAccountingError("option_rule_sdk_snapshot_required")
        _, port_type, _, _, instrument_type = _execution_rule_snapshot_types()
        if type(instrument) is not instrument_type:
            raise OptionAccountingError("option_instrument_key_unavailable")
        if type(hedge_class) is not str or hedge_class not in _HEDGE_CLASSES:
            raise OptionAccountingError("option_hedge_class_unavailable")
        if not isinstance(port, port_type):
            raise OptionAccountingError("option_sdk_snapshot_port_unavailable")
        try:
            snapshot = port.execution_rules_snapshot(
                instrument,
                hedge_class=hedge_class,
            )
        except Exception as exc:
            raise OptionAccountingError("option_rule_snapshot_unavailable") from exc
        facts = _validated_execution_snapshot(port, instrument, hedge_class, snapshot)
        multiplier = _finite_number(
            facts.contract_multiplier, "option_multiplier_invalid", positive=True
        )
        if "mult" in kwargs:
            supplied_multiplier = _finite_number(
                kwargs["mult"], "option_multiplier_invalid", positive=True
            )
            if supplied_multiplier != multiplier:
                raise OptionAccountingError("option_multiplier_scope_mismatch")
        else:
            kwargs["mult"] = multiplier

        supplied_style = kwargs.get("premium_style")
        if supplied_style not in (None, ""):
            style = str(supplied_style).strip().lower().replace("-", "_")
            if style not in {"premium", "premium_style"}:
                raise OptionAccountingError("option_premium_style_scope_mismatch")
        else:
            kwargs["premium_style"] = facts.option_premium_style
        supplied_type = kwargs.get("option_type")
        if supplied_type not in (None, ""):
            option_type = str(supplied_type).strip().lower()
            if option_type != facts.option_right:
                raise OptionAccountingError("option_contract_right_scope_mismatch")
        else:
            kwargs["option_type"] = facts.option_right

        super().__init__(**kwargs)
        self._execution_rules_snapshot_port = port
        self._instrument_key = instrument
        self._hedge_class = hedge_class
        self._execution_rules_snapshot = snapshot
        self._execution_facts = facts
        _finite_number(self.get_param("mult"), "option_multiplier_invalid", positive=True)
        self._premium_style = "premium"

    @property
    def fee_evidence_status(self) -> str:
        try:
            for role in ("open", "close", "close_today", "close_yesterday"):
                self._fee_pair(role)
            return "AVAILABLE"
        except OptionAccountingError:
            return "UNAVAILABLE"

    def seller_margin_status(self) -> str:
        return "UNAVAILABLE_NEUTRAL_PRE_FEE_MARGIN_FACT_MISSING"

    def _current_execution_facts(self):
        facts = _validated_execution_snapshot(
            self._execution_rules_snapshot_port,
            self._instrument_key,
            self._hedge_class,
            self._execution_rules_snapshot,
        )
        if facts is not self._execution_facts:
            raise OptionAccountingError("option_rule_facts_changed")
        return facts

    def refresh_execution_rules_snapshot(self) -> None:
        """Explicitly replace the pinned snapshot through its selected SDK port."""
        try:
            snapshot = self._execution_rules_snapshot_port.execution_rules_snapshot(
                self._instrument_key,
                hedge_class=self._hedge_class,
            )
        except Exception as exc:
            raise OptionAccountingError("option_rule_snapshot_unavailable") from exc
        facts = _validated_execution_snapshot(
            self._execution_rules_snapshot_port,
            self._instrument_key,
            self._hedge_class,
            snapshot,
        )
        multiplier = _finite_number(
            facts.contract_multiplier, "option_multiplier_invalid", positive=True
        )
        if multiplier != self.get_param("mult"):
            raise OptionAccountingError("option_multiplier_scope_mismatch")
        if (
            facts.option_right != self._execution_facts.option_right
            or facts.option_strike != self._execution_facts.option_strike
            or facts.option_expiry != self._execution_facts.option_expiry
            or facts.option_premium_style != self._execution_facts.option_premium_style
        ):
            raise OptionAccountingError("option_contract_right_scope_mismatch")
        self._execution_rules_snapshot = snapshot
        self._execution_facts = facts

    def _fee_pair(self, role: str | None) -> tuple[float, float]:
        role_text = str(role or "open").strip().lower().replace("-", "_")
        if role_text in {"open", "opened", "maker", "taker"}:
            prefix = "open"
        elif role_text in {"close_today", "closetoday"}:
            prefix = "close_today"
        elif role_text in {"close_yesterday", "closeyesterday"}:
            prefix = "close_yesterday"
        elif role_text in {"close", "closed"}:
            prefix = "close"
        else:
            raise OptionAccountingError("option_fee_role_unknown")

        facts = self._current_execution_facts()
        fee_type = _execution_rule_snapshot_types()[0]
        fee = next((item for item in facts.commission_rules if item.role == prefix), None)
        if type(fee) is not fee_type:
            raise OptionAccountingError("option_fee_evidence_unavailable")
        if (
            fee.currency_status != "verified"
            or fee.currency is None
            or fee.source_ref is None
            or fee.session_generation != facts.session_generation
            or fee.currency_session_generation != facts.session_generation
            or fee.currency_source_ref is None
            or facts.price_currency_status != "verified"
            or facts.price_currency is None
            or facts.price_currency != fee.currency
            or facts.price_currency_session_generation != facts.session_generation
            or facts.price_currency_source_ref is None
        ):
            raise OptionAccountingError("option_fee_currency_evidence_unavailable")
        money = _finite_number(fee.by_money_rate, f"option_fee_{prefix}_unavailable")
        volume = _finite_number(fee.by_volume_amount, f"option_fee_{prefix}_unavailable")
        if money < 0.0 or volume < 0.0:
            raise OptionAccountingError(f"option_fee_{prefix}_invalid")
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
        _ = price, quantity
        raise OptionAccountingError("seller_margin_neutral_evidence_unavailable")

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
        _ = price
        raise OptionAccountingError("seller_margin_neutral_evidence_unavailable")

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


__all__ = [
    "OptionPremiumCommInfo",
    "OptionAccountingError",
]
