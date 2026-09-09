"""Frozen deterministic minute/quote fusion and cost admission for SA v0."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence

try:
    from .features import FastFeatures
except ImportError:  # Direct execution from the example directory.
    from features import FastFeatures


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


@dataclass(frozen=True)
class MinuteFeatures:
    ready: bool
    reasons: tuple[str, ...]
    bar_id: str
    bar_end: float
    available_at: float
    trading_day: str
    ema5: float | None = None
    ema20: float | None = None
    atr14: float | None = None
    trend: float | None = None
    return1: float | None = None
    return3: float | None = None
    return5: float | None = None
    volume_ratio: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CostInputs:
    tick_size: float
    multiplier: float
    lots: int
    entry_price: float
    exit_price: float
    open_money_rate: float
    open_volume_rate: float
    close_money_rate: float
    close_volume_rate: float
    entry_slip_ticks: float = 1.0
    exit_slip_ticks: float = 1.0
    edge_buffer_ticks: float = 1.0
    verified: bool = False
    source: str = ""

    def validate(self) -> None:
        numeric = (
            self.tick_size,
            self.multiplier,
            self.entry_price,
            self.exit_price,
            self.open_money_rate,
            self.open_volume_rate,
            self.close_money_rate,
            self.close_volume_rate,
            self.entry_slip_ticks,
            self.exit_slip_ticks,
            self.edge_buffer_ticks,
        )
        if not all(math.isfinite(float(value)) and float(value) >= 0 for value in numeric):
            raise ValueError("cost inputs must be finite and nonnegative")
        if self.tick_size <= 0 or self.multiplier <= 0 or self.lots != 1:
            raise ValueError("v0 cost gate requires positive tick/multiplier and exactly one lot")
        if not self.source:
            raise ValueError("fee source is required")


@dataclass(frozen=True)
class CostDecision:
    admitted: bool
    move_proxy_ticks: float
    roundtrip_cost_ticks: float
    required_ticks: float
    open_fee_cny: float
    close_fee_cny: float
    fee_verified: bool
    fee_source: str


@dataclass(frozen=True)
class FusionDecision:
    ready: bool
    reasons: tuple[str, ...]
    direction: int
    h_score: float | None
    k_score: float | None
    score: float | None
    prediction_kind: str
    contributions: dict[str, float]
    cost: CostDecision | None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value


def minute_features(
    *,
    closes: Sequence[tuple[float, float]],
    current_volume: float,
    previous_volumes: Sequence[tuple[str, float]],
    trading_day: str,
    ema5: float,
    ema20: float,
    atr14: float,
    tick_size: float,
    bar_id: str,
    bar_end: float,
    available_at: float,
) -> MinuteFeatures:
    reasons: list[str] = []
    values = tuple(closes)
    if len(values) < 6:
        reasons.append("closed_bars_lt_6")
    if not all(math.isfinite(float(value)) for value in (ema5, ema20, atr14, tick_size)):
        reasons.append("native_indicator_invalid")
    if tick_size <= 0 or atr14 <= 0:
        reasons.append("native_indicator_not_ready")
    if values:
        expected = values[-1][0] - 60.0 * (len(values) - 1)
        for index, (stamp, _close) in enumerate(values):
            if abs(stamp - (expected + 60.0 * index)) > 1.0e-6:
                reasons.append("minute_return_gap")
                break
    returns: dict[int, float | None] = {1: None, 3: None, 5: None}
    if len(values) >= 6 and atr14 > 0 and tick_size > 0:
        current_close = float(values[-1][1])
        scale = max(float(atr14), float(tick_size))
        for horizon in returns:
            returns[horizon] = _clip((current_close - float(values[-1 - horizon][1])) / scale)
    prior = tuple(previous_volumes)
    if len(prior) != 20:
        reasons.append("previous_valid_volumes_ne_20")
        volume_ratio = None
    elif any(day != trading_day for day, _value in prior):
        reasons.append("volume_history_crosses_trading_day")
        volume_ratio = None
    elif any(not math.isfinite(float(value)) or float(value) < 0 for _day, value in prior):
        reasons.append("volume_history_invalid")
        volume_ratio = None
    else:
        mean_volume = sum(float(value) for _day, value in prior) / 20.0
        if mean_volume <= 0:
            reasons.append("volume_history_zero_mean")
            volume_ratio = None
        elif not math.isfinite(float(current_volume)) or float(current_volume) < 0:
            reasons.append("current_volume_invalid")
            volume_ratio = None
        else:
            volume_ratio = float(current_volume) / mean_volume
    if available_at > bar_end + 5.0:
        reasons.append("bar_delivery_late")
    trend = None
    if atr14 > 0 and tick_size > 0 and all(math.isfinite(v) for v in (ema5, ema20)):
        trend = _clip((ema5 - ema20) / max(atr14, tick_size))
    return MinuteFeatures(
        ready=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        bar_id=bar_id,
        bar_end=float(bar_end),
        available_at=float(available_at),
        trading_day=trading_day,
        ema5=float(ema5) if math.isfinite(float(ema5)) else None,
        ema20=float(ema20) if math.isfinite(float(ema20)) else None,
        atr14=float(atr14) if math.isfinite(float(atr14)) else None,
        trend=trend,
        return1=returns[1],
        return3=returns[3],
        return5=returns[5],
        volume_ratio=volume_ratio,
    )


def roundtrip_cost(
    spread_ticks: float, inputs: CostInputs, move_proxy_ticks: float
) -> CostDecision:
    inputs.validate()
    if not math.isfinite(float(spread_ticks)) or spread_ticks < 0:
        raise ValueError("spread_ticks must be finite and nonnegative")
    open_fee = (
        inputs.entry_price * inputs.multiplier * inputs.lots * inputs.open_money_rate
        + inputs.lots * inputs.open_volume_rate
    )
    close_fee = (
        inputs.exit_price * inputs.multiplier * inputs.lots * inputs.close_money_rate
        + inputs.lots * inputs.close_volume_rate
    )
    fee_ticks = (open_fee + close_fee) / (inputs.multiplier * inputs.lots * inputs.tick_size)
    cost_ticks = float(spread_ticks) + inputs.entry_slip_ticks + inputs.exit_slip_ticks + fee_ticks
    required = cost_ticks + inputs.edge_buffer_ticks
    return CostDecision(
        admitted=float(move_proxy_ticks) > required,
        move_proxy_ticks=float(move_proxy_ticks),
        roundtrip_cost_ticks=cost_ticks,
        required_ticks=required,
        open_fee_cny=open_fee,
        close_fee_cny=close_fee,
        fee_verified=bool(inputs.verified),
        fee_source=inputs.source,
    )


def fuse(
    fast: FastFeatures,
    minute: MinuteFeatures,
    costs: CostInputs,
    *,
    entry_score: float = 0.35,
) -> FusionDecision:
    reasons = list(fast.reasons) + list(minute.reasons)
    if not fast.ready:
        reasons.append("fast_features_not_ready")
    if not minute.ready:
        reasons.append("minute_features_not_ready")
    if reasons:
        return FusionDecision(
            False,
            tuple(dict.fromkeys(reasons)),
            0,
            None,
            None,
            None,
            "uncalibrated_score",
            {},
            None,
        )
    h_components = {
        "imbalance_5s": 0.45 * float(fast.imbalance_5s),
        "micro_dev": 0.20 * float(fast.micro_dev),
        "ofi_5s": 0.25 * float(fast.ofi_5s),
        "momentum_15s": 0.10 * float(fast.momentum_15s),
    }
    k_components = {
        "trend": 0.65 * float(minute.trend),
        "return3": 0.35 * float(minute.return3),
    }
    h_score = sum(h_components.values())
    k_score = sum(k_components.values())
    score = 0.40 * h_score + 0.60 * k_score
    direction = 1 if score > 0 else -1 if score < 0 else 0
    move_proxy = abs(score) * min(float(minute.atr14) / costs.tick_size, 10.0)
    cost = roundtrip_cost(float(fast.spread_ticks), costs, move_proxy)
    if h_score == 0 or k_score == 0 or math.copysign(1.0, h_score) != math.copysign(1.0, k_score):
        reasons.append("fast_and_minute_disagree")
    if abs(score) < float(entry_score):
        reasons.append("entry_score_below_threshold")
    if not cost.admitted:
        reasons.append("roundtrip_cost_gate")
    contributions = {
        **{f"H.{key}": value for key, value in h_components.items()},
        **{f"K.{key}": value for key, value in k_components.items()},
    }
    return FusionDecision(
        ready=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        direction=direction,
        h_score=h_score,
        k_score=k_score,
        score=score,
        prediction_kind="uncalibrated_score",
        contributions=contributions,
        cost=cost,
    )


class ConfirmationTracker:
    """Require fresh quote-driven confirmation for one immutable bar version."""

    def __init__(self, seconds: float = 2.0, quotes: int = 3) -> None:
        self.seconds = float(seconds)
        self.quotes = int(quotes)
        self.reset()

    def reset(self) -> None:
        self.direction = 0
        self.bar_id = ""
        self.started_at: float | None = None
        self.last_quote_time: float | None = None
        self.count = 0

    def observe(self, *, direction: int, bar_id: str, quote_time: float, eligible: bool) -> bool:
        if not eligible or direction not in {-1, 1}:
            self.reset()
            return False
        if (
            self.direction != direction
            or self.bar_id != bar_id
            or self.last_quote_time is not None
            and quote_time <= self.last_quote_time
        ):
            self.reset()
            self.direction = direction
            self.bar_id = bar_id
            self.started_at = float(quote_time)
        self.count += 1
        self.last_quote_time = float(quote_time)
        return self.count >= self.quotes and quote_time - float(self.started_at) >= self.seconds
