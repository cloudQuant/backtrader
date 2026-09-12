"""Offline Iteration 24 C/P/F strategy with a frozen FQ2 feature boundary.

The example consumes bars and quote evidence emitted by the local replay
producer.  It never creates a clock mapping, fills quote identity, opens a
network session, or sends an external order.  The ordinary decision path is a
single closed-minute ``next`` call; later ticks can only be recorded as
cutoff-qualified diagnostics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Deque, Dict, Mapping, Optional, Sequence, Tuple

import backtrader as bt
from backtrader.feeds import (
    BarBarrierPolicy,
    BarLeg,
    MultiLegBarBarrier,
    validate_quote_against_bar,
)


def _load_feature_module() -> Any:
    """Load the sibling feature module only when a strategy is constructed."""

    try:
        from .features import FeaturePolicy, FeatureReason, compute_minute_features
    except ImportError:  # Direct execution through this directory's run.py.
        from features import FeaturePolicy, FeatureReason, compute_minute_features

    return FeaturePolicy, FeatureReason, compute_minute_features


def _load_timing_module() -> Any:
    """Load the local MF-T1 read model without creating a second runtime client."""

    try:
        from .execution_timing import TimingPolicy, TimingProjector
    except ImportError:  # Direct execution through this directory's run.py.
        from execution_timing import TimingPolicy, TimingProjector

    return TimingPolicy, TimingProjector


if TYPE_CHECKING:
    try:
        from .features import MinuteFeatures
    except ImportError:  # Direct execution through this directory's run.py.
        from features import MinuteFeatures


class ConfigurationError(ValueError):
    """A strict local-config rejection with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError("CONFIG_SCHEMA", f"{path} must be a mapping")
    return value


def _require_exact_keys(value: Mapping[str, Any], allowed: Sequence[str], path: str) -> None:
    actual = set(value)
    expected = set(allowed)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown or missing:
        raise ConfigurationError(
            "CONFIG_SCHEMA", f"{path} has unknown keys {unknown} or missing keys {missing}"
        )


def _decimal(value: Any, path: str) -> Decimal:
    if isinstance(value, bool):
        raise ConfigurationError("CONFIG_NUMBER", f"{path} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ConfigurationError("CONFIG_NUMBER", f"{path} must be numeric") from error
    if not parsed.is_finite():
        raise ConfigurationError("CONFIG_NUMBER", f"{path} must be finite")
    return parsed


def _positive_decimal(value: Any, path: str) -> Decimal:
    parsed = _decimal(value, path)
    if parsed <= 0:
        raise ConfigurationError("CONFIG_RANGE", f"{path} must be positive")
    return parsed


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError("CONFIG_RANGE", f"{path} must be a positive integer")
    return value


def _optional_positive_int(value: Any, path: str) -> Optional[int]:
    if value is None:
        return None
    return _positive_int(value, path)


def validate_config(raw: Any) -> Dict[str, Any]:
    """Validate the replay contract before constructing Cerebro or a broker."""

    config = _require_mapping(raw, "config")
    required_config_keys = {"mode", "candidate", "budget", "signal", "features", "replay"}
    unknown_config_keys = sorted(set(config) - required_config_keys - {"timing"})
    missing_config_keys = sorted(required_config_keys - set(config))
    if unknown_config_keys or missing_config_keys:
        raise ConfigurationError(
            "CONFIG_SCHEMA",
            f"config has unknown keys {unknown_config_keys} or missing keys {missing_config_keys}",
        )
    mode = config["mode"]
    if mode != "replay":
        code = "PRODUCTION_DISABLED" if mode == "production" else "MODE_NOT_SUPPORTED_OFFLINE"
        raise ConfigurationError(code, f"mode {mode!r} is disabled by this offline example")

    candidate = _require_mapping(config["candidate"], "candidate")
    _require_exact_keys(
        candidate,
        (
            "candidate_id",
            "exchange",
            "rules_hash",
            "option_style",
            "strike",
            "multiplier",
            "discount_factor",
            "contracts",
            "quantities",
            "price_ticks",
        ),
        "candidate",
    )
    for field in ("candidate_id", "exchange", "rules_hash"):
        if not isinstance(candidate[field], str) or not candidate[field].strip():
            raise ConfigurationError("CONFIG_SCHEMA", f"candidate.{field} must be non-empty")
    if candidate["option_style"] not in ("European", "American"):
        raise ConfigurationError(
            "CONFIG_SCHEMA", "candidate.option_style must be European or American"
        )
    strike = _positive_decimal(candidate["strike"], "candidate.strike")
    multiplier = _positive_decimal(candidate["multiplier"], "candidate.multiplier")
    discount_factor = _positive_decimal(candidate["discount_factor"], "candidate.discount_factor")
    if discount_factor > Decimal("1"):
        raise ConfigurationError("CONFIG_RANGE", "candidate.discount_factor must be at most one")

    contracts = _require_mapping(candidate["contracts"], "candidate.contracts")
    _require_exact_keys(contracts, ("future", "call", "put"), "candidate.contracts")
    identifiers = []
    for field in ("future", "call", "put"):
        value = contracts[field]
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(
                "CONFIG_SCHEMA", f"candidate.contracts.{field} must be non-empty"
            )
        identifiers.append(value)
    if len(set(identifiers)) != 3:
        raise ConfigurationError("DUPLICATE_CONTRACT", "future, call and put must be distinct")

    price_ticks = _require_mapping(candidate["price_ticks"], "candidate.price_ticks")
    _require_exact_keys(price_ticks, ("future", "call", "put"), "candidate.price_ticks")
    parsed_ticks = {
        field: _positive_decimal(price_ticks[field], f"candidate.price_ticks.{field}")
        for field in ("future", "call", "put")
    }

    quantities = _require_mapping(candidate["quantities"], "candidate.quantities")
    _require_exact_keys(quantities, ("future", "call", "put"), "candidate.quantities")
    parsed_quantities = {
        field: _positive_int(quantities[field], f"candidate.quantities.{field}")
        for field in ("future", "call", "put")
    }
    if tuple(parsed_quantities.values()) != (1, 1, 1):
        raise ConfigurationError("BASKET_RATIO", "this fixture permits only one 1:1:1 basket")

    budget = _require_mapping(config["budget"], "budget")
    _require_exact_keys(
        budget,
        ("capital_limit_cny", "working_limit_cny", "recovery_reserve_cny", "path_requirement_cny"),
        "budget",
    )
    capital_limit = _positive_decimal(budget["capital_limit_cny"], "budget.capital_limit_cny")
    working_limit = _positive_decimal(budget["working_limit_cny"], "budget.working_limit_cny")
    recovery_reserve = _positive_decimal(
        budget["recovery_reserve_cny"], "budget.recovery_reserve_cny"
    )
    path_requirement = _positive_decimal(
        budget["path_requirement_cny"], "budget.path_requirement_cny"
    )
    if capital_limit != Decimal("10000"):
        raise ConfigurationError("CAPITAL_CAP", "budget.capital_limit_cny must equal 10000")
    if working_limit > Decimal("8000"):
        raise ConfigurationError("WORKING_CAP", "budget.working_limit_cny may not exceed 8000")
    if recovery_reserve < Decimal("2000"):
        raise ConfigurationError(
            "RECOVERY_RESERVE", "budget.recovery_reserve_cny must be at least 2000"
        )
    if working_limit + recovery_reserve > capital_limit:
        raise ConfigurationError(
            "BUDGET_PARTITION", "working limit plus recovery reserve exceeds capital"
        )
    if path_requirement > working_limit or path_requirement + recovery_reserve > capital_limit:
        raise ConfigurationError(
            "BUDGET_PATH", "budget path requirement exceeds the permitted capital"
        )

    signal = _require_mapping(config["signal"], "signal")
    _require_exact_keys(
        signal,
        (
            "bar_minutes",
            "history_bars",
            "residual_floor_cny",
            "z_entry",
            "minimum_net_edge_cny",
            "cost_bound_cny",
        ),
        "signal",
    )
    if signal["bar_minutes"] != 1:
        raise ConfigurationError(
            "BAR_INTERVAL", "this example accepts completed one-minute bars only"
        )
    if signal["history_bars"] != 60:
        raise ConfigurationError(
            "HISTORY_WINDOW", "this example requires exactly sixty historical bars"
        )
    residual_floor = _positive_decimal(signal["residual_floor_cny"], "signal.residual_floor_cny")
    z_entry = _positive_decimal(signal["z_entry"], "signal.z_entry")
    minimum_net_edge = _positive_decimal(
        signal["minimum_net_edge_cny"], "signal.minimum_net_edge_cny"
    )
    cost_bound = _positive_decimal(signal["cost_bound_cny"], "signal.cost_bound_cny")
    economic_floor = multiplier * (
        parsed_ticks["future"] * discount_factor + parsed_ticks["call"] + parsed_ticks["put"]
    )
    if residual_floor < economic_floor:
        raise ConfigurationError(
            "RESIDUAL_FLOOR",
            "signal.residual_floor_cny is below the bound implied by multiplier, discount, and ticks",
        )

    feature_config = _require_mapping(config["features"], "features")
    _require_exact_keys(
        feature_config,
        (
            "short_window_seconds",
            "long_window_seconds",
            "max_segment_seconds",
            "max_cross_leg_skew_ms",
            "minimum_new_snapshots",
            "persistence_ratio",
            "max_adverse_pressure",
        ),
        "features",
    )
    short_window = _positive_decimal(
        feature_config["short_window_seconds"], "features.short_window_seconds"
    )
    long_window = _positive_decimal(
        feature_config["long_window_seconds"], "features.long_window_seconds"
    )
    max_segment = _positive_decimal(
        feature_config["max_segment_seconds"], "features.max_segment_seconds"
    )
    max_skew = _positive_decimal(
        feature_config["max_cross_leg_skew_ms"], "features.max_cross_leg_skew_ms"
    )
    minimum_snapshots = _positive_int(
        feature_config["minimum_new_snapshots"], "features.minimum_new_snapshots"
    )
    persistence = _positive_decimal(
        feature_config["persistence_ratio"], "features.persistence_ratio"
    )
    adverse = _positive_decimal(
        feature_config["max_adverse_pressure"], "features.max_adverse_pressure"
    )
    if short_window != Decimal("5") or long_window != Decimal("60"):
        raise ConfigurationError("FEATURE_WINDOW", "FQ2 requires five and sixty second windows")
    if max_segment > Decimal("2"):
        raise ConfigurationError("FEATURE_SEGMENT", "FQ2 segment limit may not exceed two seconds")
    if max_skew > Decimal("500"):
        raise ConfigurationError("FEATURE_SKEW", "FQ2 cross-leg skew may not exceed 500ms")
    if persistence < Decimal("0.8") or persistence > Decimal("1"):
        raise ConfigurationError(
            "FEATURE_RATIO", "features.persistence_ratio must be between 0.8 and one"
        )
    if adverse <= Decimal("0") or adverse > Decimal("0.5"):
        raise ConfigurationError(
            "FEATURE_RATIO", "features.max_adverse_pressure must be positive and at most 0.5"
        )
    if minimum_net_edge < Decimal("20"):
        raise ConfigurationError("FEATURE_EDGE", "signal.minimum_net_edge_cny must be at least 20")
    if z_entry < Decimal("2.5"):
        raise ConfigurationError("FEATURE_Z", "signal.z_entry must be at least 2.5")

    replay = _require_mapping(config["replay"], "replay")
    _require_exact_keys(replay, ("initial_cash_cny", "scenario"), "replay")
    initial_cash = _positive_decimal(replay["initial_cash_cny"], "replay.initial_cash_cny")
    if initial_cash < capital_limit:
        raise ConfigurationError("INITIAL_CASH", "replay initial cash must cover the capital limit")
    if replay["scenario"] not in ("no_edge", "edge"):
        raise ConfigurationError("REPLAY_SCENARIO", "replay.scenario must be no_edge or edge")

    timing_raw = config.get("timing")
    if timing_raw is None:
        timing = {
            "decision_deadline_seconds": None,
            "leg_timeout_seconds": 5,
            "basket_timeout_seconds": 15,
            "cancel_timeout_seconds": 5,
            "recovery_timeout_seconds": 60,
            "minimum_hold_seconds": 60,
            "maximum_hold_seconds": 900,
            "idle_interval_ms": 250,
            "history_capacity": 128,
        }
    else:
        timing_config = _require_mapping(timing_raw, "timing")
        _require_exact_keys(
            timing_config,
            (
                "decision_deadline_seconds",
                "leg_timeout_seconds",
                "basket_timeout_seconds",
                "cancel_timeout_seconds",
                "recovery_timeout_seconds",
                "minimum_hold_seconds",
                "maximum_hold_seconds",
                "idle_interval_ms",
                "history_capacity",
            ),
            "timing",
        )
        decision_deadline = _optional_positive_int(
            timing_config["decision_deadline_seconds"],
            "timing.decision_deadline_seconds",
        )
        timing = {
            "decision_deadline_seconds": decision_deadline,
            "leg_timeout_seconds": _positive_int(
                timing_config["leg_timeout_seconds"], "timing.leg_timeout_seconds"
            ),
            "basket_timeout_seconds": _positive_int(
                timing_config["basket_timeout_seconds"], "timing.basket_timeout_seconds"
            ),
            "cancel_timeout_seconds": _positive_int(
                timing_config["cancel_timeout_seconds"], "timing.cancel_timeout_seconds"
            ),
            "recovery_timeout_seconds": _positive_int(
                timing_config["recovery_timeout_seconds"], "timing.recovery_timeout_seconds"
            ),
            "minimum_hold_seconds": _positive_int(
                timing_config["minimum_hold_seconds"], "timing.minimum_hold_seconds"
            ),
            "maximum_hold_seconds": _positive_int(
                timing_config["maximum_hold_seconds"], "timing.maximum_hold_seconds"
            ),
            "idle_interval_ms": _positive_int(
                timing_config["idle_interval_ms"], "timing.idle_interval_ms"
            ),
            "history_capacity": _positive_int(
                timing_config["history_capacity"], "timing.history_capacity"
            ),
        }
        if timing["leg_timeout_seconds"] > 5:
            raise ConfigurationError(
                "TIMING_LEG_TIMEOUT", "timing leg timeout may not exceed five seconds"
            )
        if timing["basket_timeout_seconds"] > 15:
            raise ConfigurationError(
                "TIMING_BASKET_TIMEOUT", "timing basket timeout may not exceed fifteen seconds"
            )
        if timing["cancel_timeout_seconds"] > 5:
            raise ConfigurationError(
                "TIMING_CANCEL_TIMEOUT", "timing cancel timeout may not exceed five seconds"
            )
        if timing["recovery_timeout_seconds"] > 60:
            raise ConfigurationError(
                "TIMING_RECOVERY_TIMEOUT", "timing recovery timeout may not exceed sixty seconds"
            )
        if timing["minimum_hold_seconds"] < 60:
            raise ConfigurationError("TIMING_MIN_HOLD", "timing minimum hold cannot be shortened")
        if timing["maximum_hold_seconds"] > 900:
            raise ConfigurationError("TIMING_MAX_HOLD", "timing maximum hold cannot be extended")
        if timing["idle_interval_ms"] > 250:
            raise ConfigurationError(
                "TIMING_IDLE_INTERVAL", "timing idle interval may not exceed 250ms"
            )
        if timing["history_capacity"] < 8:
            raise ConfigurationError("TIMING_CAPACITY", "timing history capacity is too small")

    return {
        "mode": "replay",
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "exchange": candidate["exchange"],
            "rules_hash": candidate["rules_hash"],
            "option_style": candidate["option_style"],
            "strike": strike,
            "multiplier": multiplier,
            "discount_factor": discount_factor,
            "contracts": dict(contracts),
            "quantities": parsed_quantities,
            "price_ticks": parsed_ticks,
        },
        "budget": {
            "capital_limit_cny": capital_limit,
            "working_limit_cny": working_limit,
            "recovery_reserve_cny": recovery_reserve,
            "path_requirement_cny": path_requirement,
        },
        "signal": {
            "bar_minutes": 1,
            "history_bars": 60,
            "residual_floor_cny": residual_floor,
            "z_entry": z_entry,
            "minimum_net_edge_cny": minimum_net_edge,
            "cost_bound_cny": cost_bound,
        },
        "features": {
            "short_window_seconds": short_window,
            "long_window_seconds": long_window,
            "max_segment_seconds": max_segment,
            "max_cross_leg_skew_ms": max_skew,
            "minimum_new_snapshots": minimum_snapshots,
            "persistence_ratio": persistence,
            "max_adverse_pressure": adverse,
        },
        "replay": {"initial_cash_cny": initial_cash, "scenario": replay["scenario"]},
        "timing": timing,
    }


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _decision_key(value: Any) -> Any:
    """Convert barrier key components to stable JSON-safe report values."""

    return value.isoformat() if isinstance(value, datetime) else value


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a deliberately naive local config timestamp for compatibility tests."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return None
    return parsed


def _tick_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class DecisionToken:
    """One ordinary decision capability bound to one closed input."""

    token_id: str
    candidate_id: str
    bar_ids: Tuple[str, ...]
    quote_cutoffs: Tuple[Tuple[str, int], ...]
    bucket_end: datetime
    generation: int
    rules_hash: str
    direction: str
    quantity: Tuple[Tuple[str, int], ...]
    next_id: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "candidate_id": self.candidate_id,
            "bar_ids": list(self.bar_ids),
            "quote_cutoffs": dict(self.quote_cutoffs),
            "bucket_end": self.bucket_end.isoformat(),
            "generation": self.generation,
            "rules_hash": self.rules_hash,
            "direction": self.direction,
            "quantity": dict(self.quantity),
            "next_id": self.next_id,
        }


class _TokenLedger:
    """Bounded one-shot token storage used only inside the replay strategy."""

    _MAX = 128

    def __init__(self) -> None:
        self._issued: Deque[DecisionToken] = deque(maxlen=self._MAX)
        self._consumed: Deque[str] = deque(maxlen=self._MAX)
        self._consumed_ids = set()
        self.issued_count = 0
        self.consumed_count = 0

    def issue(
        self,
        features: MinuteFeatures,
        decision_input: Any,
        *,
        next_id: int,
        quantity: Mapping[str, int],
    ) -> DecisionToken:
        del decision_input
        token = DecisionToken(
            token_id=f"{features.candidate_id}:{features.bucket_end.isoformat()}:{next_id}",
            candidate_id=features.candidate_id,
            bar_ids=tuple(features.bar_ids),
            quote_cutoffs=tuple(
                sorted((key, int(value)) for key, value in features.quote_cutoffs.items())
            ),
            bucket_end=features.bucket_end,
            generation=features.generation,
            rules_hash=features.rules_hash,
            direction=features.direction or "",
            quantity=tuple(sorted((key, int(value)) for key, value in quantity.items())),
            next_id=next_id,
        )
        self._issued.append(token)
        self.issued_count += 1
        return token

    def consume(
        self, token: DecisionToken, decision_input: Any, *, next_id: int
    ) -> Tuple[bool, str]:
        if token.token_id in self._consumed_ids:
            return False, "TOKEN_ALREADY_CONSUMED"
        expected = (
            token.candidate_id == decision_input.candidate_id
            and token.bar_ids == tuple(decision_input.bar_ids)
            and token.quote_cutoffs
            == tuple(
                sorted((key, int(value)) for key, value in decision_input.quote_cutoffs.items())
            )
            and token.bucket_end == decision_input.bucket_end
            and token.generation == decision_input.generation
            and token.rules_hash == decision_input.rules_hash
            and token.next_id == next_id
        )
        if not expected:
            return False, "TOKEN_CONTEXT_MISMATCH"
        self._consumed.append(token.token_id)
        self._consumed_ids.add(token.token_id)
        while len(self._consumed_ids) > self._MAX:
            self._consumed_ids.discard(self._consumed.popleft())
        self.consumed_count += 1
        return True, "TOKEN_CONSUMED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issued_count": self.issued_count,
            "consumed_count": self.consumed_count,
            "issued": [token.to_dict() for token in self._issued],
        }


class CTPOptionsMidFrequencyStrategy(bt.Strategy):
    """A read-only local C/P/F strategy driven by frozen FQ2 features."""

    params = (("config", None), ("quote_producer", None), ("timing_provider", None))

    def __init__(self) -> None:
        if self.p.config is None:
            raise ConfigurationError("CONFIG_REQUIRED", "strategy configuration is required")
        if self.p.quote_producer is None and self.p.timing_provider is None:
            raise ConfigurationError(
                "EVIDENCE_PRODUCER_REQUIRED",
                "an explicit replay evidence or timing provider is required",
            )
        self._config = self.p.config
        candidate = self._config["candidate"]
        contracts = candidate["contracts"]
        self._producer = self.p.quote_producer
        self._timing_provider = self.p.timing_provider
        self._timing_projector = None
        self._timing_results: Deque[Dict[str, Any]] = deque(maxlen=128)
        self._timing_only = self._producer is None
        self._timing_idle_count = 0
        if self._timing_only:
            self._init_timing_only()
            return
        feature_policy_type, self._feature_reason, self._compute_features = _load_feature_module()
        self._policy = feature_policy_type(
            symbols=(contracts["future"], contracts["call"], contracts["put"]),
            multiplier=candidate["multiplier"],
            strike=candidate["strike"],
            discount_factor=candidate["discount_factor"],
            price_tick_by_symbol={
                contracts[field]: candidate["price_ticks"][field]
                for field in ("future", "call", "put")
            },
            history_bars=self._config["signal"]["history_bars"],
            short_window_seconds=self._config["features"]["short_window_seconds"],
            long_window_seconds=self._config["features"]["long_window_seconds"],
            max_segment_seconds=self._config["features"]["max_segment_seconds"],
            max_cross_leg_skew_ms=self._config["features"]["max_cross_leg_skew_ms"],
            minimum_new_snapshots=self._config["features"]["minimum_new_snapshots"],
            persistence_ratio=self._config["features"]["persistence_ratio"],
            max_adverse_pressure=self._config["features"]["max_adverse_pressure"],
            residual_floor_cny=self._config["signal"]["residual_floor_cny"],
            z_entry=self._config["signal"]["z_entry"],
            minimum_net_edge_cny=self._config["signal"]["minimum_net_edge_cny"],
            cost_bound_cny=self._config["signal"]["cost_bound_cny"],
        )
        self._history: Deque[Decimal] = deque(maxlen=self._policy.history_bars)
        self._feature_history: Deque[MinuteFeatures] = deque(maxlen=128)
        self._seen_minutes = set()
        self._seen_minute_order: Deque[str] = deque(maxlen=256)
        self._last_minute: Optional[datetime] = None
        self._last_closed_minute: Optional[datetime] = None
        self._last_decision_input: Any = None
        self._ordinary_decisions: Deque[Dict[str, Any]] = deque(maxlen=128)
        self._minute_events: Deque[Dict[str, Any]] = deque(maxlen=256)
        self._accepted_tick_features: Deque[Dict[str, Any]] = deque(maxlen=128)
        self._rejections: Deque[str] = deque(maxlen=128)
        self._barrier_results: Deque[Dict[str, Any]] = deque(maxlen=128)
        self._rejected_tick_count = 0
        self._tick_callback_count = 0
        self._orders_submitted = 0
        self._next_id = 0
        self._tokens = _TokenLedger()
        self._barrier = MultiLegBarBarrier(
            expected_legs=tuple(
                BarLeg(contracts[field], candidate["exchange"])
                for field in ("future", "call", "put")
            ),
            candidate_id=candidate["candidate_id"],
            expected_rules_hash=candidate["rules_hash"],
            policy=BarBarrierPolicy(timeframe_seconds=60.0, timeout_seconds=2.0),
            clock_mode="replay",
            expected_clock_domain="iter24-replay-clock",
        )
        if self._timing_provider is not None:
            self._init_timing_projector()

    def _init_timing_projector(self) -> None:
        timing_policy_type, timing_projector_type = _load_timing_module()
        provider = self._timing_provider
        if provider is None:
            return
        self._timing_projector = timing_projector_type(
            scope=provider.scope,
            mapping=provider.mapping,
            policy=timing_policy_type(**self._config["timing"]),
        )

    def _init_timing_only(self) -> None:
        """Initialize the same strategy as a timing-only Cerebro consumer."""

        self._feature_reason = None
        self._compute_features = None
        self._policy = None
        self._history = deque(maxlen=1)
        self._feature_history = deque(maxlen=1)
        self._seen_minutes = set()
        self._seen_minute_order = deque(maxlen=1)
        self._last_minute = None
        self._last_closed_minute = None
        self._last_decision_input = None
        self._ordinary_decisions = deque(maxlen=1)
        self._minute_events = deque(maxlen=128)
        self._accepted_tick_features = deque(maxlen=1)
        self._rejections = deque(maxlen=128)
        self._barrier_results = deque(maxlen=1)
        self._rejected_tick_count = 0
        self._tick_callback_count = 0
        self._orders_submitted = 0
        self._next_id = 0
        self._tokens = _TokenLedger()
        self._init_timing_projector()

    def _timing_next(self) -> None:
        provider = self._timing_provider
        if provider is None or self._timing_projector is None:
            return
        minute = provider.next_minute()
        result = self._timing_projector.consume_minute(
            minute,
            provider.execution_facts(),
            provider.clock_for_next(),
        )
        self._timing_results.append({"origin": "next", **result.to_dict()})

    def _timing_idle(self) -> None:
        provider = self._timing_provider
        if provider is None or self._timing_projector is None:
            return
        self._timing_idle_count += 1
        result = self._timing_projector.notify_idle(
            provider.execution_facts(),
            provider.clock_for_idle(),
        )
        self._timing_results.append({"origin": "notify_idle", **result.to_dict()})

    def _current_synchronous_minute(self) -> Optional[datetime]:
        if len(self.datas) != 3 or any(len(data) == 0 for data in self.datas):
            return None
        timestamps = tuple(data.datetime.datetime(0).replace(tzinfo=None) for data in self.datas)
        if timestamps[0] != timestamps[1] or timestamps[0] != timestamps[2]:
            return None
        return timestamps[0]

    def _minute_index(self, minute: datetime) -> int:
        producer_base = self._producer.base
        end = minute.replace(tzinfo=timezone.utc)
        elapsed_minutes = (end - producer_base).total_seconds() / 60.0
        index = int(round(elapsed_minutes)) - 1
        if index < 0 or abs(elapsed_minutes - round(elapsed_minutes)) > 1e-9:
            raise ConfigurationError(
                "REPLAY_TIME", "minute is outside the explicit replay producer scope"
            )
        return index

    def _bar_evidence(self, symbol: str, minute: datetime, data: Any, leg_index: int) -> Any:
        return self._producer.bar_for(self._minute_index(minute), symbol, data, leg_index)

    def _consume_barrier(self, minute: datetime) -> Any:
        contracts = self._config["candidate"]["contracts"]
        data_by_symbol = {
            contracts["future"]: self.datas[0],
            contracts["call"]: self.datas[1],
            contracts["put"]: self.datas[2],
        }
        result = None
        scope_reset = False
        for index, symbol in enumerate((contracts["future"], contracts["call"], contracts["put"])):
            bar = self._bar_evidence(symbol, minute, data_by_symbol[symbol], index)
            result = self._barrier.ingest(bar)
            if (
                result.reason
                in {
                    "SESSION_MISMATCH",
                    "GENERATION_MISMATCH",
                }
                and result.reset_warmup
            ):
                try:
                    self._barrier.reset_scope(
                        trading_day=bar.trading_day,
                        generation=bar.generation,
                        session_segment=bar.session_segment,
                        rules_hash=bar.rules_hash,
                        clock_domain=bar.clock_domain,
                        clock_mode=bar.clock_mode,
                        clock_mapping=bar.clock_mapping,
                        candidate_id=bar.candidate_id,
                    )
                except (TypeError, ValueError):
                    scope_reset = True
                    break
                scope_reset = True
                result = self._barrier.ingest(bar)
        assert result is not None
        self._barrier_results.append(
            {
                "reason": result.reason,
                "ready": result.ready,
                "reset_warmup": result.reset_warmup,
                "scope_reset": scope_reset,
            }
        )
        if scope_reset:
            self._history.clear()
        if not result.ready:
            if result.reset_warmup:
                self._history.clear()
            return None
        self._last_decision_input = result.decision_input
        return result.decision_input

    def _budget_allows(self) -> bool:
        budget = self._config["budget"]
        return (
            budget["path_requirement_cny"] <= budget["working_limit_cny"]
            and budget["path_requirement_cny"] + budget["recovery_reserve_cny"]
            <= budget["capital_limit_cny"]
        )

    def _remember_minute(self, minute_key: str) -> bool:
        if minute_key in self._seen_minutes:
            return False
        if len(self._seen_minute_order) == self._seen_minute_order.maxlen:
            self._seen_minutes.discard(self._seen_minute_order[0])
        self._seen_minute_order.append(minute_key)
        self._seen_minutes.add(minute_key)
        return True

    def _record_feature(self, features: MinuteFeatures) -> None:
        self._feature_history.append(features)

    def _decision_for(self, features: MinuteFeatures, decision_input: Any) -> Dict[str, Any]:
        outcome = "NO_EDGE"
        token_info: Optional[Dict[str, Any]] = None
        token_reason = None
        if features.signal_ready:
            if not self._budget_allows():
                outcome = "BUDGET_REJECTED"
            else:
                quantity = self._config["candidate"]["quantities"]
                token = self._tokens.issue(
                    features, decision_input, next_id=self._next_id, quantity=quantity
                )
                consumed, token_reason = self._tokens.consume(
                    token, decision_input, next_id=self._next_id
                )
                token_info = token.to_dict()
                outcome = "REPLAY_WRITE_DISABLED" if consumed else token_reason or "TOKEN_REJECTED"
        elif features.reason not in {
            self._feature_reason.NO_SIGNAL,
            self._feature_reason.NO_SIGNAL_NET_EDGE,
            self._feature_reason.NO_SIGNAL_DIRECTION,
        }:
            outcome = features.reason
        decision = {
            "kind": "ORDINARY_DECISION",
            "origin": "next",
            "minute": _iso(features.bucket_end),
            "history_bars_before_current": features.history_before_current,
            "signal_scope": "fq2_frozen_features",
            "feature_reason": features.reason,
            "feature_reasons": list(features.reasons),
            "tradable": features.signal_ready,
            "direction": features.direction,
            "residual_cny": float(features.residual_cny),
            "median_cny": None if features.median_cny is None else float(features.median_cny),
            "mad_cny": None if features.mad_cny is None else float(features.mad_cny),
            "z_score": None if features.z_score is None else float(features.z_score),
            "score_conversion_cny": float(features.score_conversion_cny),
            "score_reversal_cny": float(features.score_reversal_cny),
            "persistence_conversion": float(features.persistence_conversion),
            "persistence_reversal": float(features.persistence_reversal),
            "short_window_covered_ms": features.short_window_covered_ms,
            "long_window_covered_ms": features.long_window_covered_ms,
            "short_window_complete": features.short_window_complete,
            "long_window_complete": features.long_window_complete,
            "synchronized_states_5s": features.synchronized_states_5s,
            "source_skew_ms": float(features.source_skew_ms),
            "receive_skew_ms": float(features.receive_skew_ms),
            "outcome": outcome,
            "orders_submitted_for_decision": 0,
            "execution_permission": "NOT_PROVEN",
            "token": token_info,
            "token_consume_reason": token_reason,
            # Keep the causal input attached to each decision, rather than
            # relying on the report's mutable "last_input" snapshot.  This
            # makes a multi-minute replay auditable even after later bars are
            # consumed and prevents a decision from losing its three-leg
            # barrier provenance.
            "bar_ids": list(decision_input.bar_ids),
            "quote_cutoffs": dict(decision_input.quote_cutoffs),
            "source_sequences": {
                symbol: list(sequence)
                for symbol, sequence in decision_input.source_sequences.items()
            },
            "bucket_start": decision_input.bucket_start.isoformat(),
            "bucket_end": decision_input.bucket_end.isoformat(),
            "common_available_at": decision_input.common_available_at.isoformat(),
            "barrier_ready_mono": decision_input.barrier_ready_mono,
            "barrier_deadline_mono": decision_input.deadline_mono,
            "decision_input_key": [_decision_key(value) for value in decision_input.key],
        }
        self._ordinary_decisions.append(decision)
        self._minute_events.append(dict(decision))
        return decision

    def next(self) -> None:
        """Consume one complete closed-minute input exactly once."""

        if self._timing_only:
            self._timing_next()
            return
        self._next_id += 1
        minute = self._current_synchronous_minute()
        if minute is None:
            self._history.clear()
            self._minute_events.append({"kind": "SKIP_UNSYNCHRONIZED_BAR", "origin": "next"})
            return
        minute_key = _iso(minute)
        if not self._remember_minute(minute_key):
            return
        if self._last_minute is not None and minute - self._last_minute != timedelta(minutes=1):
            self._history.clear()
            self._minute_events.append(
                {"kind": "RESET_HISTORY_GAP", "origin": "next", "minute": minute_key}
            )
        decision_input = self._consume_barrier(minute)
        self._last_minute = minute
        self._last_closed_minute = minute
        if decision_input is None:
            self._minute_events.append(
                {"kind": "SKIP_INCOMPLETE_MINUTE", "origin": "next", "minute": minute_key}
            )
            return

        features = self._compute_features(
            decision_input, policy=self._policy, history=tuple(self._history)
        )
        self._record_feature(features)
        window_usable = (
            features.short_window_complete
            and features.long_window_complete
            and features.synchronized_states_5s >= self._policy.minimum_new_snapshots
            and features.source_skew_ms <= self._policy.max_cross_leg_skew_ms
            and features.receive_skew_ms <= self._policy.max_cross_leg_skew_ms
        )
        if window_usable:
            if len(self._history) < self._policy.history_bars:
                self._history.append(features.residual_cny)
                self._minute_events.append(
                    {
                        "kind": "WARMUP",
                        "origin": "next",
                        "minute": minute_key,
                        "history_bars": len(self._history),
                        "residual_cny": float(features.residual_cny),
                    }
                )
                return
            self._decision_for(features, decision_input)
            # The current valid residual becomes history only after the
            # decision has consumed its frozen input.  This applies equally
            # to a no-edge and budget-rejected decision; both are observations
            # of the minute and must roll the H60 window.
            self._history.append(features.residual_cny)
        else:
            self._history.clear()
            self._minute_events.append(
                {
                    "kind": "RESET_WARMUP_FEATURE_GAP",
                    "origin": "next",
                    "minute": minute_key,
                    "reason": features.reason,
                }
            )

    def notify_idle(self) -> None:
        """Project local timing facts on an actual no-bar Cerebro callback."""

        if self._timing_provider is not None:
            self._timing_idle()

    def notify_tick(self, tick: Any) -> None:
        """Validate a producer-supplied post-seal quote as a diagnostic only."""

        self._tick_callback_count += 1
        if not isinstance(tick, Mapping) or self._last_closed_minute is None:
            self._rejected_tick_count += 1
            return
        required = {
            "symbol",
            "exchange",
            "event_time",
            "received_at",
            "received_monotonic_ns",
            "ingest_seq",
            "generation",
            "trading_day",
            "session_segment",
            "rules_hash",
            "clock_domain",
            "clock_mode",
            "candidate_id",
            "quality",
            "volume_complete",
            "bid",
            "ask",
            "bid_qty",
            "ask_qty",
        }
        if not required.issubset(tick):
            self._rejected_tick_count += 1
            return
        event_time = _tick_datetime(tick["event_time"])
        received_at = _tick_datetime(tick["received_at"])
        if event_time is None or received_at is None or event_time > received_at:
            self._rejected_tick_count += 1
            return
        cutoff = self._last_closed_minute.replace(tzinfo=timezone.utc)
        if event_time >= cutoff or received_at >= cutoff:
            self._rejected_tick_count += 1
            return
        decision_input = self._last_decision_input
        if decision_input is None:
            self._rejected_tick_count += 1
            return
        symbol = tick["symbol"]
        if not isinstance(symbol, str) or symbol not in decision_input.bars:
            self._rejected_tick_count += 1
            return
        validation = validate_quote_against_bar(
            dict(tick),
            bar=decision_input.bars[symbol],
            max_skew_ms=self._barrier.policy.max_quote_skew_ms,
        )
        if not validation.accepted:
            self._rejected_tick_count += 1
            return
        self._accepted_tick_features.append(
            {
                "event_time": event_time.isoformat(),
                "received_at": received_at.isoformat(),
                "sequence": int(tick["ingest_seq"]),
                "cutoff": cutoff.isoformat(),
                "symbol": symbol,
                "bar_id": decision_input.bars[symbol].bar_id,
                "quote_cutoff_seq": decision_input.bars[symbol].quote_cutoff_seq,
                "ordinary_action": "NONE_LATER_TICK",
            }
        )

    @property
    def last_closed_minute(self) -> Optional[datetime]:
        return self._last_closed_minute

    def build_report(self) -> Dict[str, Any]:
        """Return a deterministic local report with explicit FQ2 evidence."""

        if self._timing_only:
            provider = self._timing_provider
            return {
                "status": "LOCAL_TIMING_REPLAY_PASS",
                "scope": "offline_local_timing_fixture",
                "mode": "replay",
                "timing": {
                    "results": list(self._timing_results),
                    "idle_callback_count": self._timing_idle_count,
                    "provider_next_calls": 0 if provider is None else provider.next_calls,
                    "provider_idle_calls": 0 if provider is None else provider.idle_calls,
                    "projector": (
                        {}
                        if self._timing_projector is None
                        else self._timing_projector.build_report()
                    ),
                    "execution_permission": "NOT_PROVEN",
                },
                "orders_submitted": 0,
                "external_network_requests": 0,
                "external_trade_writes": 0,
                "actual_order_permission": "NOT_PROVEN",
                "actual_pnl": None,
                "actual_pnl_status": "NOT_AVAILABLE",
                "gates": {
                    "G1_full_offline_contract": "BLOCKED",
                    "G2_package_native": "NOT_RUN",
                    "G3_first_set_read_only": "NOT_RUN",
                    "G4_simnow_mechanical": "NOT_RUN",
                    "R1_oos_research": "NOT_RUN",
                    "R2_natural_signal_research": "NOT_RUN",
                },
            }

        report = {
            "status": "LOCAL_REPLAY_PASS",
            "scope": "offline_local_replay_fixture",
            "mode": "replay",
            "candidate_id": self._config["candidate"]["candidate_id"],
            "contracts": dict(self._config["candidate"]["contracts"]),
            "minute_bar_interval": self._config["signal"]["bar_minutes"],
            "triple_leg_synchronization": "same candidate/session/generation minute input",
            "barrier": {
                "policy_timeout_seconds": self._barrier.policy.timeout_seconds,
                "timeframe_seconds": self._barrier.policy.timeframe_seconds,
                "last_input": (
                    self._last_decision_input.to_dict()
                    if self._last_decision_input is not None
                    else None
                ),
                "clock_mode": "replay",
                "clock_domain": "iter24-replay-clock",
                "quote_cutoff": "frozen_at_bar_seal",
                "tick_feature_scope": "full_5s_60s_window",
                "tradable_signal_scope": "fq2_frozen_features_only",
                "late_bar_policy": "retired_bucket_no_backfill",
                "results": list(self._barrier_results),
            },
            "feature_contract": {
                "short_window": "[T-5s,T)",
                "long_window": "[T-60s,T)",
                "max_segment_seconds": float(self._policy.max_segment_seconds),
                "max_cross_leg_skew_ms": float(self._policy.max_cross_leg_skew_ms),
                "history_bars": self._policy.history_bars,
                "current_residual_added_after_calculation": True,
            },
            "ordinary_decision_path": "closed minute bar next() only",
            "history_window_bars": self._config["signal"]["history_bars"],
            "ordinary_decision_count": len(self._ordinary_decisions),
            "ordinary_decisions": list(self._ordinary_decisions),
            "minute_events": list(self._minute_events),
            "feature_history": [feature.to_dict() for feature in self._feature_history],
            "rejections": list(self._rejections),
            "tick_callback_count": self._tick_callback_count,
            "accepted_cutoff_tick_features": list(self._accepted_tick_features),
            "rejected_tick_count": self._rejected_tick_count,
            "token_ledger": self._tokens.to_dict(),
            "orders_submitted": self._orders_submitted,
            "external_network_requests": 0,
            "external_trade_writes": 0,
            "local_broker": "BackBroker",
            "execution_basis": "no_execution_replay_decision_fixture",
            "actual_order_permission": "NOT_PROVEN",
            "actual_pnl": None,
            "actual_pnl_status": "NOT_AVAILABLE",
            "pnl_statement": "This report is not live, SimNow, hypothetical-fill, or actual PnL.",
            "gates": {
                "G1_full_offline_contract": "BLOCKED",
                "G2_package_native": "NOT_RUN",
                "G3_first_set_read_only": "NOT_RUN",
                "G4_simnow_mechanical": "NOT_RUN",
                "R1_oos_research": "NOT_RUN",
                "R2_natural_signal_research": "NOT_RUN",
            },
        }
        if self._timing_projector is not None:
            report["timing"] = {
                "results": list(self._timing_results),
                "idle_callback_count": self._timing_idle_count,
                "projector": self._timing_projector.build_report(),
                "execution_permission": "NOT_PROVEN",
            }
        return report


__all__ = [
    "CTPOptionsMidFrequencyStrategy",
    "ConfigurationError",
    "DecisionToken",
    "validate_config",
]
