"""Independent robust-basis strategy for OKX/Binance perpetual contracts.

The alpha and pair state in this file belong only to example 012_1. Exchange
request mapping, authentication, and durable order recovery remain in the
public ``BtApiStore``/``BtApiBroker`` path.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import math
import os
import random
from statistics import median
import time
from typing import Callable, Deque, Dict, Mapping, Optional, Sequence, Tuple

import backtrader as bt
from bt_api_py import Freshness

from bt_api_py.cross_venue import (
    CostBreakdown,
    CrossVenueLeg as InstrumentRule,
    CrossVenueValueError as CrossExchangeValueError,
    ExecutableVWAP,
    FundingSnapshot as FundingState,
    InsufficientDepth,
    RealizedEconomics,
    ORDERBOOK_HEALTHY_CONTINUITY,
    aggregate_confirmed_fills,
    coerce_funding_snapshot as normalize_funding_state,
    decimal_value,
    executable_vwap,
    funding_settlement_count,
    quantity_lattice,
    realized_round_trip_economics,
    normalize_orderbook_evidence,
    round_trip_cost,
    signed_funding_cashflow,
)

VENUE_SYMBOLS = {"okx": "BTC-USDT-SWAP", "binance": "BTCUSDT"}
SYMBOL_VENUES = {symbol: venue for venue, symbol in VENUE_SYMBOLS.items()}
QUALIFICATION_METHOD = "ar1_intercept_bootstrap_tau_equilibrium_bound_v3"
BASIS_DEFINITION = "sell_mid_minus_buy_mid_time_aligned_l2_v3"
QUALIFICATION_CONFIDENCE_Z = Decimal("3")
QUALIFICATION_PVALUE_LIMIT = Decimal("0.005")
QUALIFICATION_BOOTSTRAP_REPLICATIONS = 999


def _sha256_payload(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _venue_symbols_sha256() -> str:
    return _sha256_payload(VENUE_SYMBOLS)


@dataclass(frozen=True)
class BasisModelQualification:
    """Immutable provenance and validity gate for the mean-reversion model."""

    basis_series_sha256: str
    method: str
    sample_count: int
    lag1_coefficient: Decimal
    ar1_intercept: Decimal
    equilibrium_basis: Decimal
    equilibrium_upper_confidence: Decimal
    half_life_seconds: Decimal
    maximum_half_life_seconds: Decimal
    qualified: bool
    valid_from_epoch: Decimal
    valid_until_epoch: Decimal
    structural_break_detected: bool = False
    rejection_reason: str = ""
    source_data_sha256: Optional[str] = None
    provenance: str = ""
    sample_interval_seconds: Decimal = Decimal("0")
    lag1_upper_confidence: Decimal = Decimal("999999")
    unit_root_pvalue: Decimal = Decimal("1")
    bootstrap_replications: int = 0
    basis_definition: str = ""
    venue_symbols_sha256: Optional[str] = None
    qualification_contract_sha256: Optional[str] = None
    buy_venue: str = ""
    sell_venue: str = ""

    def __post_init__(self) -> None:
        digest = str(self.basis_series_sha256)
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("basis_series_sha256 must be a lowercase SHA-256 digest")
        for digest_name in (
            "source_data_sha256",
            "venue_symbols_sha256",
            "qualification_contract_sha256",
        ):
            optional_digest = getattr(self, digest_name)
            if optional_digest is None:
                continue
            digest_value = str(optional_digest)
            if len(digest_value) != 64 or any(
                char not in "0123456789abcdef" for char in digest_value
            ):
                raise ValueError(f"{digest_name} must be a lowercase SHA-256 digest")
        if not str(self.method).strip():
            raise ValueError("model qualification method is required")
        if not isinstance(self.qualified, bool) or not isinstance(
            self.structural_break_detected, bool
        ):
            raise ValueError("qualification flags must be booleans")
        if not isinstance(self.provenance, str) or not isinstance(self.rejection_reason, str):
            raise ValueError("qualification provenance and rejection reason must be strings")
        if self.buy_venue not in VENUE_SYMBOLS or self.sell_venue not in VENUE_SYMBOLS:
            raise ValueError("qualification direction must use configured venues")
        if self.buy_venue == self.sell_venue:
            raise ValueError("qualification direction must cross venues")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 0
        ):
            raise ValueError("sample_count must be a nonnegative integer")
        for name in (
            "lag1_coefficient",
            "ar1_intercept",
            "equilibrium_basis",
            "equilibrium_upper_confidence",
            "half_life_seconds",
            "maximum_half_life_seconds",
            "valid_from_epoch",
            "valid_until_epoch",
            "sample_interval_seconds",
            "lag1_upper_confidence",
            "unit_root_pvalue",
        ):
            object.__setattr__(self, name, decimal_value(getattr(self, name), name))
        if self.half_life_seconds < 0 or self.maximum_half_life_seconds <= 0:
            raise ValueError("half-life values must be nonnegative with a positive maximum")
        if not Decimal(0) <= self.unit_root_pvalue <= Decimal(1):
            raise ValueError("unit_root_pvalue must be in [0, 1]")
        if self.lag1_upper_confidence < abs(self.lag1_coefficient):
            raise ValueError("lag1_upper_confidence cannot be below the fitted magnitude")
        if self.equilibrium_upper_confidence < self.equilibrium_basis:
            raise ValueError("equilibrium upper confidence must cover the fitted equilibrium")
        if self.valid_until_epoch <= self.valid_from_epoch:
            raise ValueError("model validity interval is empty")
        if (
            isinstance(self.bootstrap_replications, bool)
            or not isinstance(self.bootstrap_replications, int)
            or self.bootstrap_replications < 0
        ):
            raise ValueError("bootstrap_replications must be a nonnegative integer")
        if self.qualified and self.rejection_reason:
            raise ValueError("a qualified artifact cannot carry a rejection reason")

    def rejection_at(
        self,
        now_epoch,
        *,
        minimum_samples: int,
        maximum_half_life_seconds,
        expected_contract_sha256: Optional[str] = None,
        expected_direction: Optional[Tuple[str, str]] = None,
    ) -> Optional[str]:
        now = decimal_value(now_epoch, "qualification_now_epoch")
        maximum = decimal_value(maximum_half_life_seconds, "maximum_half_life_seconds")
        if now < self.valid_from_epoch:
            return "model_not_yet_valid"
        if now >= self.valid_until_epoch:
            return "model_qualification_expired"
        if self.sample_count < minimum_samples:
            return "model_sample_count"
        if self.method != QUALIFICATION_METHOD:
            return "model_method"
        if not self.source_data_sha256 or not self.provenance.strip():
            return "model_provenance"
        if self.sample_interval_seconds <= 0:
            return "model_sample_interval"
        if self.basis_definition != BASIS_DEFINITION:
            return "model_basis_definition"
        if expected_direction != (self.buy_venue, self.sell_venue):
            return "model_direction_binding"
        if self.venue_symbols_sha256 != _venue_symbols_sha256():
            return "model_venue_binding"
        if (
            expected_contract_sha256 is None
            or self.qualification_contract_sha256 != expected_contract_sha256
        ):
            return "model_contract_binding"
        if self.structural_break_detected:
            return "model_structural_break"
        if abs(self.lag1_coefficient) >= 1 or self.lag1_upper_confidence >= 1:
            return "model_nonstationary"
        if (
            self.bootstrap_replications < QUALIFICATION_BOOTSTRAP_REPLICATIONS
            or self.unit_root_pvalue > QUALIFICATION_PVALUE_LIMIT
        ):
            return "model_unit_root_confidence"
        if (
            self.half_life_seconds > maximum
            or self.half_life_seconds > self.maximum_half_life_seconds
        ):
            return "model_half_life"
        if not self.qualified:
            return self.rejection_reason or "model_not_qualified"
        return None

    def as_dict(self) -> Mapping[str, object]:
        return {
            "basis_series_sha256": self.basis_series_sha256,
            "source_data_sha256": self.source_data_sha256,
            "provenance": self.provenance,
            "method": self.method,
            "sample_count": self.sample_count,
            "lag1_coefficient": str(self.lag1_coefficient),
            "ar1_intercept": str(self.ar1_intercept),
            "equilibrium_basis": str(self.equilibrium_basis),
            "equilibrium_upper_confidence": str(self.equilibrium_upper_confidence),
            "half_life_seconds": str(self.half_life_seconds),
            "maximum_half_life_seconds": str(self.maximum_half_life_seconds),
            "qualified": self.qualified,
            "valid_from_epoch": str(self.valid_from_epoch),
            "valid_until_epoch": str(self.valid_until_epoch),
            "structural_break_detected": self.structural_break_detected,
            "rejection_reason": self.rejection_reason,
            "sample_interval_seconds": str(self.sample_interval_seconds),
            "lag1_upper_confidence": str(self.lag1_upper_confidence),
            "unit_root_pvalue": str(self.unit_root_pvalue),
            "bootstrap_replications": self.bootstrap_replications,
            "basis_definition": self.basis_definition,
            "venue_symbols_sha256": self.venue_symbols_sha256,
            "qualification_contract_sha256": self.qualification_contract_sha256,
            "buy_venue": self.buy_venue,
            "sell_venue": self.sell_venue,
        }


def _fit_ar1(values: Sequence[Decimal], interval: Decimal):
    previous = values[:-1]
    current = values[1:]
    previous_mean = sum(previous) / Decimal(len(previous))
    current_mean = sum(current) / Decimal(len(current))
    denominator = sum((value - previous_mean) ** 2 for value in previous)
    if denominator <= 0:
        center = decimal_value(median(values), "basis_center")
        return (
            Decimal("999999"),
            Decimal(0),
            Decimal("999999"),
            Decimal("999999"),
            Decimal("999999"),
            center,
            center,
        )
    coefficient = (
        sum(
            (left - previous_mean) * (right - current_mean)
            for left, right in zip(previous, current)
        )
        / denominator
    )
    intercept = current_mean - coefficient * previous_mean
    residuals = [right - intercept - coefficient * left for left, right in zip(previous, current)]
    degrees = max(1, len(residuals) - 2)
    residual_variance = sum(value * value for value in residuals) / Decimal(degrees)
    standard_error = Decimal(str(math.sqrt(float(residual_variance / denominator))))
    tau_statistic = (
        (coefficient - Decimal(1)) / standard_error if standard_error > 0 else Decimal("-999999")
    )
    absolute = abs(coefficient)
    half_life = Decimal("999999")
    if absolute == 0:
        half_life = Decimal(0)
    elif absolute < 1:
        half_life = Decimal(str(-math.log(2) / math.log(float(absolute)))) * interval
    robust_center = decimal_value(median(values), "basis_center")
    deviations = [abs(value - robust_center) for value in values]
    robust_scale = decimal_value(median(deviations), "basis_mad") * Decimal("1.4826")
    if robust_scale == 0:
        robust_scale = Decimal("0.00000001")
    equilibrium = robust_center
    if abs(coefficient) < 1:
        equilibrium = intercept / (Decimal(1) - coefficient)
    effective_count = max(
        Decimal(1),
        Decimal(len(values))
        * (Decimal(1) - min(absolute, Decimal("0.999999")))
        / (Decimal(1) + min(absolute, Decimal("0.999999"))),
    )
    equilibrium_margin = (
        QUALIFICATION_CONFIDENCE_Z * robust_scale / Decimal(str(math.sqrt(float(effective_count))))
    )
    return (
        coefficient,
        intercept,
        half_life,
        absolute + QUALIFICATION_CONFIDENCE_Z * standard_error,
        tau_statistic,
        equilibrium,
        equilibrium + equilibrium_margin,
    )


def _unit_root_bootstrap_pvalue(
    values: Sequence[Decimal],
    observed_tau_statistic: Decimal,
    interval: Decimal,
    digest: str,
) -> Decimal:
    """Deterministic difference bootstrap under the unit-root null."""

    differences = [right - left for left, right in zip(values[:-1], values[1:])]
    rng = random.Random(int(digest[:16], 16))
    at_least_as_stationary = 0
    for _ in range(QUALIFICATION_BOOTSTRAP_REPLICATIONS):
        innovations = list(differences)
        rng.shuffle(innovations)
        simulated = [values[0]]
        for innovation in innovations:
            simulated.append(simulated[-1] + innovation)
        _, _, _, _, bootstrap_tau, _, _ = _fit_ar1(simulated, interval)
        if bootstrap_tau <= observed_tau_statistic:
            at_least_as_stationary += 1
    return Decimal(at_least_as_stationary + 1) / Decimal(QUALIFICATION_BOOTSTRAP_REPLICATIONS + 1)


def qualify_basis_model(
    samples: Sequence[object],
    *,
    sample_interval_seconds,
    maximum_half_life_seconds,
    valid_from_epoch,
    valid_until_epoch,
    buy_venue: str,
    sell_venue: str,
    minimum_samples: int = 120,
    structural_break_detected: Optional[bool] = None,
    source_data_sha256: Optional[str] = None,
    provenance: str = "",
    qualification_contract_sha256: Optional[str] = None,
) -> BasisModelQualification:
    """Fit a bounded AR(1) qualification artifact from historical basis samples.

    This helper is intended for an explicit research/qualification step.  The
    live engine only consumes the immutable returned artifact; it never invents
    a hash or silently qualifies its rolling live window.
    """

    values = tuple(decimal_value(value, "basis_sample") for value in samples)
    canonical = "\n".join(format(value, "f") for value in values).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    interval = decimal_value(sample_interval_seconds, "sample_interval_seconds")
    maximum = decimal_value(maximum_half_life_seconds, "maximum_half_life_seconds")
    if interval <= 0 or maximum <= 0:
        raise ValueError("sample interval and maximum half-life must be positive")
    if buy_venue not in VENUE_SYMBOLS or sell_venue not in VENUE_SYMBOLS or buy_venue == sell_venue:
        raise ValueError("qualification direction must cross configured venues")

    coefficient = Decimal("999999")
    intercept = Decimal(0)
    equilibrium = decimal_value(median(values), "basis_center") if values else Decimal(0)
    equilibrium_upper = equilibrium
    half_life = maximum * Decimal(10) + interval
    lag1_upper_confidence = Decimal("999999")
    tau_statistic = Decimal("999999")
    unit_root_pvalue = Decimal(1)
    reason = "model_sample_count"
    detected_break = bool(structural_break_detected)
    if len(values) >= 3:
        (
            coefficient,
            intercept,
            half_life,
            lag1_upper_confidence,
            tau_statistic,
            equilibrium,
            equilibrium_upper,
        ) = _fit_ar1(values, interval)
        if not coefficient.is_finite() or coefficient == Decimal("999999"):
            reason = "model_zero_variance"
        else:
            unit_root_pvalue = _unit_root_bootstrap_pvalue(values, tau_statistic, interval, digest)

        if structural_break_detected is None:
            midpoint = len(values) // 2
            first = values[:midpoint]
            second = values[midpoint:]
            first_center = decimal_value(median(first), "first_center")
            second_center = decimal_value(median(second), "second_center")
            first_mad = decimal_value(
                median(abs(value - first_center) for value in first),
                "first_half_mad",
            )
            second_mad = decimal_value(
                median(abs(value - second_center) for value in second),
                "second_half_mad",
            )
            within_regime_scale = max(first_mad, second_mad, Decimal("0.00000001"))
            detected_break = abs(second_center - first_center) > within_regime_scale * Decimal(8)

        if detected_break:
            reason = "model_structural_break"
        elif not coefficient.is_finite() or abs(coefficient) >= 1 or lag1_upper_confidence >= 1:
            reason = "model_nonstationary"
        elif unit_root_pvalue > QUALIFICATION_PVALUE_LIMIT:
            reason = "model_unit_root_confidence"
        elif not half_life.is_finite() or half_life > maximum:
            reason = "model_half_life"
        elif len(values) < minimum_samples:
            reason = "model_sample_count"
        elif not source_data_sha256 or not provenance.strip():
            reason = "model_provenance"
        elif not qualification_contract_sha256:
            reason = "model_contract_binding"
        else:
            reason = ""

    qualified = reason == ""
    return BasisModelQualification(
        basis_series_sha256=digest,
        method=QUALIFICATION_METHOD,
        sample_count=len(values),
        lag1_coefficient=coefficient,
        ar1_intercept=intercept,
        equilibrium_basis=equilibrium,
        equilibrium_upper_confidence=equilibrium_upper,
        half_life_seconds=half_life,
        maximum_half_life_seconds=maximum,
        qualified=qualified,
        valid_from_epoch=decimal_value(valid_from_epoch),
        valid_until_epoch=decimal_value(valid_until_epoch),
        structural_break_detected=detected_break,
        rejection_reason=reason,
        source_data_sha256=source_data_sha256,
        provenance=provenance,
        sample_interval_seconds=interval,
        lag1_upper_confidence=lag1_upper_confidence,
        unit_root_pvalue=unit_root_pvalue,
        bootstrap_replications=QUALIFICATION_BOOTSTRAP_REPLICATIONS,
        basis_definition=BASIS_DEFINITION,
        venue_symbols_sha256=_venue_symbols_sha256(),
        qualification_contract_sha256=qualification_contract_sha256,
        buy_venue=buy_venue,
        sell_venue=sell_venue,
    )


@dataclass(frozen=True)
class BookState:
    venue: str
    bids: Tuple[Tuple[Decimal, Decimal], ...]
    asks: Tuple[Tuple[Decimal, Decimal], ...]
    exchange_time: Decimal
    receive_time: Decimal
    sequence: int
    previous_sequence: Optional[int] = None
    snapshot_or_delta: str = "snapshot"
    continuity_status: str = "unknown"
    stale: bool = False
    clock_domain_id: str = "process-monotonic"
    funding_rate: Decimal = Decimal(0)
    next_funding_time: Optional[Decimal] = None
    recovery_snapshot: bool = False


@dataclass(frozen=True)
class MidFrequencyRisk:
    quantity_base: Decimal = Decimal("0.01")
    zscore_window: int = 120
    minimum_samples: int = 120
    entry_zscore: Decimal = Decimal("3")
    exit_zscore: Decimal = Decimal("0.5")
    divergence_zscore: Decimal = Decimal("4")
    confirmations: int = 3
    persistence_seconds: Decimal = Decimal("5")
    minimum_interval_seconds: Decimal = Decimal("5")
    maximum_quote_age_seconds: Decimal = Decimal("2")
    maximum_venue_skew_seconds: Decimal = Decimal("0.75")
    maximum_holding_seconds: Decimal = Decimal("300")
    maximum_loss_bps: Decimal = Decimal("100")
    account_maximum_loss_bps: Decimal = Decimal("50")
    minimum_net_edge_bps: Decimal = Decimal("1")
    depth_fraction: Decimal = Decimal("0.25")
    exit_reserve_bps: Decimal = Decimal("2")
    latency_reserve_bps: Decimal = Decimal("1")
    failure_reserve_bps: Decimal = Decimal("2")
    model_buffer_bps: Decimal = Decimal("3")
    minimum_qualification_samples: int = 120
    maximum_half_life_seconds: Decimal = Decimal("120")
    entry_deadline_seconds: Decimal = Decimal("2")
    hedge_deadline_seconds: Decimal = Decimal("2")
    cancel_deadline_seconds: Decimal = Decimal("1")
    pair_deadline_seconds: Decimal = Decimal("5")
    flatten_deadline_seconds: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        decimal_fields = (
            "quantity_base",
            "entry_zscore",
            "exit_zscore",
            "divergence_zscore",
            "persistence_seconds",
            "minimum_interval_seconds",
            "maximum_quote_age_seconds",
            "maximum_venue_skew_seconds",
            "maximum_holding_seconds",
            "maximum_loss_bps",
            "account_maximum_loss_bps",
            "minimum_net_edge_bps",
            "depth_fraction",
            "exit_reserve_bps",
            "latency_reserve_bps",
            "failure_reserve_bps",
            "model_buffer_bps",
            "maximum_half_life_seconds",
            "entry_deadline_seconds",
            "hedge_deadline_seconds",
            "cancel_deadline_seconds",
            "pair_deadline_seconds",
            "flatten_deadline_seconds",
        )
        for name in decimal_fields:
            value = decimal_value(getattr(self, name), name)
            object.__setattr__(self, name, value)
            if value < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.quantity_base <= 0 or self.maximum_quote_age_seconds <= 0:
            raise ValueError("quantity and quote age must be positive")
        if self.account_maximum_loss_bps <= 0:
            raise ValueError("account_maximum_loss_bps must be positive")
        if not 0 < self.depth_fraction <= 1:
            raise ValueError("depth_fraction must be in (0, 1]")
        if self.zscore_window < 3 or not 3 <= self.minimum_samples <= self.zscore_window:
            raise ValueError("invalid robust deviation window")
        if self.confirmations < 1:
            raise ValueError("confirmations must be positive")
        if self.minimum_qualification_samples < 3:
            raise ValueError("minimum_qualification_samples must be at least three")
        if not (
            0 < self.entry_deadline_seconds <= self.pair_deadline_seconds
            and 0 < self.hedge_deadline_seconds <= self.pair_deadline_seconds
            and 0 < self.cancel_deadline_seconds <= self.pair_deadline_seconds
            and self.flatten_deadline_seconds > 0
        ):
            raise ValueError("execution deadlines must be positive and bounded")


def qualification_contract_sha256(
    rules: Mapping[str, InstrumentRule],
    risk: MidFrequencyRisk,
    buy_venue: str,
    sell_venue: str,
) -> str:
    """Bind a qualification artifact to the traded pair, basis and risk model."""

    if buy_venue not in VENUE_SYMBOLS or sell_venue not in VENUE_SYMBOLS or buy_venue == sell_venue:
        raise ValueError("qualification direction must cross configured venues")
    if set(rules) != set(VENUE_SYMBOLS):
        raise ValueError("qualification rules must contain exactly okx and binance")

    rule_payload = {
        venue: {
            "symbol": VENUE_SYMBOLS[venue],
            "multiplier": str(rule.multiplier),
            "quantity_step": str(rule.quantity_step),
            "minimum_quantity": str(rule.minimum_quantity),
            "minimum_notional": str(rule.minimum_notional),
            "price_tick": str(rule.price_tick),
            "taker_fee": str(rule.taker_fee),
            "funding_interval_seconds": str(rule.funding_interval_seconds),
        }
        for venue, rule in sorted(rules.items())
    }
    risk_payload = {key: str(value) for key, value in asdict(risk).items()}
    return _sha256_payload(
        {
            "schema": 3,
            "basis_definition": BASIS_DEFINITION,
            "venue_symbols": VENUE_SYMBOLS,
            "rules": rule_payload,
            "risk": risk_payload,
            "direction": {"buy_venue": buy_venue, "sell_venue": sell_venue},
        }
    )


@dataclass(frozen=True)
class PairIntent:
    long_venue: str
    short_venue: str
    quantity_base: Decimal
    buy_price: Decimal
    sell_price: Decimal
    zscore: Decimal
    basis: Decimal
    entry_executable_basis: Decimal
    expected_exit_basis: Decimal
    cost: CostBreakdown
    created_at: Decimal
    entry_buy: ExecutableVWAP
    entry_sell: ExecutableVWAP
    exit_sell_preview: ExecutableVWAP
    exit_buy_preview: ExecutableVWAP
    reason: str = "robust_deviation_and_net_edge"

    def as_dict(self) -> Mapping[str, object]:
        return {
            "long_venue": self.long_venue,
            "short_venue": self.short_venue,
            "quantity_base": str(self.quantity_base),
            "buy_price": str(self.buy_price),
            "sell_price": str(self.sell_price),
            "zscore": str(self.zscore),
            "basis": str(self.basis),
            "entry_executable_basis": str(self.entry_executable_basis),
            "expected_exit_basis": str(self.expected_exit_basis),
            "cost": self.cost.as_dict(),
            "created_at": str(self.created_at),
            "entry_buy": self.entry_buy.as_dict(),
            "entry_sell": self.entry_sell.as_dict(),
            "exit_sell_preview": self.exit_sell_preview.as_dict(),
            "exit_buy_preview": self.exit_buy_preview.as_dict(),
            "reason": self.reason,
        }


@dataclass
class ActivePair:
    intent: PairIntent
    opened_at: Decimal
    quantity_base: Decimal
    entry_mean_notional: Decimal
    entry_buy: ExecutableVWAP
    entry_sell: ExecutableVWAP
    entry_fees_paid: Optional[Decimal] = None
    funding_snapshot: Optional[Mapping[str, Tuple[object, ...]]] = None
    maximum_adverse_zscore: Decimal = Decimal(0)


class RobustBasisWindow:
    """Rolling median/MAD model that never includes the evaluated sample."""

    def __init__(self, size: int, minimum_samples: int):
        self.values: Deque[Decimal] = deque(maxlen=size)
        self.minimum_samples = minimum_samples

    def score(self, value: Decimal) -> Optional[Decimal]:
        if len(self.values) < self.minimum_samples:
            return None
        center = decimal_value(median(self.values), "basis_median")
        deviations = [abs(item - center) for item in self.values]
        mad = decimal_value(median(deviations), "basis_mad")
        scale = mad * Decimal("1.4826")
        if scale == 0:
            nonzero = [item for item in deviations if item > 0]
            scale = min(nonzero) if nonzero else Decimal("0.00000001")
        return (value - center) / scale

    def append(self, value: Decimal) -> None:
        self.values.append(value)


class MidFrequencyEngine:
    """Pure decision engine shared by the live strategy and replay runner."""

    def __init__(
        self,
        rules: Mapping[str, InstrumentRule],
        risk: MidFrequencyRisk,
        model_qualification: Optional[object] = None,
        wall_clock: Callable[[], object] = time.time,
    ):
        if set(rules) != set(VENUE_SYMBOLS):
            raise ValueError("rules must contain okx and binance")
        self.rules = dict(rules)
        self.risk = risk
        self.qualification_contract_sha256 = {
            direction: qualification_contract_sha256(self.rules, risk, *direction)
            for direction in (("okx", "binance"), ("binance", "okx"))
        }
        self.model_qualifications = self._normalize_qualifications(model_qualification)
        self._wall_clock = wall_clock
        self.books: Dict[str, BookState] = {}
        self.models = {
            ("okx", "binance"): RobustBasisWindow(risk.zscore_window, risk.minimum_samples),
            ("binance", "okx"): RobustBasisWindow(risk.zscore_window, risk.minimum_samples),
        }
        self.reject_reasons: Counter[str] = Counter()
        self.gapped_venues = set()
        self.last_sequences: Dict[str, int] = {}
        self.last_evaluation = Decimal("-Infinity")
        self.confirming_direction: Optional[Tuple[str, str]] = None
        self.confirmation_count = 0
        self.confirmation_started: Optional[Decimal] = None
        self.active_pair: Optional[ActivePair] = None
        self.cost_history = deque(maxlen=256)
        self.intent_history = deque(maxlen=256)
        self.last_exit_economics = None

    @staticmethod
    def _normalize_qualifications(value) -> Dict[Tuple[str, str], BasisModelQualification]:
        if value is None:
            return {}
        if isinstance(value, BasisModelQualification):
            return {(value.buy_venue, value.sell_venue): value}
        if not isinstance(value, Mapping):
            raise ValueError("model_qualification must be a direction-to-artifact mapping")
        normalized = {}
        for raw_direction, raw_artifact in value.items():
            artifact = (
                raw_artifact
                if isinstance(raw_artifact, BasisModelQualification)
                else BasisModelQualification(**raw_artifact)
            )
            if isinstance(raw_direction, (tuple, list)) and len(raw_direction) == 2:
                direction = (str(raw_direction[0]).lower(), str(raw_direction[1]).lower())
            else:
                parts = str(raw_direction).lower().replace("_to_", "->").split("->")
                if len(parts) != 2:
                    raise ValueError("qualification keys must use 'buy->sell'")
                direction = (parts[0], parts[1])
            if direction != (artifact.buy_venue, artifact.sell_venue):
                raise ValueError("qualification key and artifact direction disagree")
            normalized[direction] = artifact
        return normalized

    def _qualification_allows_entry(self, direction: Tuple[str, str]) -> bool:
        qualification = self.model_qualifications.get(direction)
        if qualification is None:
            self.reject("model_qualification_missing_" + "_to_".join(direction))
            return False
        reason = qualification.rejection_at(
            self._wall_clock(),
            minimum_samples=self.risk.minimum_qualification_samples,
            maximum_half_life_seconds=self.risk.maximum_half_life_seconds,
            expected_contract_sha256=self.qualification_contract_sha256[direction],
            expected_direction=direction,
        )
        if reason is not None:
            self.reject(reason)
            return False
        return True

    def reject(self, reason: str) -> None:
        self.reject_reasons[reason] += 1

    def update_book(self, book: BookState) -> bool:
        if book.venue not in self.rules or not book.bids or not book.asks:
            self.reject("invalid_book")
            return False
        try:
            sequence, previous_sequence, snapshot_kind, continuity = normalize_orderbook_evidence(
                book.sequence,
                book.previous_sequence,
                book.snapshot_or_delta,
                book.continuity_status,
            )
        except CrossExchangeValueError as exc:
            self.gapped_venues.add(book.venue)
            self.reject(str(exc))
            return False
        if book.stale or continuity in {
            "gap",
            "stale",
            "disconnected",
            "checksum_failed",
            "out_of_order",
        }:
            self.gapped_venues.add(book.venue)
            self.reject("sequence_gap" if continuity == "gap" else "source_stale")
            return False
        previous = self.last_sequences.get(book.venue)
        if previous is None and snapshot_kind != "snapshot" and not book.recovery_snapshot:
            self.gapped_venues.add(book.venue)
            self.reject("initial_delta_without_snapshot")
            return False
        if previous is not None:
            if sequence <= previous:
                self.gapped_venues.add(book.venue)
                self.reject("out_of_order")
                return False
            is_snapshot = snapshot_kind == "snapshot"
            broken_delta = not is_snapshot and previous_sequence != previous
            if broken_delta and not book.recovery_snapshot:
                self.gapped_venues.add(book.venue)
                self.reject("sequence_gap")
                self.last_sequences[book.venue] = sequence
                return False
        if book.recovery_snapshot or (
            snapshot_kind == "snapshot" and continuity in ORDERBOOK_HEALTHY_CONTINUITY
        ):
            self.gapped_venues.discard(book.venue)
        self.last_sequences[book.venue] = sequence
        self.books[book.venue] = book
        return True

    def _fresh(self, now: Decimal) -> bool:
        if set(self.books) != set(VENUE_SYMBOLS):
            self.reject("missing_book")
            return False
        if self.gapped_venues:
            self.reject("sequence_gap")
            return False
        values = tuple(self.books.values())
        if len({book.clock_domain_id for book in values}) != 1:
            self.reject("clock_domain")
            return False
        if any(now - book.receive_time > self.risk.maximum_quote_age_seconds for book in values):
            self.reject("stale")
            return False
        if any(book.receive_time > now for book in values):
            self.reject("future_receive_time")
            return False
        skew = abs(values[0].receive_time - values[1].receive_time)
        if skew > self.risk.maximum_venue_skew_seconds:
            self.reject("venue_skew")
            return False
        return True

    def _depth_quantity(self, buy_venue: str, sell_venue: str) -> Decimal:
        buy_depth = sum(size for _, size in self.books[buy_venue].asks)
        sell_depth = sum(size for _, size in self.books[sell_venue].bids)
        requested = min(
            self.risk.quantity_base,
            buy_depth * self.risk.depth_fraction,
            sell_depth * self.risk.depth_fraction,
        )
        lattice = quantity_lattice(requested, self.rules.values())
        if not lattice.tradable:
            raise InsufficientDepth("common quantity lattice is below venue minimum")
        return lattice.quantity_base

    def _funding(self, buy_venue: str, sell_venue: str, quantity: Decimal) -> Decimal:
        total = Decimal(0)
        for venue, side in ((buy_venue, "long"), (sell_venue, "short")):
            book = self.books[venue]
            count = funding_settlement_count(
                book.exchange_time,
                book.next_funding_time,
                self.risk.maximum_holding_seconds,
                self.rules[venue].funding_interval_seconds,
            )
            mid = (book.bids[0][0] + book.asks[0][0]) / Decimal(2)
            total += signed_funding_cashflow(quantity * mid, book.funding_rate, side, count)
        return total

    def _candidate(
        self, buy_venue: str, sell_venue: str, now: Decimal
    ) -> Tuple[Optional[PairIntent], Decimal]:
        try:
            quantity = self._depth_quantity(buy_venue, sell_venue)
            buy = executable_vwap(self.books[buy_venue].asks, quantity, "buy")
            sell = executable_vwap(self.books[sell_venue].bids, quantity, "sell")
            exit_sell = executable_vwap(self.books[buy_venue].bids, quantity, "sell")
            exit_buy = executable_vwap(self.books[sell_venue].asks, quantity, "buy")
            if (
                buy.notional < self.rules[buy_venue].minimum_notional
                or sell.notional < self.rules[sell_venue].minimum_notional
            ):
                raise InsufficientDepth("venue minimum notional is not satisfied")
        except CrossExchangeValueError:
            self.reject("depth_or_lattice")
            return None, Decimal(0)
        long_mid = (self.books[buy_venue].bids[0][0] + self.books[buy_venue].asks[0][0]) / 2
        short_mid = (self.books[sell_venue].bids[0][0] + self.books[sell_venue].asks[0][0]) / 2
        basis = short_mid - long_mid
        model = self.models[(buy_venue, sell_venue)]
        zscore = model.score(basis)
        mean_notional = (buy.notional + sell.notional) / Decimal(2)
        bps = Decimal("10000")
        qualification = self.model_qualifications.get((buy_venue, sell_venue))
        if qualification is None:
            self.reject("model_qualification_missing_" + "_to_".join((buy_venue, sell_venue)))
            return None, basis
        # Entry VWAP is already frozen in entry_executable_edge.  Only the
        # projected closing half-spread/depth belongs in the exit reserve.
        executable_exit_cost = max(Decimal(0), quantity * long_mid - exit_sell.notional) + max(
            Decimal(0), exit_buy.notional - quantity * short_mid
        )
        cost = round_trip_cost(
            quantity_base=quantity,
            entry_buy=buy,
            entry_sell=sell,
            buy_fee_rate=self.rules[buy_venue].taker_fee,
            sell_fee_rate=self.rules[sell_venue].taker_fee,
            expected_exit_basis=qualification.equilibrium_upper_confidence,
            expected_exit_buy_price=exit_buy.price,
            expected_exit_sell_price=exit_sell.price,
            expected_exit_execution_cost=(
                executable_exit_cost + mean_notional * self.risk.exit_reserve_bps / bps
            ),
            signed_funding=self._funding(buy_venue, sell_venue, quantity),
            latency_reserve=mean_notional * self.risk.latency_reserve_bps / bps,
            failure_reserve=mean_notional * self.risk.failure_reserve_bps / bps,
            model_buffer=mean_notional * self.risk.model_buffer_bps / bps,
        )
        self.cost_history.append(cost)
        if zscore is None:
            self.reject("warmup")
            return None, basis
        if zscore < self.risk.entry_zscore:
            self.reject("deviation_gate")
            return None, basis
        minimum_net = mean_notional * self.risk.minimum_net_edge_bps / bps
        if cost.expected_net <= minimum_net:
            self.reject("net_edge")
            return None, basis
        return (
            PairIntent(
                long_venue=buy_venue,
                short_venue=sell_venue,
                quantity_base=quantity,
                buy_price=buy.price,
                sell_price=sell.price,
                zscore=zscore,
                basis=basis,
                entry_executable_basis=cost.entry_executable_edge / quantity,
                expected_exit_basis=qualification.equilibrium_upper_confidence,
                cost=cost,
                created_at=now,
                entry_buy=buy,
                entry_sell=sell,
                exit_sell_preview=exit_sell,
                exit_buy_preview=exit_buy,
            ),
            basis,
        )

    def evaluate(self, now_value) -> Optional[PairIntent]:
        now = decimal_value(now_value, "now")
        if not self.model_qualifications:
            self.reject("model_qualification_missing")
            return None
        if not self._fresh(now):
            return None
        if now - self.last_evaluation < self.risk.minimum_interval_seconds:
            self.reject("minimum_interval")
            return None
        self.last_evaluation = now
        candidates = []
        observed = {}
        for direction in (("okx", "binance"), ("binance", "okx")):
            if not self._qualification_allows_entry(direction):
                continue
            candidate, basis = self._candidate(*direction, now)
            observed[direction] = basis
            if candidate is not None:
                candidates.append(candidate)
        for direction, basis in observed.items():
            self.models[direction].append(basis)
        if self.active_pair is not None:
            return None
        if not candidates:
            self.confirming_direction = None
            self.confirmation_count = 0
            self.confirmation_started = None
            return None
        candidate = max(candidates, key=lambda item: item.cost.expected_net)
        direction = (candidate.long_venue, candidate.short_venue)
        if direction == self.confirming_direction:
            self.confirmation_count += 1
        else:
            self.confirming_direction = direction
            self.confirmation_count = 1
            self.confirmation_started = now
        persisted = now - self.confirmation_started if self.confirmation_started is not None else 0
        if self.confirmation_count < self.risk.confirmations:
            self.reject("confirmation_gate")
            return None
        if persisted < self.risk.persistence_seconds:
            self.reject("persistence_gate")
            return None
        self.confirmation_count = 0
        self.confirmation_started = None
        self.intent_history.append(candidate)
        return candidate

    @staticmethod
    def _confirmed_fill(side: str, quantity: Decimal, price) -> ExecutableVWAP:
        return executable_vwap(((decimal_value(price, "fill_price"), quantity),), quantity, side)

    def mark_open(
        self,
        intent: PairIntent,
        now_value,
        quantity_base=None,
        *,
        entry_buy: Optional[ExecutableVWAP] = None,
        entry_sell: Optional[ExecutableVWAP] = None,
        entry_fees_paid=None,
    ) -> None:
        quantity = (
            intent.quantity_base
            if quantity_base is None
            else decimal_value(quantity_base, "quantity_base")
        )
        if quantity <= 0:
            raise ValueError("opened quantity must be positive")
        confirmed_buy = entry_buy or self._confirmed_fill("buy", quantity, intent.buy_price)
        confirmed_sell = entry_sell or self._confirmed_fill("sell", quantity, intent.sell_price)
        funding_snapshot = {}
        for venue, side, fill in (
            (intent.long_venue, "long", confirmed_buy),
            (intent.short_venue, "short", confirmed_sell),
        ):
            book = self.books[venue]
            funding_snapshot[venue] = (
                book.exchange_time,
                book.next_funding_time,
                book.funding_rate,
                fill.notional,
                self.rules[venue].funding_interval_seconds,
                side,
            )
        self.active_pair = ActivePair(
            intent=intent,
            opened_at=decimal_value(now_value, "opened_at"),
            quantity_base=quantity,
            entry_mean_notional=(confirmed_buy.notional + confirmed_sell.notional) / Decimal(2),
            entry_buy=confirmed_buy,
            entry_sell=confirmed_sell,
            entry_fees_paid=(
                None
                if entry_fees_paid is None
                else decimal_value(entry_fees_paid, "entry_fees_paid")
            ),
            funding_snapshot=funding_snapshot,
        )

    def _realized_funding(self) -> Decimal:
        active = self.active_pair
        if active is None or active.funding_snapshot is None:
            return Decimal(0)
        total = Decimal(0)
        for venue, snapshot in active.funding_snapshot.items():
            opened_exchange_time, next_time, rate, notional, interval, side = snapshot
            current = self.books.get(venue)
            if current is None:
                continue
            elapsed = max(Decimal(0), current.exchange_time - opened_exchange_time)
            settlements = funding_settlement_count(
                opened_exchange_time,
                next_time,
                elapsed,
                interval,
            )
            total += signed_funding_cashflow(notional, rate, side, settlements)
        return total

    def _economics(
        self,
        exit_sell: ExecutableVWAP,
        exit_buy: ExecutableVWAP,
        *,
        exit_fees_paid=None,
        failure_leg_loss=Decimal(0),
        signed_funding=None,
        status="preview_executable_l2",
    ) -> RealizedEconomics:
        active = self.active_pair
        if active is None:
            raise ValueError("no active pair")
        ratio = active.quantity_base / active.intent.quantity_base
        result = realized_round_trip_economics(
            quantity_base=active.quantity_base,
            entry_buy=active.entry_buy,
            entry_sell=active.entry_sell,
            exit_sell=exit_sell,
            exit_buy=exit_buy,
            buy_venue_fee_rate=self.rules[active.intent.long_venue].taker_fee,
            sell_venue_fee_rate=self.rules[active.intent.short_venue].taker_fee,
            entry_fees_paid=active.entry_fees_paid,
            exit_fees_paid=exit_fees_paid,
            signed_funding=(
                self._realized_funding()
                if signed_funding is None
                else decimal_value(signed_funding, "signed_funding")
            ),
            failure_leg_loss=failure_leg_loss,
            latency_reserve=active.intent.cost.latency_adverse_selection_reserve * ratio,
            failure_reserve=active.intent.cost.failure_leg_reserve * ratio,
            model_buffer=active.intent.cost.model_error_buffer * ratio,
        )
        self.last_exit_economics = {**result.as_dict(), "status": status}
        return result

    def exit_reason(self, now_value, margin_ok: bool = True) -> Optional[str]:
        if self.active_pair is None:
            return None
        now = decimal_value(now_value, "now")
        if not self._fresh(now):
            return "stale"
        if not margin_ok:
            return "margin"
        if now - self.active_pair.opened_at >= self.risk.maximum_holding_seconds:
            return "maximum_holding"
        buy_venue = self.active_pair.intent.long_venue
        sell_venue = self.active_pair.intent.short_venue
        quantity = self.active_pair.quantity_base
        try:
            long_exit = executable_vwap(self.books[buy_venue].bids, quantity, "sell")
            short_exit = executable_vwap(self.books[sell_venue].asks, quantity, "buy")
            current_entry_buy = executable_vwap(self.books[buy_venue].asks, quantity, "buy")
            current_entry_sell = executable_vwap(self.books[sell_venue].bids, quantity, "sell")
        except CrossExchangeValueError:
            self.reject("exit_depth")
            return "depth"
        economics = self._economics(long_exit, short_exit)
        loss_limit = (
            self.active_pair.entry_mean_notional * self.risk.maximum_loss_bps / Decimal("10000")
        )
        if economics.realized_net <= -loss_limit:
            return "loss"
        direction = (buy_venue, sell_venue)
        # Use the same executable L2 quantity as entry, loss and close routing.
        current_basis = current_entry_sell.price - current_entry_buy.price
        score = self.models[direction].score(current_basis)
        if score is not None:
            self.active_pair.maximum_adverse_zscore = max(
                self.active_pair.maximum_adverse_zscore, score
            )
            if score <= self.risk.exit_zscore:
                if economics.risk_adjusted_net > 0:
                    return "convergence"
                self.reject("convergence_not_profitable")
            if score >= self.risk.divergence_zscore:
                return "divergence"
        return None

    def mark_closed(self) -> None:
        self.active_pair = None

    def snapshot(self) -> Mapping[str, object]:
        """Return the engine's domain evidence outside a Cerebro run.

        Formula replay has no strategy or observer lifecycle, so its domain
        evidence remains available as a snapshot rather than pretending that
        a framework-level observer was involved.
        """
        return {
            "strategy_id": "012_1_midfreq_cross_exchange",
            "model": "robust_executable_basis_mean_reversion",
            "risk": {key: str(value) for key, value in asdict(self.risk).items()},
            "intents": [intent.as_dict() for intent in self.intent_history],
            "cost_breakdowns": [cost.as_dict() for cost in self.cost_history],
            "reject_reasons": dict(self.reject_reasons),
            "active_pair": self.active_pair is not None,
            "last_exit_economics": self.last_exit_economics,
            "model_qualifications": {
                "->".join(direction): artifact.as_dict()
                for direction, artifact in self.model_qualifications.items()
            },
        }

    def report(self) -> Mapping[str, object]:
        """Return :meth:`snapshot` under the legacy formula-engine API.

        ``CrossExchangeArbitrageStrategy.report`` was intentionally removed
        in favor of the framework-level ``TradeLogger`` report.  This engine
        remains public and is also used by formula replay without a Cerebro
        lifecycle, so retain its historical method as a compatibility alias.
        """
        return self.snapshot()


def _book_from_event(event, venue: str, rule: InstrumentRule, funding) -> BookState:
    received_monotonic_ns = getattr(event, "received_monotonic_ns", None)
    clock_domain_id = getattr(event, "clock_domain_id", None)
    if (
        isinstance(received_monotonic_ns, bool)
        or not isinstance(received_monotonic_ns, int)
        or received_monotonic_ns <= 0
        or not isinstance(clock_domain_id, str)
        or not clock_domain_id.strip()
    ):
        raise CrossExchangeValueError("causal_provenance_missing_or_invalid")
    receive = decimal_value(received_monotonic_ns) / Decimal("1000000000")
    if venue not in funding:
        raise CrossExchangeValueError("funding_snapshot_missing")
    rate, next_time = funding[venue]
    snapshot_or_delta = str(getattr(event, "snapshot_or_delta", None) or "snapshot")
    continuity = str(getattr(event, "continuity_status", None) or "unknown")
    recovery = bool(getattr(event, "recovery_snapshot", False)) or (
        snapshot_or_delta.lower() == "snapshot"
        and continuity.lower() in {"ok", "continuous", "recovered", "snapshot"}
    )
    return BookState(
        venue=venue,
        bids=tuple((decimal_value(price), rule.native_to_base(size)) for price, size in event.bids),
        asks=tuple((decimal_value(price), rule.native_to_base(size)) for price, size in event.asks),
        exchange_time=decimal_value(getattr(event, "exchange_time", None) or event.timestamp),
        receive_time=decimal_value(receive),
        sequence=int(getattr(event, "sequence", 0) or 0),
        previous_sequence=getattr(event, "previous_sequence", None),
        snapshot_or_delta=snapshot_or_delta,
        continuity_status=continuity,
        stale=bool(getattr(event, "stale", False)),
        clock_domain_id=clock_domain_id.strip(),
        funding_rate=decimal_value(rate),
        next_funding_time=(None if next_time is None else decimal_value(next_time)),
        recovery_snapshot=recovery,
    )


class CrossExchangeArbitrageStrategy(bt.Strategy):
    """Backtrader adapter for :class:`MidFrequencyEngine`."""

    params = (
        ("rules", None),
        ("risk", None),
        ("model_qualification", None),
        ("funding", None),
        ("funding_snapshot_provider", None),
        ("funding_exchange_routes", None),
        ("funding_max_age_seconds", Decimal("30")),
        ("funding_exit_window_seconds", None),
        ("account_risk_ledger", None),
        ("execution_enabled", True),
        ("shadow", False),
    )

    def __init__(self):
        self.rules = dict(self.p.rules or {})
        self.risk = (
            self.p.risk
            if isinstance(self.p.risk, MidFrequencyRisk)
            else MidFrequencyRisk(**(self.p.risk or {}))
        )
        qualification = self.p.model_qualification
        self.engine = MidFrequencyEngine(self.rules, self.risk, qualification)
        self.feeds = {
            SYMBOL_VENUES[data._name]: data for data in self.datas if data._name in SYMBOL_VENUES
        }
        if set(self.feeds) != set(VENUE_SYMBOLS):
            raise ValueError("both OKX and Binance feeds are required")
        self.pending_order = None
        self.pair_state = None
        self.order_records = {}
        self.unknown = False
        self.awaiting_reconciliation = False
        self.remote_flat_proven = False
        self.leg_deadline = None
        self.cancel_deadline = None
        self.pair_deadline = None
        self.cancel_requested = False
        self.known_order_refs = set()
        self.processed_order_refs = set()
        self.unhedged_started = None
        self.unhedged_durations = deque(maxlen=4096)
        self.submitted_order_count = 0
        self._confirmed_fill_event_count = 0
        self._fill_cumulative = {}
        self._confirmed_fill_ids = set()
        self.confirmed_fill_ledger = deque(maxlen=4096)
        self.execution_economics_history = deque(maxlen=256)
        self._cycle_id = 0
        self._cancel_retry_refs = set()
        self._reconcile_min_as_of_ns = 0
        self._last_reconcile_request_fence_ns = 0
        self._reconcile_request_active = False
        self._last_reconcile_generation = 0
        self._last_reconcile_fencing_epoch = 0
        self.account_loss_kill_switch = False
        self.account_risk_status = (
            "NOT_APPLICABLE_OBSERVATION_ONLY"
            if self.p.shadow or not self.p.execution_enabled
            else "not_checked"
        )
        self.funding_evidence_status = (
            "NOT_APPLICABLE_OBSERVATION_ONLY"
            if self.p.shadow or not self.p.execution_enabled
            else "not_observed"
        )
        self._funding_states: Dict[str, FundingState] = {}
        self._funding_history = deque(maxlen=256)
        self._trade_logger_last_context_signature = None
        self._trade_logger_context_published_at = Decimal("-Infinity")

    @staticmethod
    def _now():
        return decimal_value(time.monotonic(), "process_monotonic")

    @staticmethod
    def _deadline_ns(deadline: Decimal) -> int:
        return int(deadline * Decimal("1000000000"))

    def _ensure_runtime_state(self):
        """Initialize audit state for normal construction and focused harnesses."""

        state = self.__dict__
        state.setdefault("submitted_order_count", 0)
        state.setdefault("_confirmed_fill_event_count", 0)
        state.setdefault("_fill_cumulative", {})
        state.setdefault("_confirmed_fill_ids", set())
        state.setdefault("confirmed_fill_ledger", deque(maxlen=4096))
        state.setdefault("execution_economics_history", deque(maxlen=256))
        state.setdefault("_cycle_id", 0)
        state.setdefault("_cancel_retry_refs", set())
        state.setdefault("_reconcile_min_as_of_ns", 0)
        state.setdefault("_last_reconcile_generation", 0)
        state.setdefault("_last_reconcile_fencing_epoch", 0)
        state.setdefault("_last_reconcile_request_fence_ns", 0)
        state.setdefault("_reconcile_request_active", False)
        state.setdefault("_last_risk_generation", 0)
        state.setdefault("_last_risk_fencing_epoch", 0)
        state.setdefault("account_loss_kill_switch", False)
        state.setdefault("account_risk_status", "not_checked")
        state.setdefault("funding_evidence_status", "not_observed")
        state.setdefault("_funding_states", {})
        state.setdefault("_funding_history", deque(maxlen=256))
        state.setdefault("_last_idle_funding_check", Decimal("-Infinity"))
        state.setdefault("_trade_logger_last_context_signature", None)
        state.setdefault("_trade_logger_context_published_at", Decimal("-Infinity"))

    @staticmethod
    def _wall_now() -> Decimal:
        return decimal_value(time.time(), "wall_clock_epoch")

    def _static_funding_states(self, now_epoch: Decimal) -> Dict[str, FundingState]:
        raw = getattr(getattr(self, "p", None), "funding", None)
        if not isinstance(raw, Mapping):
            raise CrossExchangeValueError("funding_snapshot_missing")
        states = {}
        for venue in VENUE_SYMBOLS:
            value = raw.get(venue)
            if not isinstance(value, (tuple, list)) or len(value) < 2 or value[1] is None:
                raise CrossExchangeValueError("funding_snapshot_missing")
            next_epoch = decimal_value(value[1], "next_funding_time")
            if next_epoch <= now_epoch:
                raise CrossExchangeValueError("funding_schedule_expired")
            states[venue] = FundingState(
                exchange_name=venue,
                symbol=VENUE_SYMBOLS[venue],
                rate=decimal_value(value[0], "funding_rate"),
                next_funding_time=datetime.fromtimestamp(float(next_epoch), tz=UTC),
                settlement_interval_seconds=int(self.rules[venue].funding_interval_seconds),
                source="explicit_static_replay",
                freshness=Freshness(
                    source="explicit_static_replay",
                    observed_at=datetime.fromtimestamp(float(now_epoch), tz=UTC),
                ),
            )
        return states

    def _read_funding_states(self) -> Dict[str, FundingState]:
        now_epoch = self._wall_now()
        provider = getattr(getattr(self, "p", None), "funding_snapshot_provider", None)
        if not callable(provider):
            return self._static_funding_states(now_epoch)
        values = provider()
        if not isinstance(values, Mapping) or set(values) != set(VENUE_SYMBOLS):
            raise CrossExchangeValueError("funding_snapshot_pair_incomplete")
        expected_routes = getattr(
            getattr(self, "p", None), "funding_exchange_routes", None
        ) or dict.fromkeys(VENUE_SYMBOLS, None)
        if not isinstance(expected_routes, Mapping) or set(expected_routes) != set(VENUE_SYMBOLS):
            raise CrossExchangeValueError("funding_route_binding_incomplete")
        maximum_age = decimal_value(
            getattr(getattr(self, "p", None), "funding_max_age_seconds", Decimal("30")),
            "funding_max_age_seconds",
        )
        for venue, value in values.items():
            if not isinstance(value, Mapping):
                raise CrossExchangeValueError("funding_snapshot_invalid")
            expected_exchange = expected_routes[venue] or venue
            if str(value.get("exchange_name") or "").lower() != str(expected_exchange).lower():
                raise CrossExchangeValueError("funding_identity_mismatch")
            if str(value.get("symbol") or "") != VENUE_SYMBOLS[venue]:
                raise CrossExchangeValueError("funding_identity_mismatch")
            cache_age = decimal_value(value.get("cache_age_seconds"), "cache_age_seconds")
            if cache_age < 0 or cache_age > maximum_age:
                raise CrossExchangeValueError("funding_cache_ttl_expired")
        states = {
            venue: normalize_funding_state(values[venue], now_epoch=now_epoch)
            for venue in VENUE_SYMBOLS
        }
        for venue, state in states.items():
            if state.settlement_interval_seconds != self.rules[venue].funding_interval_seconds:
                raise CrossExchangeValueError("funding_interval_mismatch")
        return states

    def _apply_funding_states(self, states: Mapping[str, FundingState]) -> None:
        self._ensure_runtime_state()
        self._funding_states = dict(states)
        self._funding_history.append(
            {
                "captured_at_epoch": str(self._wall_now()),
                "venues": {venue: state.as_dict() for venue, state in states.items()},
            }
        )
        for venue, current in tuple(self.engine.books.items()):
            state = states.get(venue)
            if state is not None:
                self.engine.books[venue] = replace(
                    current,
                    funding_rate=state.rate,
                    next_funding_time=state.next_funding_epoch,
                )
        pair_funding = (getattr(self, "pair_state", None) or {}).get("funding_snapshot")
        if isinstance(pair_funding, Mapping) and isinstance(pair_funding.get("venues"), Mapping):
            bound = dict(pair_funding["venues"])
            for venue, state in states.items():
                previous = bound.get(venue)
                if not isinstance(previous, FundingState) or (
                    state.next_funding_epoch <= previous.next_funding_epoch
                ):
                    bound[venue] = state
            pair_funding["venues"] = bound
        active = self.engine.active_pair
        if active is not None and active.funding_snapshot is not None:
            bound = dict(active.funding_snapshot)
            for venue, state in states.items():
                previous = bound.get(venue)
                if previous is None:
                    continue
                opened, next_time, rate, notional, interval, side = previous
                if next_time is None or state.next_funding_epoch <= decimal_value(next_time):
                    bound[venue] = (
                        opened,
                        state.next_funding_epoch,
                        state.rate,
                        notional,
                        interval,
                        side,
                    )
            active.funding_snapshot = bound
        self.funding_evidence_status = "fresh_cached_snapshot"

    def _refresh_funding_gate(self, *, opening: bool) -> bool:
        try:
            states = self._read_funding_states()
        except (CrossExchangeValueError, TypeError, ValueError):
            self.funding_evidence_status = "stale_or_unavailable"
            self.engine.reject("funding_stale")
            return False
        self._apply_funding_states(states)
        if opening:
            now_epoch = self._wall_now()
            safe_window = (
                self.risk.pair_deadline_seconds
                + self.risk.maximum_holding_seconds
                + self.risk.flatten_deadline_seconds
            )
            if any(
                state.next_funding_epoch <= now_epoch + safe_window for state in states.values()
            ):
                self.funding_evidence_status = "entry_window_blocked"
                self.engine.reject("funding_entry_window")
                return False
        return True

    def _funding_payload(self) -> Dict[str, Tuple[Decimal, Decimal]]:
        return {
            venue: (state.rate, state.next_funding_epoch)
            for venue, state in self._funding_states.items()
        }

    def _funding_exit_reason(self) -> Optional[str]:
        if not self._refresh_funding_gate(opening=False):
            return "funding_stale"
        return self._funding_exit_reason_from_state()

    def _funding_exit_reason_from_state(self) -> Optional[str]:
        active = self.engine.active_pair
        if active is None:
            return None
        window = getattr(getattr(self, "p", None), "funding_exit_window_seconds", None)
        configured_window = (
            self.risk.flatten_deadline_seconds if window is None else decimal_value(window)
        )
        remaining_holding = max(
            Decimal(0),
            self.risk.maximum_holding_seconds - (self._now() - active.opened_at),
        )
        window = max(
            configured_window,
            remaining_holding + self.risk.flatten_deadline_seconds,
        )
        now_epoch = self._wall_now()
        if any(
            state.next_funding_epoch <= now_epoch + window
            for state in self._funding_states.values()
        ):
            return "funding_window"
        return None

    def _handle_runtime_funding_failure(self, opening_inflight: bool) -> None:
        if self.pending_order is not None and opening_inflight:
            self.pair_state["risk_exit_reason"] = "funding_stale"
            self._request_cancel("funding_stale_cancel")
        elif self.engine.active_pair is not None and self.pair_state is None:
            active = self.engine.active_pair
            self._begin_flatten(
                {
                    active.intent.long_venue: ("long", active.quantity_base),
                    active.intent.short_venue: ("short", active.quantity_base),
                },
                "funding_stale",
            )
        elif opening_inflight and self.pair_state.get("exposures"):
            self._begin_flatten(self.pair_state["exposures"], "funding_stale")
        elif opening_inflight:
            self.pair_state = None
            self.pair_deadline = None
            self.leg_deadline = None
            self.cancel_deadline = None

    def _advance_reconcile_fence(self):
        self._ensure_runtime_state()
        self._reconcile_min_as_of_ns = max(
            self._reconcile_min_as_of_ns,
            self._deadline_ns(self._now()),
        )

    @staticmethod
    def _execution_summary_safe(summary) -> bool:
        required = {
            "unknown_ids",
            "fee_unresolved_orders",
            "trading_blocked",
            "active_orders",
            "evidence_complete",
        }
        if not isinstance(summary, Mapping) or not required.issubset(summary):
            return False
        active_orders = summary["active_orders"]
        if isinstance(active_orders, bool) or not isinstance(active_orders, int):
            return False
        unknown_ids = summary["unknown_ids"]
        fee_unresolved = summary["fee_unresolved_orders"]
        funding_unresolved = summary.get("funding_unresolved_orders", ())
        collection_types = (list, tuple, set, frozenset)
        return bool(
            isinstance(unknown_ids, collection_types)
            and not unknown_ids
            and isinstance(fee_unresolved, collection_types)
            and not fee_unresolved
            and isinstance(funding_unresolved, collection_types)
            and not funding_unresolved
            and summary["trading_blocked"] is False
            and active_orders == 0
            and summary["evidence_complete"] is True
            and not summary.get("evidence_errors")
            and not summary.get("error_code")
        )

    def _account_risk_snapshot(self):
        source = getattr(getattr(self, "p", None), "account_risk_ledger", None)
        if source is None:
            source = getattr(getattr(self, "broker", None), "get_account_risk_snapshot", None)
        try:
            snapshot = source() if callable(source) else source
        except Exception:
            self.engine.reject("account_risk_ledger_error")
            return None
        return snapshot if isinstance(snapshot, Mapping) else None

    def _account_loss_allows_entry(self) -> bool:
        """Require a fresh durable account-level loss snapshot before opening."""

        self._ensure_runtime_state()
        snapshot = self._account_risk_snapshot()
        required = {
            "baseline_equity",
            "current_equity",
            "configured_venues",
            "generation",
            "fencing_epoch",
            "as_of_monotonic_ns",
            "owner_pid",
            "clock_domain_id",
            "identity_binding_sha256",
            "durable",
            "trading_blocked",
            "evidence_complete",
            "loss_limit_bps",
            "loss_limit_breached",
        }
        if snapshot is None or not required.issubset(snapshot):
            self.account_risk_status = "missing_or_incomplete"
            self.account_loss_kill_switch = True
            self.engine.reject("account_risk_ledger_missing")
            return False
        try:
            raw_venues = snapshot["configured_venues"]
            if not isinstance(raw_venues, (list, tuple, set, frozenset)):
                raise TypeError("configured_venues must be a collection")
            venues = {str(item).lower() for item in raw_venues}
            now_ns = self._deadline_ns(self._now())
            raw_as_of = snapshot["as_of_monotonic_ns"]
            raw_generation = snapshot["generation"]
            raw_fencing_epoch = snapshot["fencing_epoch"]
            raw_owner_pid = snapshot["owner_pid"]
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (raw_as_of, raw_generation, raw_fencing_epoch, raw_owner_pid)
            ):
                raise TypeError("risk ledger fences must be integers")
            as_of = raw_as_of
            generation = raw_generation
            fencing_epoch = raw_fencing_epoch
            owner_pid = raw_owner_pid
            clock_domain_id = snapshot["clock_domain_id"]
            if owner_pid != os.getpid() or clock_domain_id != f"process:{owner_pid}:monotonic":
                raise ValueError("risk ledger clock domain is not local monotonic")
            identity_binding = str(snapshot["identity_binding_sha256"])
            if len(identity_binding) != 64 or any(
                character not in "0123456789abcdef" for character in identity_binding
            ):
                raise ValueError("risk ledger identity binding must be a SHA-256 digest")
            if isinstance(snapshot["loss_limit_bps"], bool):
                raise TypeError("loss_limit_bps must be numeric")
            sdk_loss_limit = decimal_value(snapshot["loss_limit_bps"], "loss_limit_bps")
            loss_limit_breached = snapshot["loss_limit_breached"]
            if type(loss_limit_breached) is not bool:
                raise TypeError("loss_limit_breached must be boolean")
        except (TypeError, ValueError, OverflowError):
            self.account_risk_status = "invalid_contract"
            self.account_loss_kill_switch = True
            self.engine.reject("account_risk_ledger_invalid")
            return False
        if sdk_loss_limit != self.risk.account_maximum_loss_bps:
            self.account_risk_status = "invalid_contract"
            self.account_loss_kill_switch = True
            self.engine.reject("account_risk_loss_limit_mismatch")
            return False
        fresh_after = max(
            0,
            now_ns - int(self.risk.maximum_quote_age_seconds * Decimal("1000000000")),
        )
        if (
            venues != set(VENUE_SYMBOLS)
            or snapshot["durable"] is not True
            or type(snapshot["trading_blocked"]) is not bool
            or snapshot["trading_blocked"] is not loss_limit_breached
            or snapshot["evidence_complete"] is not True
            or snapshot.get("evidence_errors")
            or snapshot.get("error_code")
            or generation <= 0
            or generation < self._last_risk_generation
            or fencing_epoch <= 0
            or fencing_epoch < self._last_risk_fencing_epoch
            or as_of < fresh_after
            or as_of > now_ns
        ):
            self.account_risk_status = "stale_or_unbound"
            self.account_loss_kill_switch = True
            self.engine.reject("account_risk_ledger_stale")
            return False
        try:
            baseline = decimal_value(snapshot["baseline_equity"], "baseline_equity")
            current = decimal_value(snapshot["current_equity"], "current_equity")
            realized = (
                decimal_value(snapshot["realized_net"], "account_realized_net")
                if snapshot.get("realized_net") is not None
                else None
            )
        except CrossExchangeValueError:
            self.account_risk_status = "invalid_contract"
            self.account_loss_kill_switch = True
            self.engine.reject("account_risk_ledger_invalid")
            return False
        if baseline <= 0:
            self.account_risk_status = "invalid_baseline"
            self.account_loss_kill_switch = True
            self.engine.reject("account_risk_ledger_invalid")
            return False
        self._last_risk_generation = generation
        self._last_risk_fencing_epoch = fencing_epoch
        limit = baseline * self.risk.account_maximum_loss_bps / Decimal("10000")
        loss = max(Decimal(0), baseline - current)
        if realized is not None:
            loss = max(loss, -realized)
        blocked = bool(self.account_loss_kill_switch or loss_limit_breached or loss >= limit)
        if blocked:
            self.account_loss_kill_switch = True
        self.account_risk_status = "loss_limit" if blocked else "pass"
        if blocked:
            self.engine.reject("account_loss_kill_switch")
        return not blocked

    def _capture_fill_delta(self, order, phase, venue):
        """Convert cumulative Backtrader execution state to unique fill deltas."""

        self._ensure_runtime_state()
        if venue not in self.rules:
            return None
        cumulative_base = self.rules[venue].native_to_base(
            abs(decimal_value(getattr(order.executed, "size", 0), "executed_size"))
        )
        cumulative_price = decimal_value(getattr(order.executed, "price", 0), "fill_price")
        cumulative_commission = decimal_value(
            getattr(order.executed, "comm", 0), "executed_commission"
        )
        previous = self._fill_cumulative.get(
            order.ref,
            {"quantity": Decimal(0), "notional": Decimal(0), "commission": Decimal(0)},
        )
        cumulative_notional = cumulative_base * cumulative_price if cumulative_base else Decimal(0)
        delta_quantity = cumulative_base - previous["quantity"]
        delta_notional = cumulative_notional - previous["notional"]
        delta_commission = cumulative_commission - previous["commission"]
        if delta_quantity < 0 or delta_notional < 0:
            self._mark_unknown("non_monotonic_fill_ledger")
            return None
        self._fill_cumulative[order.ref] = {
            "quantity": cumulative_base,
            "notional": cumulative_notional,
            "commission": cumulative_commission,
        }
        if delta_quantity == 0:
            if delta_commission and order.ref in self._confirmed_fill_ids:
                for event in reversed(self.confirmed_fill_ledger):
                    if event["order_ref"] == order.ref:
                        event["commission"] += delta_commission
                        pair_state = getattr(self, "pair_state", None)
                        if pair_state is not None:
                            for fill in pair_state.get("fills", {}).values():
                                if fill.get("order_ref") == order.ref:
                                    fill["commission"] += delta_commission
                            for fill in pair_state.get("flatten_fills", ()):
                                if fill.get("order_ref") == order.ref:
                                    fill["commission"] += delta_commission
                        active = self.engine.active_pair
                        if active is not None and event["phase"] in {
                            "open_short",
                            "open_long",
                        }:
                            active.entry_fees_paid = (
                                active.entry_fees_paid or Decimal(0)
                            ) + delta_commission
                        self._advance_reconcile_fence()
                        return {
                            "event_id": event["event_id"],
                            "commission_adjustment": delta_commission,
                        }
            return None
        if cumulative_price <= 0 or delta_notional <= 0:
            self._mark_unknown("missing_confirmed_fill_price")
            return None
        event = {
            "event_id": f"{venue}:{order.ref}:{self._confirmed_fill_event_count + 1}",
            "cycle_id": self._cycle_id,
            "order_ref": order.ref,
            "venue": venue,
            "phase": phase,
            "side": "buy" if order.isbuy() else "sell",
            "quantity": delta_quantity,
            "price": delta_notional / delta_quantity,
            "commission": delta_commission,
            "confirmed_at_monotonic_ns": self._deadline_ns(self._now()),
        }
        self.confirmed_fill_ledger.append(event)
        self._confirmed_fill_event_count += 1
        self._confirmed_fill_ids.add(order.ref)
        self._advance_reconcile_fence()
        return event

    def _request_remote_reconcile(self):
        self._ensure_runtime_state()
        if self._reconcile_request_active:
            return False
        self._reconcile_request_active = True
        try:
            self._advance_reconcile_fence()
            if self._last_reconcile_request_fence_ns >= self._reconcile_min_as_of_ns:
                return True
            requester = getattr(getattr(self, "broker", None), "request_reconcile", None)
            if not callable(requester):
                self._mark_unknown("broker_reconcile_api_missing")
                return False
            try:
                receipt = requester()
            except Exception:
                self._mark_unknown("broker_reconcile_request_failed")
                return False
            if receipt is False or (
                isinstance(receipt, Mapping) and receipt.get("queued") is False
            ):
                self._mark_unknown("broker_reconcile_request_rejected")
                return False
            self._last_reconcile_request_fence_ns = self._reconcile_min_as_of_ns
            return True
        finally:
            self._reconcile_request_active = False

    def _poll_remote_reconcile(self):
        broker = getattr(self, "broker", None)
        getter = getattr(broker, "get_last_reconcile_result", None)
        summary_getter = getattr(broker, "get_execution_summary", None)
        if not callable(getter) or not callable(summary_getter):
            return False
        try:
            snapshot = getter()
            summary = summary_getter()
        except Exception:
            self._mark_unknown("broker_reconcile_read_failed")
            return False
        if snapshot is None:
            return False
        return self.confirm_remote_flat(snapshot, execution_summary=summary)

    def _mark_unknown(self, reason):
        self._ensure_runtime_state()
        was_unknown = self.unknown
        if not was_unknown:
            previous_fence = self._reconcile_min_as_of_ns
            self._advance_reconcile_fence()
            self._reconcile_min_as_of_ns = max(
                self._reconcile_min_as_of_ns,
                previous_fence + 1,
            )
        self.engine.reject(reason)
        self.engine.reject("unknown_execution")
        self.unknown = True
        self.awaiting_reconciliation = True
        self.remote_flat_proven = False
        if self._last_reconcile_request_fence_ns < self._reconcile_min_as_of_ns:
            self._request_remote_reconcile()

    def _request_cancel(self, reason):
        if self.pending_order is None or self.cancel_requested:
            return
        self.cancel_requested = True
        self.engine.reject(reason)
        self._advance_reconcile_fence()
        self.cancel(self.pending_order)

    def _check_deadlines(self):
        if self.pending_order is None:
            now = self._now()
            if (
                self.pair_state is not None
                and self.pair_state.get("phase") == "flatten"
                and self.pair_state.get("flatten_waiting_for_book") is not None
                and self.pair_deadline is not None
                and now >= self.pair_deadline
                and not self.unknown
            ):
                self._mark_unknown("flatten_deadline")
                return
            if (
                self.awaiting_reconciliation
                and self.pair_deadline is not None
                and now >= self.pair_deadline
                and not self.unknown
            ):
                self._mark_unknown("reconciliation_deadline")
            return
        now = self._now()
        execution_cutoff = min(
            deadline for deadline in (self.leg_deadline, self.pair_deadline) if deadline is not None
        )
        if now >= execution_cutoff:
            self._request_cancel("execution_deadline")
        if (
            self.cancel_requested
            and self.cancel_deadline is not None
            and now >= self.cancel_deadline
        ):
            self._mark_unknown("cancel_deadline")

    def _handle_invalid_book(self, venue):
        if self.engine.active_pair is not None and self.pending_order is None:
            active = self.engine.active_pair
            self._begin_flatten(
                {
                    active.intent.long_venue: ("long", active.quantity_base),
                    active.intent.short_venue: ("short", active.quantity_base),
                },
                "invalid_market_data",
            )
            return
        if self.pair_state is None:
            return
        self.pair_state["risk_exit_reason"] = "invalid_market_data"
        if self.pending_order is not None:
            self._request_cancel("invalid_market_data_cancel")
        elif self.pair_state.get("exposures"):
            self._begin_flatten(self.pair_state["exposures"], "invalid_market_data")

    def notify_orderbook(self, event):
        """Process a book and refresh report context only when it is due."""

        self._ensure_runtime_state()
        try:
            return self._notify_orderbook(event)
        finally:
            self._publish_trade_logger_context()

    def _notify_orderbook(self, event):
        venue = SYMBOL_VENUES.get(event.symbol)
        if venue is None:
            return
        self._check_deadlines()
        pair_phase = self.pair_state.get("phase") if self.pair_state is not None else None
        if pair_phase in {"flatten", "reconcile"}:
            updated = self._update_risk_reduction_book(event, venue)
            queue = (self.pair_state or {}).get("flatten_queue") or ()
            retry_venue = queue[0].get("venue") if queue else None
            if (
                updated
                and pair_phase == "flatten"
                and self.pending_order is None
                and self.pair_state.get("flatten_waiting_for_book") is not None
                and venue == retry_venue
                and not self.unknown
            ):
                self.pair_state.pop("flatten_waiting_for_book", None)
                self._submit_flatten_head()
            if self.awaiting_reconciliation:
                self._poll_remote_reconcile()
            return
        if self.awaiting_reconciliation:
            self._poll_remote_reconcile()
            return
        if self.unknown:
            return
        opening_inflight = pair_phase in {"open_short", "open_long"}
        funding_ready = self._refresh_funding_gate(opening=self.engine.active_pair is None)
        if not funding_ready:
            self._handle_runtime_funding_failure(opening_inflight)
            return
        book = _book_from_event(event, venue, self.rules[venue], self._funding_payload())
        if not self.engine.update_book(book):
            self._handle_invalid_book(venue)
            return
        now = book.receive_time
        if self.pending_order is not None:
            return
        if self.pair_state is not None:
            return
        if self.engine.active_pair is not None:
            if (
                self.p.execution_enabled
                and not self.p.shadow
                and not self._account_loss_allows_entry()
            ):
                active = self.engine.active_pair
                self._begin_flatten(
                    {
                        active.intent.long_venue: ("long", active.quantity_base),
                        active.intent.short_venue: ("short", active.quantity_base),
                    },
                    "account_loss_kill_switch",
                )
                return
            reason = self._funding_exit_reason() or self.engine.exit_reason(now)
            if reason and self.p.execution_enabled and not self.p.shadow:
                active = self.engine.active_pair
                self._begin_flatten(
                    {
                        active.intent.long_venue: ("long", active.quantity_base),
                        active.intent.short_venue: ("short", active.quantity_base),
                    },
                    "close_" + reason,
                )
            return
        intent = self.engine.evaluate(now)
        if intent is None or not self.p.execution_enabled or self.p.shadow:
            return
        if not self._account_loss_allows_entry():
            return
        if not self._refresh_funding_gate(opening=True):
            return
        self._ensure_runtime_state()
        self._cycle_id += 1
        self.remote_flat_proven = False
        self.pair_state = {
            "intent": intent,
            "phase": "open_short",
            "fills": {},
            "exposures": {},
            "funding_snapshot": {
                "captured_at_epoch": self._wall_now(),
                "venues": dict(self._funding_states),
            },
        }
        now_local = self._now()
        self.pair_deadline = now_local + self.risk.pair_deadline_seconds
        self._submit(
            intent.short_venue,
            "sell",
            intent.quantity_base,
            intent.entry_sell.marginal_price,
            "open_short",
            position_side="short",
        )

    def notify_idle(self):
        """Advance deadlines and refresh the low-rate runtime report context."""

        self._ensure_runtime_state()
        try:
            return self._notify_idle()
        finally:
            self._publish_trade_logger_context()

    def _notify_idle(self):
        """Advance execution and risk deadlines while live books are silent."""

        self._ensure_runtime_state()
        self._check_deadlines()
        if self.awaiting_reconciliation:
            self._poll_remote_reconcile()
            return
        if self.unknown:
            return
        pair_phase = self.pair_state.get("phase") if self.pair_state is not None else None
        if pair_phase in {"flatten", "reconcile"}:
            if (
                pair_phase == "flatten"
                and self.pending_order is None
                and self.pair_deadline is not None
                and self._now() >= self.pair_deadline
            ):
                self._mark_unknown("flatten_deadline")
            return
        opening_inflight = pair_phase in {"open_short", "open_long"}
        now = self._now()
        if opening_inflight and not self.engine._fresh(now):
            self.pair_state["risk_exit_reason"] = "market_data_silence"
            if self.pending_order is not None:
                self._request_cancel("market_data_silence_cancel")
            elif self.pair_state.get("exposures"):
                self._begin_flatten(self.pair_state["exposures"], "market_data_silence")
            else:
                self.pair_state = None
            return
        active = self.engine.active_pair
        if active is None and not opening_inflight:
            return
        maximum_age = decimal_value(
            getattr(getattr(self, "p", None), "funding_max_age_seconds", Decimal("30"))
        )
        funding_poll = min(Decimal("0.25"), maximum_age / Decimal(2))
        if now - self._last_idle_funding_check >= funding_poll:
            self._last_idle_funding_check = now
            if not self._refresh_funding_gate(opening=active is None):
                self._handle_runtime_funding_failure(opening_inflight)
                return
        if active is not None and self.pending_order is None:
            if self._funding_exit_reason_from_state() == "funding_window":
                self._begin_flatten(
                    {
                        active.intent.long_venue: ("long", active.quantity_base),
                        active.intent.short_venue: ("short", active.quantity_base),
                    },
                    "close_funding_window_data_silence",
                )
            elif now - active.opened_at >= self.risk.maximum_holding_seconds:
                self._begin_flatten(
                    {
                        active.intent.long_venue: ("long", active.quantity_base),
                        active.intent.short_venue: ("short", active.quantity_base),
                    },
                    "close_maximum_holding_data_silence",
                )
            elif not self.engine._fresh(now):
                self._begin_flatten(
                    {
                        active.intent.long_venue: ("long", active.quantity_base),
                        active.intent.short_venue: ("short", active.quantity_base),
                    },
                    "close_market_data_silence",
                )

    def _submit(
        self,
        venue,
        side,
        quantity_base,
        price,
        phase,
        *,
        position_side,
        reduce_only=False,
    ):
        if not reduce_only and phase in {"open_short", "open_long"}:
            if not self._refresh_funding_gate(opening=True):
                if self.pending_order is not None:
                    if self.pair_state is not None:
                        self.pair_state["risk_exit_reason"] = "funding_stale"
                    self._request_cancel("funding_stale_cancel")
                elif self.pair_state is not None and self.pair_state.get("exposures"):
                    self._begin_flatten(self.pair_state["exposures"], "funding_stale")
                elif self.pair_state is not None:
                    self.pair_state = None
                    self.pair_deadline = None
                    self.leg_deadline = None
                    self.cancel_deadline = None
                return
        now = self._now()
        if phase in {"open_short", "open_long"} and not self.engine._fresh(now):
            reason = (
                "hedge_market_data_stale" if phase == "open_long" else "entry_market_data_stale"
            )
            self._handle_local_submit_failure(reason, phase, reduce_only)
            return
        if self.pair_deadline is None or now >= self.pair_deadline:
            self._handle_local_submit_failure("pair_deadline", phase, reduce_only)
            return
        rule = self.rules[venue]
        native = rule.quantize_native_down(rule.base_to_native(quantity_base))
        if native <= 0:
            self._handle_local_submit_failure("quantity_below_lattice", phase, reduce_only)
            return
        try:
            limit_price = self._execution_price(venue, side, quantity_base)
        except CrossExchangeValueError:
            self._handle_local_submit_failure("order_depth", phase, reduce_only)
            return
        leg_limit = (
            self.risk.entry_deadline_seconds
            if phase == "open_short"
            else (
                self.risk.hedge_deadline_seconds
                if phase == "open_long"
                else self.risk.flatten_deadline_seconds
            )
        )
        self.leg_deadline = min(now + leg_limit, self.pair_deadline)
        self.cancel_deadline = min(
            self.leg_deadline + self.risk.cancel_deadline_seconds,
            self.pair_deadline,
        )
        self.cancel_requested = False
        self.remote_flat_proven = False
        self._advance_reconcile_fence()
        kwargs = {
            "data": self.feeds[venue],
            "size": native,
            "price": rule.quantize_price(limit_price, side),
            "exectype": bt.Order.Limit,
            "time_in_force": "IOC",
            "position_side": position_side,
            "offset": "close" if reduce_only else "open",
            "reduce_only": reduce_only,
            "execution_deadline_monotonic_ns": self._deadline_ns(self.leg_deadline),
            "cancel_deadline_monotonic_ns": self._deadline_ns(self.cancel_deadline),
        }
        self.pending_order = self.buy(**kwargs) if side == "buy" else self.sell(**kwargs)
        self.submitted_order_count += 1
        self.known_order_refs.add(self.pending_order.ref)

    def _handle_local_submit_failure(self, reason, phase, reduce_only):
        opening_phase = phase in {"open_short", "open_long"} and not reduce_only
        exposures = (self.pair_state or {}).get("exposures", {})
        if opening_phase and exposures:
            self.engine.reject(reason)
            self._begin_flatten(exposures, reason)
            return
        if opening_phase:
            self.engine.reject(reason)
            self.pair_state = None
            self.pair_deadline = None
            self.leg_deadline = None
            self.cancel_deadline = None
            return
        if reduce_only and phase == "flatten" and reason == "order_depth":
            queue = (self.pair_state or {}).get("flatten_queue") or ()
            if queue and int(queue[0].get("attempts", 0)) < 3:
                self.engine.reject(reason)
                self.pair_state["flatten_waiting_for_book"] = reason
                return
            self.engine.reject("compensation_exhausted" if queue else "flatten_queue_missing")
        self._mark_unknown(reason)

    def _update_risk_reduction_book(self, event, venue):
        funding = self._funding_payload()
        current = self.engine.books.get(venue)
        if venue not in funding and current is not None:
            funding[venue] = (current.funding_rate, current.next_funding_time)
        try:
            book = _book_from_event(event, venue, self.rules[venue], funding)
        except (CrossExchangeValueError, AttributeError, TypeError, ValueError):
            self.engine.reject("risk_reduction_book_invalid")
            return False
        if not self.engine.update_book(book):
            self.engine.reject("risk_reduction_book_rejected")
            return False
        return True

    def _execution_price(self, venue, side, quantity_base):
        book = self.engine.books.get(venue)
        if book is None:
            raise CrossExchangeValueError("no last-known book for order")
        levels = book.asks if side == "buy" else book.bids
        return executable_vwap(levels, quantity_base, side).marginal_price

    def _begin_flatten(self, exposures, reason):
        funding_snapshot = (
            self.pair_state.get("funding_snapshot") if self.pair_state is not None else None
        )
        intent = (
            self.pair_state["intent"]
            if self.pair_state is not None
            else self.engine.active_pair.intent
        )
        queue = []
        for venue, (position_side, quantity) in exposures.items():
            if quantity <= 0:
                continue
            side = "sell" if position_side == "long" else "buy"
            fallback = intent.buy_price if side == "sell" else intent.sell_price
            queue.append(
                {
                    "venue": venue,
                    "position_side": position_side,
                    "side": side,
                    "remaining": quantity,
                    "fallback": fallback,
                    "attempts": 0,
                }
            )
        self.pair_deadline = self._now() + self.risk.flatten_deadline_seconds
        self.pair_state = {
            "intent": intent,
            "phase": "flatten",
            "flatten_queue": queue,
            "flatten_fills": [],
            "reason": reason,
            "funding_snapshot": funding_snapshot,
        }
        self._submit_flatten_head()

    def _submit_flatten_head(self):
        queue = self.pair_state["flatten_queue"]
        if not queue:
            self.pair_state["phase"] = "reconcile"
            self.awaiting_reconciliation = True
            self.remote_flat_proven = False
            self.pending_order = None
            self.leg_deadline = None
            self.cancel_deadline = None
            self.engine.reject("remote_flat_confirmation_required")
            self._request_remote_reconcile()
            return
        head = queue[0]
        head["attempts"] += 1
        self._submit(
            head["venue"],
            head["side"],
            head["remaining"],
            head["fallback"],
            "flatten",
            position_side=head["position_side"],
            reduce_only=True,
        )

    def _record_order(self, order, phase, venue, filled_base):
        fill_price = decimal_value(getattr(order.executed, "price", 0), "fill_price")
        self.order_records[order.ref] = {
            "venue": venue,
            "phase": phase,
            "status": order.getstatusname(),
            "filled_base": str(filled_base),
            "fill_events": len(getattr(order.executed, "exbits", ()) or ()),
            "fill_price": str(fill_price),
            "commission": str(decimal_value(order.executed.comm)),
        }
        if len(self.order_records) > 4096:
            self.order_records.pop(next(iter(self.order_records)))

    def _note_live_partial(self, order):
        if self.pair_state is None:
            return
        venue = SYMBOL_VENUES.get(order.data._name)
        if venue is None:
            return
        quantity = self.rules[venue].native_to_base(abs(decimal_value(order.executed.size)))
        if quantity <= 0:
            return
        phase = self.pair_state["phase"]
        position_side = "long" if order.isbuy() else "short"
        self.pair_state.setdefault("confirmed_partials", {})[phase] = {
            "quantity": quantity,
            "price": str(decimal_value(getattr(order.executed, "price", 0))),
            "commission": str(decimal_value(order.executed.comm)),
        }
        if phase != "flatten":
            self.pair_state.setdefault("exposures", {})[venue] = (position_side, quantity)
            if self.unhedged_started is None:
                self.unhedged_started = self._now()

    def _finalize_realized_close(self, signed_funding=None) -> bool:
        active = self.engine.active_pair
        cycle_events = [
            event for event in self.confirmed_fill_ledger if event["cycle_id"] == self._cycle_id
        ]
        if active is None:
            if not cycle_events:
                self.funding_evidence_status = "no_fills"
                return True
            net_quantity = {venue: Decimal(0) for venue in VENUE_SYMBOLS}
            for event in cycle_events:
                signed = event["quantity"] if event["side"] == "buy" else -event["quantity"]
                net_quantity[event["venue"]] += signed
            if any(quantity != 0 for quantity in net_quantity.values()):
                self.engine.reject("failed_leg_fill_ledger_incomplete")
                return False
            gross = sum(
                (
                    event["price"] * event["quantity"]
                    if event["side"] == "sell"
                    else -(event["price"] * event["quantity"])
                )
                for event in cycle_events
            )
            fees = sum((event["commission"] for event in cycle_events), Decimal(0))
            pair_funding = (self.pair_state or {}).get("funding_snapshot", {})
            captured_at = pair_funding.get("captured_at_epoch")
            venues = pair_funding.get("venues")
            if signed_funding is None:
                if (
                    captured_at is None
                    or not isinstance(venues, Mapping)
                    or set(venues) != set(VENUE_SYMBOLS)
                    or any(not isinstance(state, FundingState) for state in venues.values())
                ):
                    self.engine.reject("funding_ledger_missing_failed_cycle")
                    self.funding_evidence_status = "missing"
                    return False
                now_epoch = self._wall_now()
                if any(
                    isinstance(state, FundingState) and state.next_funding_epoch <= now_epoch
                    for state in venues.values()
                ):
                    self.engine.reject("funding_ledger_missing_failed_cycle")
                    self.funding_evidence_status = "missing"
                    return False
            funding = Decimal(0) if signed_funding is None else decimal_value(signed_funding)
            self.funding_evidence_status = (
                "no_settlement_expected_failed_cycle" if signed_funding is None else "actual_ledger"
            )
            record = {
                "status": "failed_leg_compensation_confirmed",
                "cycle_id": self._cycle_id,
                "gross_pnl": str(gross),
                "fees": str(fees),
                "signed_funding_cashflow": str(funding),
                "failure_leg_loss": str(max(Decimal(0), -gross)),
                "realized_net": str(gross - fees + funding),
                "funding_evidence_status": self.funding_evidence_status,
            }
            self.engine.last_exit_economics = record
            self.execution_economics_history.append(record)
            return True
        fills = self.pair_state.get("flatten_fills", []) if self.pair_state else []
        long_fills = [
            (fill["price"], fill["quantity"])
            for fill in fills
            if fill["venue"] == active.intent.long_venue and fill["side"] == "sell"
        ]
        short_fills = [
            (fill["price"], fill["quantity"])
            for fill in fills
            if fill["venue"] == active.intent.short_venue and fill["side"] == "buy"
        ]
        try:
            exit_sell = aggregate_confirmed_fills(
                long_fills,
                side="sell",
                expected_quantity_base=active.quantity_base,
            )
            exit_buy = aggregate_confirmed_fills(
                short_fills,
                side="buy",
                expected_quantity_base=active.quantity_base,
            )
        except CrossExchangeValueError:
            self.engine.reject("realized_close_fill_ledger_incomplete")
            return False
        if signed_funding is None and active.funding_snapshot:
            now_epoch = self._wall_now()
            for funding_snapshot in active.funding_snapshot.values():
                _opened_exchange_time, next_time, _rate, _notional, _interval, _side = (
                    funding_snapshot
                )
                if now_epoch >= decimal_value(next_time, "next_funding_time"):
                    self.engine.reject("funding_ledger_missing")
                    self.funding_evidence_status = "missing"
                    return False
        elif signed_funding is None:
            self.engine.reject("funding_ledger_missing")
            self.funding_evidence_status = "missing"
            return False
        effective_funding = Decimal(0) if signed_funding is None else signed_funding
        self.funding_evidence_status = (
            "no_settlement_expected" if signed_funding is None else "actual_ledger"
        )
        fees = sum((fill["commission"] for fill in fills), Decimal(0))
        self.engine._economics(
            exit_sell,
            exit_buy,
            exit_fees_paid=fees,
            signed_funding=effective_funding,
            status=(
                "realized_confirmed_fills_and_funding"
                if signed_funding is not None
                else "realized_confirmed_fills_no_funding_settlement"
            ),
        )
        self.execution_economics_history.append(
            {
                **dict(self.engine.last_exit_economics),
                "cycle_id": self._cycle_id,
                "funding_evidence_status": self.funding_evidence_status,
            }
        )
        return True

    @staticmethod
    def _positions_prove_flat(positions) -> bool:
        if isinstance(positions, Mapping):
            if set(VENUE_SYMBOLS) - set(positions):
                return False
            for venue in VENUE_SYMBOLS:
                row = positions[venue]
                if not isinstance(row, Mapping) or not {"long", "short"}.issubset(row):
                    return False
                if any(
                    decimal_value(row[side], f"{venue}_{side}_position") != 0
                    for side in ("long", "short")
                ):
                    return False
            return True
        if not isinstance(positions, (list, tuple)):
            return False
        size_keys = (
            "volume",
            "size",
            "position",
            "position_size",
            "positionSize",
            "position_qty",
            "positionQty",
            "positionAmt",
            "position_amt",
            "qty",
            "quantity",
            "pos",
            "Position",
            "Volume",
            "Qty",
            "Quantity",
        )
        for row in positions:
            if not isinstance(row, Mapping):
                return False
            venue = str(row.get("exchange_name") or row.get("venue") or "").lower()
            if venue not in VENUE_SYMBOLS:
                return False
            size = next((row[key] for key in size_keys if key in row), None)
            if size is None or decimal_value(size, f"{venue}_position") != 0:
                return False
        return True

    @staticmethod
    def _open_orders_empty(open_orders) -> bool:
        if isinstance(open_orders, Mapping):
            return all(not rows for rows in open_orders.values())
        return isinstance(open_orders, (list, tuple)) and not open_orders

    def confirm_remote_flat(
        self,
        snapshot: Mapping[str, object],
        *,
        execution_summary: Optional[Mapping[str, object]] = None,
        signed_funding=None,
    ) -> bool:
        """Consume a complete fenced Broker reconcile snapshot and SDK summary."""

        if not self.awaiting_reconciliation:
            return False
        self._ensure_runtime_state()
        if not isinstance(snapshot, Mapping) or snapshot.get("error_code"):
            self._mark_unknown("reconcile_snapshot_invalid")
            return False
        summary = (
            snapshot.get("execution_summary") if execution_summary is None else execution_summary
        )
        if not self._execution_summary_safe(summary):
            self._mark_unknown("sdk_execution_summary_unsafe")
            return False
        try:
            configured = {str(item).lower() for item in snapshot.get("configured_venues", ())}
            reconciled = {str(item).lower() for item in snapshot.get("reconciled_venues", ())}
            snapshot_generation = int(
                snapshot.get("generation", snapshot.get("session_generation", 0)) or 0
            )
            summary_generation = int(
                (summary or {}).get("generation", (summary or {}).get("session_generation", 0)) or 0
            )
            snapshot_fence = int(snapshot.get("fencing_epoch", 0) or 0)
            summary_fence = int((summary or {}).get("fencing_epoch", 0) or 0)
            as_of = int(snapshot.get("as_of_monotonic_ns", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            self._mark_unknown("reconcile_snapshot_invalid")
            return False
        if configured != set(VENUE_SYMBOLS) or reconciled != configured:
            self._mark_unknown("reconcile_venue_coverage")
            return False
        if (
            snapshot.get("evidence_complete") is not True
            or snapshot.get("evidence_errors")
            or snapshot.get("error_code")
            or snapshot.get("unknown_ids") not in ([], ())
            or snapshot.get("trading_blocked") is not False
        ):
            self._mark_unknown("reconcile_snapshot_incomplete")
            return False
        if (
            snapshot_generation <= 0
            or snapshot_generation != summary_generation
            or snapshot_generation < self._last_reconcile_generation
            or snapshot_fence <= 0
            or snapshot_fence != summary_fence
            or snapshot_fence < self._last_reconcile_fencing_epoch
            or as_of < self._reconcile_min_as_of_ns
            or as_of > self._deadline_ns(self._now())
        ):
            self._mark_unknown("reconcile_fence_mismatch")
            return False
        if "open_orders" not in snapshot or not self._open_orders_empty(snapshot["open_orders"]):
            self._mark_unknown("remote_open_orders_not_empty")
            return False
        try:
            positions_flat = "positions" in snapshot and self._positions_prove_flat(
                snapshot["positions"]
            )
        except CrossExchangeValueError:
            positions_flat = False
        if not positions_flat:
            self._mark_unknown("remote_position_not_flat")
            return False
        if signed_funding is None and isinstance(summary, Mapping):
            if summary.get("funding_evidence_status") == "actual_ledger":
                signed_funding = summary.get("signed_funding_cashflow")
        economics_complete = self._finalize_realized_close(signed_funding)
        if not economics_complete:
            self._mark_unknown("realized_close_economics_unknown")
            return False
        self._last_reconcile_generation = snapshot_generation
        self._last_reconcile_fencing_epoch = snapshot_fence
        self.remote_flat_proven = True
        self.engine.mark_closed()
        self.pair_state = None
        self.pending_order = None
        self.pair_deadline = None
        if self.unhedged_started is not None:
            self.unhedged_durations.append(self._now() - self.unhedged_started)
            self.unhedged_started = None
        self.unknown = False
        self.awaiting_reconciliation = False
        return True

    def notify_order(self, order):
        """Handle an order update and immediately publish its state transition."""

        self._ensure_runtime_state()
        try:
            return self._notify_order(order)
        finally:
            self._publish_trade_logger_context()

    def _notify_order(self, order):
        self._ensure_runtime_state()
        venue = SYMBOL_VENUES.get(getattr(getattr(order, "data", None), "_name", None))
        pair_state = getattr(self, "pair_state", None)
        phase = pair_state["phase"] if pair_state else "late_or_unknown"
        fill_event = None
        if order.ref in self.known_order_refs and venue is not None:
            fill_event = self._capture_fill_delta(order, phase, venue)
        if bool(order.info.get("cancel_execution_unknown", False)):
            self._mark_unknown("broker_cancel_execution_unknown")
            self._request_remote_reconcile()
            return
        if bool(order.info.get("execution_unknown", False)):
            self._mark_unknown("broker_execution_unknown")
            self._request_remote_reconcile()
            return
        if bool(order.info.get("cancel_reconcile_confirmed_live", False)):
            if bool(order.info.get("cancel_intent_active", False)):
                # BtApiBroker owns the retry schedule after a query proves
                # that the ambiguously cancelled order is still live.
                self.cancel_requested = True
                self.cancel_deadline = None
                return
            if order.ref in self._cancel_retry_refs:
                self._mark_unknown("cancel_retry_exhausted")
                self._request_remote_reconcile()
                return
            self._cancel_retry_refs.add(order.ref)
            self.cancel_requested = False
            if self.pair_deadline is None:
                self._mark_unknown("pair_deadline")
                self._request_remote_reconcile()
                return
            self.cancel_deadline = min(
                self._now() + self.risk.cancel_deadline_seconds,
                self.pair_deadline,
            )
            self._request_cancel("cancel_retry_after_confirmed_live")
            return
        if self.pending_order is None or order.ref != self.pending_order.ref:
            if order.ref in self.processed_order_refs and fill_event is None:
                return
            if order.ref in self.known_order_refs:
                self._mark_unknown("late_known_order_update")
                self._request_remote_reconcile()
            return
        if self.unknown:
            if not order.alive():
                self._record_order(
                    order, phase, venue, self._fill_cumulative[order.ref]["quantity"]
                )
                self.processed_order_refs.add(order.ref)
                self.pending_order = None
                self._request_remote_reconcile()
            return
        if order.alive():
            self._note_live_partial(order)
            return
        if self.pair_state is None:
            self._mark_unknown("terminal_order_without_pair_state")
            return
        phase = self.pair_state["phase"] if self.pair_state else "unknown"
        filled_native = abs(decimal_value(order.executed.size))
        filled_base = self.rules[venue].native_to_base(filled_native) if venue else Decimal(0)
        self._record_order(order, phase, venue, filled_base)
        self.processed_order_refs.add(order.ref)
        self.pending_order = None
        self.leg_deadline = None
        self.cancel_deadline = None
        self.cancel_requested = False
        if phase == "flatten":
            if filled_base > 0:
                fill_price = decimal_value(getattr(order.executed, "price", 0), "fill_price")
                if fill_price <= 0:
                    self._mark_unknown("missing_confirmed_fill_price")
                    return
                self.pair_state["flatten_fills"].append(
                    {
                        "order_ref": order.ref,
                        "venue": venue,
                        "side": "buy" if order.isbuy() else "sell",
                        "quantity": filled_base,
                        "price": fill_price,
                        "commission": decimal_value(order.executed.comm),
                    }
                )
            queue = self.pair_state.get("flatten_queue") or ()
            if not queue or queue[0].get("venue") != venue:
                self._mark_unknown("flatten_order_queue_mismatch")
                return
            head = queue[0]
            head["remaining"] = max(Decimal(0), head["remaining"] - filled_base)
            if head["remaining"] == 0:
                self.pair_state["flatten_queue"].pop(0)
            elif head["attempts"] >= 3:
                self.engine.reject("compensation_exhausted")
                self._mark_unknown("compensation_exhausted")
                return
            else:
                self.pair_state["flatten_waiting_for_book"] = "terminal_remaining"
                return
            self._submit_flatten_head()
            return
        intent = self.pair_state["intent"]
        if filled_base <= 0:
            if phase == "open_short":
                self.engine.reject("first_leg_unfilled")
                if self.pair_state.get("risk_exit_reason"):
                    self.pair_state = None
                else:
                    self.pair_state = None
                self.pair_deadline = None
            else:
                self.engine.reject("hedge_unfilled")
                self._begin_flatten(self.pair_state["exposures"], "hedge_unfilled")
            return
        fill_price = decimal_value(getattr(order.executed, "price", 0), "fill_price")
        if fill_price <= 0:
            self._mark_unknown("missing_confirmed_fill_price")
            return
        position_side = "long" if order.isbuy() else "short"
        fill = {
            "order_ref": order.ref,
            "quantity": filled_base,
            "price": fill_price,
            "commission": decimal_value(order.executed.comm),
            "venue": venue,
            "side": "buy" if order.isbuy() else "sell",
        }
        self.pair_state["fills"][phase] = fill
        self.pair_state["exposures"][venue] = (position_side, filled_base)
        if self.unhedged_started is None:
            self.unhedged_started = self._now()
        if self.pair_state.get("risk_exit_reason"):
            self._begin_flatten(self.pair_state["exposures"], self.pair_state["risk_exit_reason"])
            return
        if phase == "open_short":
            hedge_lattice = quantity_lattice(filled_base, self.rules.values())
            if not hedge_lattice.tradable:
                self.engine.reject("partial_below_common_lattice")
                self._begin_flatten(self.pair_state["exposures"], "partial_below_common_lattice")
                return
            self.pair_state["phase"] = "open_long"
            self._submit(
                intent.long_venue,
                "buy",
                hedge_lattice.quantity_base,
                intent.buy_price,
                "open_long",
                position_side="long",
            )
            return
        short_fill = self.pair_state["fills"]["open_short"]
        if filled_base != short_fill["quantity"]:
            self.engine.reject("partial_hedge")
            self._begin_flatten(self.pair_state["exposures"], "partial_hedge")
            return
        long_fill = self.pair_state["fills"]["open_long"]
        if not self._refresh_funding_gate(opening=True):
            self._begin_flatten(self.pair_state["exposures"], "funding_stale_after_hedge")
            return
        entry_buy = self.engine._confirmed_fill("buy", filled_base, long_fill["price"])
        entry_sell = self.engine._confirmed_fill("sell", filled_base, short_fill["price"])
        self.engine.mark_open(
            intent,
            self._now(),
            quantity_base=filled_base,
            entry_buy=entry_buy,
            entry_sell=entry_sell,
            entry_fees_paid=long_fill["commission"] + short_fill["commission"],
        )
        self.pair_state = None
        if self.unhedged_started is not None:
            self.unhedged_durations.append(self._now() - self.unhedged_started)
            self.unhedged_started = None

    def start(self) -> None:
        """Publish the initial candidate state after observers have started."""

        self._ensure_runtime_state()
        self._publish_trade_logger_context(force=True)

    def _cached_broker_value_for_report(self):
        """Read an already-synchronized portfolio value without provider I/O."""

        getter = getattr(getattr(self, "broker", None), "get_cached_report_state", None)
        if not callable(getter):
            return None
        try:
            cached = getter()
        except Exception:
            return None
        if not isinstance(cached, Mapping):
            return None
        value = cached.get("value")
        if value is None:
            return None
        try:
            return str(decimal_value(value, "cached_broker_value"))
        except (ArithmeticError, CrossExchangeValueError, TypeError, ValueError):
            return None

    def _trade_logger_context_signature(self):
        """Return a small local-only signature for low-rate report publication."""

        self._ensure_runtime_state()
        pair_state = self.pair_state if isinstance(self.pair_state, Mapping) else {}
        pending_order = self.pending_order
        return (
            bool(getattr(self.engine, "active_pair", None)),
            bool(getattr(self.engine, "halted_unknown", False)),
            self.unknown,
            self.awaiting_reconciliation,
            self.remote_flat_proven,
            pair_state.get("phase"),
            bool(pair_state.get("risk_exit_reason")),
            len(pair_state.get("fills", {})),
            len(pair_state.get("exposures", {})),
            getattr(pending_order, "ref", None),
            getattr(pending_order, "status", None),
            self.cancel_requested,
            self.submitted_order_count,
            self._confirmed_fill_event_count,
            len(self.order_records),
            len(self.execution_economics_history),
            self.account_loss_kill_switch,
            self.account_risk_status,
            self.funding_evidence_status,
        )

    def trade_logger_context(self) -> Mapping[str, object]:
        """Return cross-venue evidence for ``TradeLogger.extensions``.

        ``TradeLogger`` owns generic orders, trades, portfolio values and
        real-time snapshots.  This strategy supplies only the model and
        execution facts which are specific to this two-venue candidate.
        """
        self._ensure_runtime_state()
        base = dict(self.engine.snapshot())
        fees = sum(
            (row["commission"] for row in self._fill_cumulative.values()),
            Decimal(0),
        )
        fill_events = [
            {
                **event,
                "quantity": str(event["quantity"]),
                "price": str(event["price"]),
                "commission": str(event["commission"]),
            }
            for event in self.confirmed_fill_ledger
        ]
        base.update(
            orders=list(self.order_records.values()),
            order_count=len(self.order_records),
            submitted_order_count=self.submitted_order_count,
            confirmed_fill_events=self._confirmed_fill_event_count,
            confirmed_fill_ledger=fill_events,
            fees_paid=str(fees),
            funding_evidence_status=self.funding_evidence_status,
            funding_snapshots=list(self._funding_history),
            execution_economics=list(self.execution_economics_history),
            account_loss_kill_switch=self.account_loss_kill_switch,
            account_risk_status=self.account_risk_status,
            unknown_execution=self.unknown,
            reconciliation_required=self.unknown or self.awaiting_reconciliation,
            remote_flat_proven=self.remote_flat_proven,
            unhedged_duration_max=str(max(self.unhedged_durations, default=Decimal(0))),
            broker_value=self._cached_broker_value_for_report(),
        )
        return base

    def _publish_trade_logger_context(self, *, force: bool = False) -> bool:
        """Publish state transitions immediately and stable books at most once a second."""

        trade_logger = getattr(getattr(self, "stats", None), "trade_logger", None)
        update = getattr(trade_logger, "update_report_context", None)
        if not callable(update):
            return False
        signature = self._trade_logger_context_signature()
        now = self._now()
        previous_signature = self._trade_logger_last_context_signature
        previous_published_at = self._trade_logger_context_published_at
        due = now - previous_published_at >= Decimal(1)
        if not force and signature == previous_signature and not due:
            return False
        try:
            published = bool(update(self.trade_logger_context(), namespace="cross_venue"))
        except Exception:
            published = False
        if published or not force:
            self._trade_logger_last_context_signature = signature
            self._trade_logger_context_published_at = now
        return published

    def stop(self) -> None:
        """Publish final domain evidence while ``TradeLogger`` remains mutable."""

        self._publish_trade_logger_context(force=True)


__all__ = [
    "BasisModelQualification",
    "BookState",
    "CrossExchangeArbitrageStrategy",
    "MidFrequencyEngine",
    "MidFrequencyRisk",
    "PairIntent",
    "RobustBasisWindow",
    "VENUE_SYMBOLS",
    "qualify_basis_model",
    "qualification_contract_sha256",
]
