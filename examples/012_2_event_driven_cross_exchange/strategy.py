"""Independent taker-taker event-driven strategy for cross-exchange perpetuals.

This implementation does not inherit or import the 012_1 mean-reversion
strategy.  It treats each continuous L2 event as a short-lived executable
opportunity and requires the opportunity to outlive a conservative path p99.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
import time
from typing import Dict, Iterable, Mapping, Optional, Tuple

import backtrader as bt
from bt_api_py import Freshness

from bt_api_py.cross_venue import (
    CostBreakdown,
    CrossVenueLeg as InstrumentRule,
    CrossVenueValueError as CrossExchangeValueError,
    ExecutableVWAP,
    FundingSnapshot as FundingState,
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
MARKOUT_HORIZONS_MS = (10, 50, 100, 500)
EVENT_PATH_LATENCY_SCOPE = "signal_to_hedge_terminal"
EVENT_PATH_EVIDENCE_ROLE = "walk_forward_oos"


def _decimal_token(value) -> str:
    converted = decimal_value(value)
    if converted == 0:
        return "0"
    return format(converted.normalize(), "f")


def event_fee_bucket(rules: Mapping[str, InstrumentRule], buy_venue: str, sell_venue: str) -> str:
    """Return the exact directional taker-fee bucket used by a path model."""

    return (
        f"buy={_decimal_token(rules[buy_venue].taker_fee)};"
        f"sell={_decimal_token(rules[sell_venue].taker_fee)}"
    )


def event_depth_bucket(
    books: Mapping[str, "EventBook"],
    buy_venue: str,
    sell_venue: str,
    quantity: Decimal,
) -> str:
    """Bucket the executable entry depth as a multiple of the proposed quantity."""

    buy_depth = sum(size for _, size in books[buy_venue].asks)
    sell_depth = sum(size for _, size in books[sell_venue].bids)
    multiple = min(buy_depth, sell_depth) / quantity
    if multiple < 2:
        return "1x_to_2x"
    if multiple < 5:
        return "2x_to_5x"
    if multiple < 10:
        return "5x_to_10x"
    return "10x_plus"


def _event_path_model_payload(value: Mapping[str, object]) -> dict:
    direction = tuple(value["direction"])
    return {
        "direction": list(direction),
        "first_venue": str(value["first_venue"]),
        "fee_bucket": str(value["fee_bucket"]),
        "depth_bucket": str(value["depth_bucket"]),
        "end_to_end_path_p99_seconds": _decimal_token(value["end_to_end_path_p99_seconds"]),
        "sample_count": int(value["sample_count"]),
        "qualified": value["qualified"],
        "source_data_sha256": str(value["source_data_sha256"]),
        "evidence_role": str(value["evidence_role"]),
        "latency_scope": str(value["latency_scope"]),
    }


def event_path_model_sha256(value: Mapping[str, object]) -> str:
    """Hash the immutable fields of an event-path qualification artifact."""

    payload = _event_path_model_payload(value)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EventPathQualification:
    """Content-addressed OOS qualification for one executable order path."""

    direction: Tuple[str, str]
    first_venue: str
    fee_bucket: str
    depth_bucket: str
    end_to_end_path_p99_seconds: Decimal
    sample_count: int
    qualified: bool
    source_data_sha256: str
    model_sha256: str
    evidence_role: str = EVENT_PATH_EVIDENCE_ROLE
    latency_scope: str = EVENT_PATH_LATENCY_SCOPE

    def __post_init__(self) -> None:
        direction = tuple(self.direction)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(
            self,
            "end_to_end_path_p99_seconds",
            decimal_value(
                self.end_to_end_path_p99_seconds,
                "end_to_end_path_p99_seconds",
            ),
        )
        if len(direction) != 2 or set(direction) != set(VENUE_SYMBOLS):
            raise ValueError("event path direction must contain both configured venues")
        if self.first_venue not in direction:
            raise ValueError("event path first venue must belong to its direction")
        if not self.fee_bucket or not self.depth_bucket:
            raise ValueError("event path fee and depth buckets are required")
        if self.end_to_end_path_p99_seconds <= 0:
            raise ValueError("event path p99 must be positive")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int):
            raise ValueError("event path sample_count must be an integer")
        if self.sample_count < 0 or not isinstance(self.qualified, bool):
            raise ValueError("event path qualification fields are invalid")
        for name in ("source_data_sha256", "model_sha256"):
            digest = str(getattr(self, name))
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    @property
    def route_key(self) -> str:
        buy_venue, sell_venue = self.direction
        return f"{buy_venue}->{sell_venue}|first={self.first_venue}"

    @property
    def path_key(self) -> Tuple[str, str, str, str, str]:
        return (*self.direction, self.first_venue, self.fee_bucket, self.depth_bucket)

    def as_dict(self) -> dict:
        return {**_event_path_model_payload(asdict(self)), "model_sha256": self.model_sha256}

    def rejection(self, *, minimum_samples: int) -> Optional[str]:
        if not self.qualified:
            return "event_model_not_qualified"
        if self.evidence_role != EVENT_PATH_EVIDENCE_ROLE:
            return "event_model_evidence_role"
        if self.latency_scope != EVENT_PATH_LATENCY_SCOPE:
            return "event_model_latency_scope"
        if self.sample_count < minimum_samples:
            return "event_model_sample_count"
        if event_path_model_sha256(asdict(self)) != self.model_sha256:
            return "event_model_fingerprint"
        return None


@dataclass(frozen=True)
class EventBook:
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
    recovery_snapshot: bool = False
    funding_rate: Decimal = Decimal(0)
    next_funding_time: Optional[Decimal] = None


@dataclass(frozen=True)
class VenueExecutionStats:
    ack_p99_seconds: Decimal = Decimal("0.05")
    reject_rate: Decimal = Decimal(0)

    def __post_init__(self):
        object.__setattr__(
            self,
            "ack_p99_seconds",
            decimal_value(self.ack_p99_seconds, "ack_p99_seconds"),
        )
        object.__setattr__(self, "reject_rate", decimal_value(self.reject_rate, "reject_rate"))
        if self.ack_p99_seconds < 0 or not 0 <= self.reject_rate <= 1:
            raise ValueError("invalid venue execution statistics")


@dataclass(frozen=True)
class EventDrivenRisk:
    quantity_base: Decimal = Decimal("0.01")
    maximum_quote_age_seconds: Decimal = Decimal("0.5")
    maximum_venue_skew_seconds: Decimal = Decimal("0.25")
    minimum_opportunity_lifetime_seconds: Decimal = Decimal("0.5")
    path_p99_seconds: Decimal = Decimal("0.005")
    entry_deadline_seconds: Decimal = Decimal("1")
    hedge_deadline_seconds: Decimal = Decimal("1")
    cancel_deadline_seconds: Decimal = Decimal("0.5")
    pair_deadline_seconds: Decimal = Decimal("2.5")
    flatten_deadline_seconds: Decimal = Decimal("2.5")
    maximum_holding_seconds: Decimal = Decimal("2.5")
    depth_fraction: Decimal = Decimal("0.20")
    exit_reserve_bps: Decimal = Decimal("1")
    latency_reserve_bps: Decimal = Decimal("2")
    failure_reserve_bps: Decimal = Decimal("3")
    model_buffer_bps: Decimal = Decimal("2")
    minimum_net_edge_bps: Decimal = Decimal("1")
    maximum_loss_bps: Decimal = Decimal("100")
    account_maximum_loss_bps: Decimal = Decimal("50")
    maximum_adverse_markout_bps: Decimal = Decimal("1")
    markout_tail_probability: Decimal = Decimal("0.95")
    markout_tolerance_seconds: Decimal = Decimal("0.010")
    minimum_markout_samples: Decimal = Decimal("21")
    maximum_markout_miss_ratio: Decimal = Decimal("0.25")

    def __post_init__(self):
        for name, value in asdict(self).items():
            converted = decimal_value(value, name)
            object.__setattr__(self, name, converted)
            if converted < 0:
                raise ValueError(f"{name} must be nonnegative")
        if self.quantity_base <= 0 or self.maximum_quote_age_seconds <= 0:
            raise ValueError("quantity and quote age must be positive")
        if self.account_maximum_loss_bps <= 0:
            raise ValueError("account_maximum_loss_bps must be positive")
        if not 0 < self.depth_fraction <= 1:
            raise ValueError("depth_fraction must be in (0, 1]")
        if not (
            0 < self.entry_deadline_seconds <= self.pair_deadline_seconds
            and 0 < self.hedge_deadline_seconds <= self.pair_deadline_seconds
            and 0 < self.cancel_deadline_seconds <= self.pair_deadline_seconds
        ):
            raise ValueError("leg deadlines must not exceed the pair deadline")
        if self.flatten_deadline_seconds <= 0 or self.markout_tolerance_seconds <= 0:
            raise ValueError("flatten and markout tolerance must be positive")
        if self.minimum_markout_samples < 0:
            raise ValueError("minimum_markout_samples must be nonnegative")
        if not 0 <= self.maximum_markout_miss_ratio < 1:
            raise ValueError("maximum_markout_miss_ratio must be in [0, 1)")
        if not 0 < self.markout_tail_probability < 1:
            raise ValueError("markout_tail_probability must be in (0, 1)")


@dataclass(frozen=True)
class EventIntent:
    long_venue: str
    short_venue: str
    first_venue: str
    quantity_base: Decimal
    buy_price: Decimal
    sell_price: Decimal
    opportunity_lifetime: Decimal
    cost: CostBreakdown
    created_at: Decimal
    entry_buy: ExecutableVWAP
    entry_sell: ExecutableVWAP
    exit_sell_preview: ExecutableVWAP
    exit_buy_preview: ExecutableVWAP

    def as_dict(self):
        return {
            "long_venue": self.long_venue,
            "short_venue": self.short_venue,
            "first_venue": self.first_venue,
            "quantity_base": str(self.quantity_base),
            "buy_price": str(self.buy_price),
            "sell_price": str(self.sell_price),
            "opportunity_lifetime": str(self.opportunity_lifetime),
            "cost": self.cost.as_dict(),
            "created_at": str(self.created_at),
            "entry_buy": self.entry_buy.as_dict(),
            "entry_sell": self.entry_sell.as_dict(),
            "exit_sell_preview": self.exit_sell_preview.as_dict(),
            "exit_buy_preview": self.exit_buy_preview.as_dict(),
        }


@dataclass
class EventActivePair:
    intent: EventIntent
    opened_at: Decimal
    quantity_base: Decimal
    entry_buy: ExecutableVWAP
    entry_sell: ExecutableVWAP
    entry_fees_paid: Optional[Decimal]
    funding_snapshot: Mapping[str, Tuple[object, ...]]


class EventArbitrageEngine:
    """Pure continuous-book decision engine with no mean-reversion state."""

    def __init__(
        self,
        rules: Mapping[str, InstrumentRule],
        risk: EventDrivenRisk,
        venue_stats: Optional[Mapping[str, VenueExecutionStats]] = None,
        admission_models: Optional[Iterable[EventPathQualification]] = None,
    ):
        if set(rules) != set(VENUE_SYMBOLS):
            raise ValueError("rules must contain okx and binance")
        self.rules = dict(rules)
        self.risk = risk
        self.venue_stats = {
            venue: (venue_stats or {}).get(venue, VenueExecutionStats()) for venue in VENUE_SYMBOLS
        }
        raw_models = (
            admission_models.values()
            if isinstance(admission_models, Mapping)
            else (admission_models or ())
        )
        self.admission_models = {}
        for model in raw_models:
            if not isinstance(model, EventPathQualification):
                raise ValueError("admission_models must contain EventPathQualification values")
            if model.path_key in self.admission_models:
                raise ValueError("event path qualifications must have unique bindings")
            self.admission_models[model.path_key] = model
        self.books: Dict[str, EventBook] = {}
        self.last_sequences: Dict[str, int] = {}
        self.gapped_venues = set()
        self.reject_reasons: Counter[str] = Counter()
        self.opportunity_direction: Optional[Tuple[str, str]] = None
        self.opportunity_path_key: Optional[Tuple[str, str, str, str, str]] = None
        self.opportunity_started: Optional[Decimal] = None
        self.intents = deque(maxlen=256)
        self.cost_history = deque(maxlen=256)
        self.pending_markouts = []
        self.markouts = {str(value): {} for value in MARKOUT_HORIZONS_MS}
        self.markout_observations = {str(value): {} for value in MARKOUT_HORIZONS_MS}
        self._last_markout_probe_at = Decimal("-Infinity")
        self.current_markout_reserve = Decimal(0)
        self.halted_unknown = False
        self.active_pair: Optional[EventActivePair] = None
        self.last_exit_economics = None

    def reject(self, reason: str) -> None:
        self.reject_reasons[reason] += 1

    def update_book(self, book: EventBook) -> bool:
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
            if not book.recovery_snapshot and broken_delta:
                self.gapped_venues.add(book.venue)
                self.last_sequences[book.venue] = sequence
                self.reject("sequence_gap")
                return False
        if book.recovery_snapshot or (
            snapshot_kind == "snapshot" and continuity in ORDERBOOK_HEALTHY_CONTINUITY
        ):
            self.gapped_venues.discard(book.venue)
        self.last_sequences[book.venue] = sequence
        self.books[book.venue] = book
        self._collect_markouts(book.receive_time)
        return True

    def _fresh(self, now: Decimal) -> bool:
        if self.halted_unknown:
            self.reject("unknown_execution")
            return False
        if set(self.books) != set(VENUE_SYMBOLS):
            self.reject("missing_book")
            return False
        if self.gapped_venues:
            self.reject("sequence_gap")
            return False
        books = tuple(self.books.values())
        if len({book.clock_domain_id for book in books}) != 1:
            self.reject("clock_domain")
            return False
        if any(now < book.receive_time for book in books):
            self.reject("future_receive_time")
            return False
        if any(now - book.receive_time > self.risk.maximum_quote_age_seconds for book in books):
            self.reject("stale")
            return False
        if (
            abs(books[0].receive_time - books[1].receive_time)
            > self.risk.maximum_venue_skew_seconds
        ):
            self.reject("venue_skew")
            return False
        return True

    def _quantity(self, buy_venue: str, sell_venue: str) -> Optional[Decimal]:
        buy_depth = sum(size for _, size in self.books[buy_venue].asks)
        sell_depth = sum(size for _, size in self.books[sell_venue].bids)
        requested = min(
            self.risk.quantity_base,
            buy_depth * self.risk.depth_fraction,
            sell_depth * self.risk.depth_fraction,
        )
        lattice = quantity_lattice(requested, self.rules.values())
        if not lattice.tradable:
            self.reject("depth")
            return None
        return lattice.quantity_base

    def _signed_funding(self, buy_venue: str, sell_venue: str, quantity: Decimal) -> Decimal:
        result = Decimal(0)
        for venue, side in ((buy_venue, "long"), (sell_venue, "short")):
            book = self.books[venue]
            count = funding_settlement_count(
                book.exchange_time,
                book.next_funding_time,
                self.risk.maximum_holding_seconds,
                self.rules[venue].funding_interval_seconds,
            )
            mid = (book.bids[0][0] + book.asks[0][0]) / 2
            result += signed_funding_cashflow(quantity * mid, book.funding_rate, side, count)
        return result

    def _cost(
        self,
        buy_venue: str,
        sell_venue: str,
        now: Decimal,
        *,
        adverse_markout_reserve: Decimal = Decimal(0),
    ):
        quantity = self._quantity(buy_venue, sell_venue)
        if quantity is None:
            return None
        try:
            buy = executable_vwap(self.books[buy_venue].asks, quantity, "buy")
            sell = executable_vwap(self.books[sell_venue].bids, quantity, "sell")
            exit_sell = executable_vwap(self.books[buy_venue].bids, quantity, "sell")
            exit_buy = executable_vwap(self.books[sell_venue].asks, quantity, "buy")
            if (
                buy.notional < self.rules[buy_venue].minimum_notional
                or sell.notional < self.rules[sell_venue].minimum_notional
            ):
                raise CrossExchangeValueError("venue minimum notional is not satisfied")
        except CrossExchangeValueError:
            self.reject("depth")
            return None
        mean_notional = (buy.notional + sell.notional) / 2
        bps = Decimal("10000")
        long_mid = (self.books[buy_venue].bids[0][0] + self.books[buy_venue].asks[0][0]) / 2
        short_mid = (self.books[sell_venue].bids[0][0] + self.books[sell_venue].asks[0][0]) / 2
        executable_exit_cost = max(Decimal(0), quantity * long_mid - exit_sell.notional) + max(
            Decimal(0), exit_buy.notional - quantity * short_mid
        )
        cost = round_trip_cost(
            quantity_base=quantity,
            entry_buy=buy,
            entry_sell=sell,
            buy_fee_rate=self.rules[buy_venue].taker_fee,
            sell_fee_rate=self.rules[sell_venue].taker_fee,
            # This candidate has no admitted exit-basis model yet.  A zero
            # target preserves research-formula observability only; network
            # execution remains locked by the candidate manifest and runner.
            expected_exit_basis=Decimal(0),
            expected_exit_buy_price=exit_buy.price,
            expected_exit_sell_price=exit_sell.price,
            expected_exit_execution_cost=(
                executable_exit_cost + mean_notional * self.risk.exit_reserve_bps / bps
            ),
            signed_funding=self._signed_funding(buy_venue, sell_venue, quantity),
            latency_reserve=mean_notional * self.risk.latency_reserve_bps / bps,
            failure_reserve=mean_notional * self.risk.failure_reserve_bps / bps,
            model_buffer=(
                mean_notional * self.risk.model_buffer_bps / bps
                + decimal_value(adverse_markout_reserve, "adverse_markout_reserve")
            ),
        )
        self.cost_history.append(cost)
        return quantity, buy, sell, exit_sell, exit_buy, cost

    def _first_venue(self, long_venue: str, short_venue: str, quantity: Decimal) -> str:
        def score(venue):
            stats = self.venue_stats[venue]
            book = self.books[venue]
            relevant_depth = sum(
                size for _, size in (book.asks if venue == long_venue else book.bids)
            )
            depth_risk = quantity / relevant_depth if relevant_depth > 0 else Decimal("Infinity")
            return stats.reject_rate, stats.ack_p99_seconds, depth_risk

        return min((long_venue, short_venue), key=score)

    @staticmethod
    def _route_key(direction: Tuple[str, str], first_venue: str) -> str:
        return f"{direction[0]}->{direction[1]}|first={first_venue}"

    def _path_key(
        self,
        direction: Tuple[str, str],
        first_venue: str,
        quantity: Decimal,
    ) -> Tuple[str, str, str, str, str]:
        buy_venue, sell_venue = direction
        return (
            buy_venue,
            sell_venue,
            first_venue,
            event_fee_bucket(self.rules, buy_venue, sell_venue),
            event_depth_bucket(self.books, buy_venue, sell_venue, quantity),
        )

    def _admission_model(
        self,
        direction: Tuple[str, str],
        first_venue: str,
        quantity: Decimal,
    ) -> Optional[EventPathQualification]:
        model = self.admission_models.get(self._path_key(direction, first_venue, quantity))
        if model is None:
            self.reject("event_model_missing")
            return None
        reason = model.rejection(minimum_samples=max(1, int(self.risk.minimum_markout_samples)))
        if reason is not None:
            self.reject(reason)
            return None
        return model

    def _markout_series(self, horizon: str, route_key: str):
        return self.markouts[horizon].setdefault(route_key, deque(maxlen=4096))

    def _markout_observation_series(self, horizon: str, route_key: str):
        return self.markout_observations[horizon].setdefault(route_key, deque(maxlen=4096))

    def _adverse_tail_cvar(self, samples) -> Decimal:
        ordered = sorted(decimal_value(value, "markout") for value in samples)
        if not ordered:
            return Decimal(0)
        rank = max(
            0,
            int(
                (self.risk.markout_tail_probability * Decimal(len(ordered))).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            - 1,
        )
        tail = ordered[rank:]
        return sum(tail, Decimal(0)) / Decimal(len(tail))

    def _markout_gate(
        self,
        mean_notional: Decimal,
        direction: Tuple[str, str],
        first_venue: str,
    ):
        route_key = self._route_key(direction, first_venue)
        samples = self._markout_series("500", route_key)
        observations = self._markout_observation_series("500", route_key)
        minimum = int(self.risk.minimum_markout_samples)
        if len(samples) < minimum:
            self.reject("markout_insufficient_samples")
            return False, Decimal(0)
        if observations:
            misses = sum(1 for row in observations if row.get("status") != "observed")
            if Decimal(misses) / Decimal(len(observations)) > self.risk.maximum_markout_miss_ratio:
                self.reject("markout_missing_ratio")
                return False, Decimal(0)
        elif minimum:
            self.reject("markout_observation_missing")
            return False, Decimal(0)
        window = list(samples)[-max(minimum, 21, 1) :]
        adverse_tail = max(Decimal(0), self._adverse_tail_cvar(window))
        maximum_adverse = mean_notional * self.risk.maximum_adverse_markout_bps / Decimal("10000")
        if adverse_tail > maximum_adverse:
            self.reject("adverse_markout")
            return False, adverse_tail
        return True, adverse_tail

    def _markout_allows_entry(
        self,
        mean_notional: Decimal,
        direction: Tuple[str, str],
        first_venue: str,
    ) -> bool:
        allowed, _reserve = self._markout_gate(mean_notional, direction, first_venue)
        return allowed

    def _schedule_markout_probe(
        self,
        now: Decimal,
        direction: Tuple[str, str],
        first_venue: str,
        quantity: Decimal,
        baseline: Decimal,
    ) -> None:
        if now - self._last_markout_probe_at < self.risk.minimum_opportunity_lifetime_seconds:
            return
        self._last_markout_probe_at = now
        self.pending_markouts.extend(
            {
                "due": now + Decimal(horizon) / Decimal(1000),
                "created_at": now,
                "horizon": str(horizon),
                "direction": direction,
                "first_venue": first_venue,
                "route_key": self._route_key(direction, first_venue),
                "quantity": quantity,
                "baseline": baseline,
            }
            for horizon in MARKOUT_HORIZONS_MS
        )
        if len(self.pending_markouts) > 4096:
            overflow = len(self.pending_markouts) - 4096
            del self.pending_markouts[:overflow]
            self.reject("markout_probe_overflow")

    def evaluate(self, now_value) -> Optional[EventIntent]:
        now = decimal_value(now_value, "now")
        if not self._fresh(now):
            self.opportunity_direction = None
            self.opportunity_path_key = None
            self.opportunity_started = None
            return None
        candidates = []
        for buy_venue, sell_venue in (("okx", "binance"), ("binance", "okx")):
            calculated = self._cost(buy_venue, sell_venue, now)
            if calculated is None:
                continue
            quantity, buy, sell, exit_sell, exit_buy, cost = calculated
            minimum_net = (
                (buy.notional + sell.notional)
                / Decimal(2)
                * self.risk.minimum_net_edge_bps
                / Decimal("10000")
            )
            if cost.expected_net > minimum_net:
                candidates.append(
                    (
                        cost.expected_net,
                        buy_venue,
                        sell_venue,
                        quantity,
                        buy,
                        sell,
                        exit_sell,
                        exit_buy,
                        cost,
                    )
                )
        if not candidates:
            self.reject("net_edge")
            self.opportunity_direction = None
            self.opportunity_path_key = None
            self.opportunity_started = None
            return None
        _, buy_venue, sell_venue, quantity, buy, sell, exit_sell, exit_buy, cost = max(candidates)
        direction = (buy_venue, sell_venue)
        first_venue = self._first_venue(buy_venue, sell_venue, quantity)
        path_key = self._path_key(direction, first_venue, quantity)
        if path_key != self.opportunity_path_key:
            self.opportunity_direction = direction
            self.opportunity_path_key = path_key
            self.opportunity_started = now
            self.reject("opportunity_too_short")
            return None
        lifetime = now - self.opportunity_started
        if lifetime < self.risk.minimum_opportunity_lifetime_seconds:
            self.reject("opportunity_too_short")
            return None
        mean_notional = (buy.notional + sell.notional) / Decimal(2)
        self._schedule_markout_probe(
            now,
            direction,
            first_venue,
            quantity,
            cost.entry_executable_edge,
        )
        model = self._admission_model(direction, first_venue, quantity)
        if model is None:
            return None
        if lifetime < model.end_to_end_path_p99_seconds:
            self.reject("opportunity_shorter_than_measured_path_p99")
            return None
        markout_allowed, markout_reserve = self._markout_gate(
            mean_notional,
            direction,
            first_venue,
        )
        if not markout_allowed:
            self.opportunity_started = now
            return None
        self.current_markout_reserve = markout_reserve
        if markout_reserve:
            adjusted = self._cost(
                buy_venue,
                sell_venue,
                now,
                adverse_markout_reserve=markout_reserve,
            )
            if adjusted is None:
                return None
            quantity, buy, sell, exit_sell, exit_buy, cost = adjusted
            minimum_net = mean_notional * self.risk.minimum_net_edge_bps / Decimal("10000")
            if cost.expected_net <= minimum_net:
                self.reject("net_edge_after_markout")
                self.opportunity_started = now
                return None
        intent = EventIntent(
            long_venue=buy_venue,
            short_venue=sell_venue,
            first_venue=first_venue,
            quantity_base=quantity,
            buy_price=buy.price,
            sell_price=sell.price,
            opportunity_lifetime=lifetime,
            cost=cost,
            created_at=now,
            entry_buy=buy,
            entry_sell=sell,
            exit_sell_preview=exit_sell,
            exit_buy_preview=exit_buy,
        )
        self.intents.append(intent)
        self.opportunity_started = now
        return intent

    @staticmethod
    def _confirmed_fill(side: str, quantity: Decimal, price) -> ExecutableVWAP:
        return executable_vwap(((decimal_value(price, "fill_price"), quantity),), quantity, side)

    def mark_open(
        self,
        intent: EventIntent,
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
        self.active_pair = EventActivePair(
            intent=intent,
            opened_at=decimal_value(now_value, "opened_at"),
            quantity_base=quantity,
            entry_buy=confirmed_buy,
            entry_sell=confirmed_sell,
            entry_fees_paid=(
                None
                if entry_fees_paid is None
                else decimal_value(entry_fees_paid, "entry_fees_paid")
            ),
            funding_snapshot=funding_snapshot,
        )

    def mark_closed(self) -> None:
        self.active_pair = None

    def _realized_funding(self) -> Decimal:
        if self.active_pair is None:
            return Decimal(0)
        total = Decimal(0)
        for venue, snapshot in self.active_pair.funding_snapshot.items():
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

    def exit_reason(self, now_value) -> Optional[str]:
        if self.active_pair is None:
            return None
        now = decimal_value(now_value, "now")
        active = self.active_pair
        intent = active.intent
        opened_at = active.opened_at
        quantity = active.quantity_base
        if not self._fresh(now):
            return "stale"
        if now - opened_at >= self.risk.maximum_holding_seconds:
            return "maximum_holding"
        try:
            long_exit = executable_vwap(self.books[intent.long_venue].bids, quantity, "sell")
            short_exit = executable_vwap(self.books[intent.short_venue].asks, quantity, "buy")
        except CrossExchangeValueError:
            return "depth"
        economics = self._economics(long_exit, short_exit)
        mean_entry_notional = (active.entry_buy.notional + active.entry_sell.notional) / 2
        loss_limit = mean_entry_notional * self.risk.maximum_loss_bps / Decimal("10000")
        if economics.realized_net <= -loss_limit:
            return "loss"
        if economics.risk_adjusted_net > 0:
            return "convergence"
        return None

    def _collect_markouts(self, now: Decimal) -> None:
        if set(self.books) != set(VENUE_SYMBOLS):
            return
        books = tuple(self.books.values())
        if (
            len({book.clock_domain_id for book in books}) != 1
            or any(now < book.receive_time for book in books)
            or any(now - book.receive_time > self.risk.maximum_quote_age_seconds for book in books)
            or abs(books[0].receive_time - books[1].receive_time)
            > self.risk.maximum_venue_skew_seconds
        ):
            return
        remaining = []
        minimum_book_time = min(book.receive_time for book in books)
        for sample in self.pending_markouts:
            if sample["due"] > now or minimum_book_time < sample["due"]:
                if now - sample["due"] > self.risk.markout_tolerance_seconds:
                    self.reject("markout_missed_tolerance")
                    self._markout_observation_series(sample["horizon"], sample["route_key"]).append(
                        {
                            "status": "missed",
                            "direction": list(sample["direction"]),
                            "first_venue": sample["first_venue"],
                            "actual_elapsed_ms": str((now - sample["created_at"]) * Decimal(1000)),
                        }
                    )
                    continue
                remaining.append(sample)
                continue
            delay = now - sample["due"]
            if delay > self.risk.markout_tolerance_seconds:
                self.reject("markout_missed_tolerance")
                self._markout_observation_series(sample["horizon"], sample["route_key"]).append(
                    {
                        "status": "missed",
                        "direction": list(sample["direction"]),
                        "first_venue": sample["first_venue"],
                        "actual_elapsed_ms": str((now - sample["created_at"]) * Decimal(1000)),
                    }
                )
                continue
            buy_venue, sell_venue = sample["direction"]
            try:
                buy = executable_vwap(self.books[buy_venue].asks, sample["quantity"], "buy")
                sell = executable_vwap(self.books[sell_venue].bids, sample["quantity"], "sell")
            except CrossExchangeValueError:
                self.reject("markout_depth")
                self._markout_observation_series(sample["horizon"], sample["route_key"]).append(
                    {
                        "status": "missed",
                        "reason": "depth",
                        "direction": list(sample["direction"]),
                        "first_venue": sample["first_venue"],
                        "actual_elapsed_ms": str((now - sample["created_at"]) * Decimal(1000)),
                    }
                )
                continue
            current = sell.notional - buy.notional
            value = sample["baseline"] - current
            self._markout_series(sample["horizon"], sample["route_key"]).append(str(value))
            self._markout_observation_series(sample["horizon"], sample["route_key"]).append(
                {
                    "status": "observed",
                    "adverse_loss_quote": str(value),
                    "direction": list(sample["direction"]),
                    "first_venue": sample["first_venue"],
                    "actual_elapsed_ms": str((now - sample["created_at"]) * Decimal(1000)),
                    "tolerance_ms": str(self.risk.markout_tolerance_seconds * Decimal(1000)),
                }
            )
        self.pending_markouts = remaining

    def mark_unknown(self) -> None:
        self.halted_unknown = True
        self.reject("unknown_execution")

    def snapshot(self):
        """Return the engine's domain evidence outside a Cerebro run.

        Formula replay has no strategy or observer lifecycle, so its domain
        evidence remains available as a snapshot rather than pretending that
        a framework-level observer was involved.
        """
        serialized_markouts = {
            horizon: {route: list(values) for route, values in routes.items()}
            for horizon, routes in self.markouts.items()
        }
        serialized_observations = {
            horizon: {route: list(values) for route, values in routes.items()}
            for horizon, routes in self.markout_observations.items()
        }
        return {
            "strategy_id": "012_2_event_driven_cross_exchange",
            "model": "independent_taker_taker_event_driven_arbitrage",
            "risk": {key: str(value) for key, value in asdict(self.risk).items()},
            "intents": [intent.as_dict() for intent in self.intents],
            "cost_breakdowns": [cost.as_dict() for cost in self.cost_history],
            "reject_reasons": dict(self.reject_reasons),
            "admission": {
                "status": "BOUND_MODELS_AVAILABLE" if self.admission_models else "FAIL_CLOSED",
                "configured_path_p99_is_evidence": False,
                "models": [
                    model.as_dict()
                    for _, model in sorted(self.admission_models.items(), key=lambda item: item[0])
                ],
            },
            "markouts_quote": serialized_markouts,
            "markout_observations": serialized_observations,
            "markout_gate": {
                "minimum_samples": str(self.risk.minimum_markout_samples),
                "tail_probability": str(self.risk.markout_tail_probability),
                "tail_metric": "upper_cvar",
                "current_500ms_samples": {
                    route: len(values) for route, values in self.markouts["500"].items()
                },
                "adverse_reserve_quote": str(self.current_markout_reserve),
            },
            "unknown_execution": self.halted_unknown,
            "active_pair": self.active_pair is not None,
            "last_exit_economics": self.last_exit_economics,
        }

    def report(self):
        """Return :meth:`snapshot` under the legacy formula-engine API.

        ``CrossExchangeArbitrageStrategy.report`` was intentionally removed
        in favor of the framework-level ``TradeLogger`` report.  This engine
        remains public and is also used by formula replay without a Cerebro
        lifecycle, so retain its historical method as a compatibility alias.
        """
        return self.snapshot()


def _book_from_event(event, venue: str, rule: InstrumentRule, funding) -> EventBook:
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
    return EventBook(
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
        recovery_snapshot=recovery,
        funding_rate=decimal_value(rate),
        next_funding_time=(None if next_time is None else decimal_value(next_time)),
    )


class CrossExchangeArbitrageStrategy(bt.Strategy):
    """Backtrader adapter for the independent event decision engine."""

    params = (
        ("rules", None),
        ("risk", None),
        ("venue_stats", None),
        ("admission_models", None),
        ("funding", None),
        ("funding_snapshot_provider", None),
        ("funding_exchange_routes", None),
        ("funding_max_age_seconds", Decimal("30")),
        ("account_risk_ledger", None),
        ("execution_enabled", True),
        ("shadow", False),
    )

    def __init__(self):
        self.rules = dict(self.p.rules or {})
        self.risk = (
            self.p.risk
            if isinstance(self.p.risk, EventDrivenRisk)
            else EventDrivenRisk(**(self.p.risk or {}))
        )
        self.engine = EventArbitrageEngine(
            self.rules,
            self.risk,
            self.p.venue_stats,
            self.p.admission_models,
        )
        self.feeds = {
            SYMBOL_VENUES[data._name]: data for data in self.datas if data._name in SYMBOL_VENUES
        }
        if set(self.feeds) != set(VENUE_SYMBOLS):
            raise ValueError("both OKX and Binance feeds are required")
        self.pending_order = None
        self.pair_state = None
        self.leg_deadline = None
        self.cancel_deadline = None
        self.pair_deadline = None
        self.cancel_requested = False
        self.awaiting_reconciliation = False
        self.remote_flat_proven = False
        self.known_order_refs = set()
        self.processed_order_refs = set()
        self.order_records = {}
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
        if active is not None:
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
        remaining_holding = max(
            Decimal(0),
            self.risk.maximum_holding_seconds - (self._now() - active.opened_at),
        )
        safe_exit_window = remaining_holding + self.risk.flatten_deadline_seconds
        now_epoch = self._wall_now()
        if any(
            state.next_funding_epoch <= now_epoch + safe_exit_window
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
                        if active is not None and event["phase"] in {"first", "hedge"}:
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
        was_unknown = self.engine.halted_unknown
        if not was_unknown:
            previous_fence = self._reconcile_min_as_of_ns
            self._advance_reconcile_fence()
            self._reconcile_min_as_of_ns = max(
                self._reconcile_min_as_of_ns,
                previous_fence + 1,
            )
        self.engine.reject(reason)
        self.engine.mark_unknown()
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
                and not self.engine.halted_unknown
            ):
                self._mark_unknown("flatten_deadline")
                return
            if (
                self.awaiting_reconciliation
                and self.pair_deadline is not None
                and now >= self.pair_deadline
                and not self.engine.halted_unknown
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
                and not self.engine.halted_unknown
            ):
                self.pair_state.pop("flatten_waiting_for_book", None)
                self._submit_flatten_head()
            if self.awaiting_reconciliation:
                self._poll_remote_reconcile()
            return
        if self.awaiting_reconciliation:
            self._poll_remote_reconcile()
            return
        if self.engine.halted_unknown:
            return
        opening_inflight = pair_phase in {"first", "hedge"}
        funding_ready = self._refresh_funding_gate(opening=self.engine.active_pair is None)
        if not funding_ready:
            self._handle_runtime_funding_failure(opening_inflight)
            return
        book = _book_from_event(event, venue, self.rules[venue], self._funding_payload())
        if not self.engine.update_book(book):
            self._handle_invalid_book(venue)
            return
        now = self._now()
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
            reason = self._funding_exit_reason() or self.engine.exit_reason(book.receive_time)
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
        intent = self.engine.evaluate(book.receive_time)
        if intent is None or not self.p.execution_enabled or self.p.shadow:
            return
        if not self._account_loss_allows_entry():
            return
        if not self._refresh_funding_gate(opening=True):
            return
        self._ensure_runtime_state()
        self._cycle_id += 1
        self.remote_flat_proven = False
        first_side = "buy" if intent.first_venue == intent.long_venue else "sell"
        first_price = (
            intent.entry_buy.marginal_price
            if first_side == "buy"
            else intent.entry_sell.marginal_price
        )
        self.pair_deadline = now + self.risk.pair_deadline_seconds
        self.pair_state = {
            "intent": intent,
            "phase": "first",
            "fills": {},
            "exposures": {},
            "funding_snapshot": {
                "captured_at_epoch": self._wall_now(),
                "venues": dict(self._funding_states),
            },
        }
        self._submit(
            intent.first_venue,
            first_side,
            intent.quantity_base,
            first_price,
            "first",
            position_side="long" if first_side == "buy" else "short",
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
        if self.engine.halted_unknown:
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
        opening_inflight = pair_phase in {"first", "hedge"}
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
        if not reduce_only and phase in {"first", "hedge"}:
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
        if phase in {"first", "hedge"} and not self.engine._fresh(now):
            reason = "hedge_market_data_stale" if phase == "hedge" else "entry_market_data_stale"
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
            if phase == "first"
            else (
                self.risk.hedge_deadline_seconds
                if phase == "hedge"
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
        opening_phase = phase in {"first", "hedge"} and not reduce_only
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
        self.pair_deadline = self._now() + self.engine.risk.flatten_deadline_seconds
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

    def _record_order(self, order, phase, venue, quantity):
        fill_price = decimal_value(getattr(order.executed, "price", 0), "fill_price")
        self.order_records[order.ref] = {
            "venue": venue,
            "phase": phase,
            "status": order.getstatusname(),
            "filled_base": str(quantity),
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
        self.engine.halted_unknown = False
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
        if self.engine.halted_unknown:
            if not order.alive():
                quantity = self._fill_cumulative.get(order.ref, {}).get("quantity", Decimal(0))
                self._record_order(order, phase, venue, quantity)
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
        quantity = self.rules[venue].native_to_base(abs(decimal_value(order.executed.size)))
        self._record_order(order, phase, venue, quantity)
        self.processed_order_refs.add(order.ref)
        self.pending_order = None
        self.leg_deadline = None
        self.cancel_deadline = None
        self.cancel_requested = False
        if phase == "flatten":
            if quantity > 0:
                fill_price = decimal_value(getattr(order.executed, "price", 0), "fill_price")
                if fill_price <= 0:
                    self._mark_unknown("missing_confirmed_fill_price")
                    return
                self.pair_state["flatten_fills"].append(
                    {
                        "order_ref": order.ref,
                        "venue": venue,
                        "side": "buy" if order.isbuy() else "sell",
                        "quantity": quantity,
                        "price": fill_price,
                        "commission": decimal_value(order.executed.comm),
                    }
                )
            queue = self.pair_state.get("flatten_queue") or ()
            if not queue or queue[0].get("venue") != venue:
                self._mark_unknown("flatten_order_queue_mismatch")
                return
            head = queue[0]
            head["remaining"] = max(Decimal(0), head["remaining"] - quantity)
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
        if quantity <= 0:
            if phase == "first":
                self.engine.reject("first_leg_unfilled")
                self.pair_state = None
                self.pair_deadline = None
                self.leg_deadline = None
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
            "quantity": quantity,
            "price": fill_price,
            "commission": decimal_value(order.executed.comm),
            "venue": venue,
            "side": "buy" if order.isbuy() else "sell",
        }
        self.pair_state["fills"][phase] = fill
        self.pair_state["exposures"][venue] = (position_side, quantity)
        if self.unhedged_started is None:
            self.unhedged_started = self._now()
        if self.pair_state.get("risk_exit_reason"):
            self._begin_flatten(self.pair_state["exposures"], self.pair_state["risk_exit_reason"])
            return
        if phase == "first":
            hedge_lattice = quantity_lattice(quantity, self.rules.values())
            if not hedge_lattice.tradable:
                self.engine.reject("partial_below_common_lattice")
                self._begin_flatten(self.pair_state["exposures"], "partial_below_common_lattice")
                return
            second_venue = intent.short_venue if venue == intent.long_venue else intent.long_venue
            second_side = "sell" if second_venue == intent.short_venue else "buy"
            second_price = (
                intent.entry_sell.marginal_price
                if second_side == "sell"
                else intent.entry_buy.marginal_price
            )
            self.pair_state["phase"] = "hedge"
            self._submit(
                second_venue,
                second_side,
                hedge_lattice.quantity_base,
                second_price,
                "hedge",
                position_side="short" if second_side == "sell" else "long",
            )
            return
        first_fill = self.pair_state["fills"]["first"]
        if quantity != first_fill["quantity"]:
            self.engine.reject("partial_hedge")
            self._begin_flatten(self.pair_state["exposures"], "partial_hedge")
            return
        hedge_fill = self.pair_state["fills"]["hedge"]
        if not self._refresh_funding_gate(opening=True):
            self._begin_flatten(self.pair_state["exposures"], "funding_stale_after_hedge")
            return
        long_fill = first_fill if first_fill["side"] == "buy" else hedge_fill
        short_fill = first_fill if first_fill["side"] == "sell" else hedge_fill
        entry_buy = self.engine._confirmed_fill("buy", quantity, long_fill["price"])
        entry_sell = self.engine._confirmed_fill("sell", quantity, short_fill["price"])
        self.engine.mark_open(
            intent,
            self._now(),
            quantity,
            entry_buy=entry_buy,
            entry_sell=entry_sell,
            entry_fees_paid=long_fill["commission"] + short_fill["commission"],
        )
        self.pair_state = None
        self.pair_deadline = None
        self.leg_deadline = None
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

    def trade_logger_context(self):
        """Return cross-venue evidence for ``TradeLogger.extensions``.

        ``TradeLogger`` owns generic orders, trades, portfolio values and
        real-time snapshots.  This strategy supplies only the model and
        execution facts which are specific to this two-venue candidate.
        """
        self._ensure_runtime_state()
        report = dict(self.engine.snapshot())
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
        report.update(
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
            unhedged_duration_max=str(max(self.unhedged_durations, default=Decimal(0))),
            reconciliation_required=self.engine.halted_unknown or self.awaiting_reconciliation,
            remote_flat_proven=self.remote_flat_proven,
            broker_value=self._cached_broker_value_for_report(),
        )
        return report

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
    "CrossExchangeArbitrageStrategy",
    "EventArbitrageEngine",
    "EventActivePair",
    "EventBook",
    "EventDrivenRisk",
    "EventIntent",
    "EventPathQualification",
    "EVENT_PATH_EVIDENCE_ROLE",
    "EVENT_PATH_LATENCY_SCOPE",
    "MARKOUT_HORIZONS_MS",
    "VENUE_SYMBOLS",
    "VenueExecutionStats",
    "event_depth_bucket",
    "event_fee_bucket",
    "event_path_model_sha256",
]
