"""Explicit local producer for the Iteration 24 FQ2 replay fixture.

The producer is intentionally separate from the strategy.  It records the
synthetic clock mapping, quote identity, receive evidence and bar seal before
the strategy sees a ``MinuteDecisionInput``.  The strategy cannot manufacture
missing provenance or turn a close price into a quote feature.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional

from backtrader.feeds import BarEvidence, ClockMapping, CtpQuoteEvidence

UTC = timezone.utc
REPLAY_BASE = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
REPLAY_CLOCK_DOMAIN = "iter24-replay-clock"
REPLAY_SESSION = "replay-minute"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _epoch(value: datetime) -> float:
    return _aware(value).timestamp()


class ReplayQuoteProducer:
    """Create complete, deterministic quote and bar evidence for one scope."""

    def __init__(
        self,
        *,
        candidate_id: str,
        exchange: str,
        rules_hash: str,
        contracts: Mapping[str, str],
        scenario: str,
        strike: Decimal,
        multiplier: Decimal,
        discount_factor: Decimal,
        base: datetime = REPLAY_BASE,
    ) -> None:
        required = ("future", "call", "put")
        if tuple(contracts) != required:
            raise ValueError("contracts must be ordered future, call, put")
        if scenario not in {"no_edge", "edge"}:
            raise ValueError("unsupported replay scenario")
        if not candidate_id or not exchange or not rules_hash:
            raise ValueError("candidate, exchange and rules hash are required")
        self.candidate_id = candidate_id
        self.exchange = exchange
        self.rules_hash = rules_hash
        self.contracts = dict(contracts)
        self.scenario = scenario
        self.strike = Decimal(str(strike))
        self.multiplier = Decimal(str(multiplier))
        self.discount_factor = Decimal(str(discount_factor))
        self.base = _aware(base)
        self.generation = 7
        self.trading_day = self.base.strftime("%Y%m%d")
        self.clock_mapping = ClockMapping(
            mapping_id=f"{candidate_id}:synthetic-clock-v1",
            wall_utc_at_anchor=self.base,
            mono_ns_at_anchor=1_000_000_000,
            clock_domain_id=REPLAY_CLOCK_DOMAIN,
            connection_generation=self.generation,
            source="iter24-explicit-replay-anchor",
            error_bound_ns=0,
            valid_until_mono_ns=10**18,
            rules_hash=rules_hash,
            synthetic=True,
        )

    def minute_end(self, minute_index: int) -> datetime:
        if type(minute_index) is not int or minute_index < 0:
            raise ValueError("minute_index must be a non-negative integer")
        return self.base + timedelta(minutes=minute_index + 1)

    def residual_for_minute(self, minute_index: int) -> Decimal:
        if type(minute_index) is not int or minute_index < 0:
            raise ValueError("minute_index must be a non-negative integer")
        if self.scenario == "no_edge":
            return Decimal("0")
        if minute_index < 60:
            return Decimal("10") if minute_index % 2 == 0 else Decimal("-10")
        return Decimal("80")

    def _quote_prices(self, minute_index: int, symbol: str) -> Dict[str, Decimal]:
        residual = self.residual_for_minute(minute_index)
        future_mid = self.strike
        put_mid = Decimal("9.5")
        if self.scenario == "edge" and minute_index >= 60:
            call_bid, call_ask = Decimal("17"), Decimal("18")
            put_bid, put_ask = Decimal("9"), Decimal("10")
            future_bid, future_ask = Decimal("999"), Decimal("1001")
        else:
            call_mid = put_mid + self.discount_factor * (future_mid - self.strike)
            call_mid += residual / self.multiplier
            call_bid, call_ask = call_mid - Decimal("0.5"), call_mid + Decimal("0.5")
            put_bid, put_ask = Decimal("9"), Decimal("10")
            future_bid, future_ask = self.strike - Decimal("0.5"), self.strike + Decimal("0.5")
        prices = {
            self.contracts["future"]: {
                "bid": future_bid,
                "ask": future_ask,
                "bid_qty": Decimal("1"),
                "ask_qty": Decimal("1"),
            },
            self.contracts["call"]: {
                "bid": call_bid,
                "ask": call_ask,
                "bid_qty": Decimal("1"),
                "ask_qty": Decimal("3"),
            },
            self.contracts["put"]: {
                "bid": put_bid,
                "ask": put_ask,
                "bid_qty": Decimal("3"),
                "ask_qty": Decimal("1"),
            },
        }
        if symbol not in prices:
            raise ValueError(f"unknown contract {symbol}")
        return prices[symbol]

    def _quote_sequence(self, minute_index: int, sample: int, leg_index: int) -> int:
        return (minute_index + 1) * 100_000 + 10_000 + sample * 3 + leg_index + 1

    def quote_events_for(self, minute_index: int, symbol: str) -> tuple[dict[str, Any], ...]:
        """Return 60 one-second states ending one second before the bar end."""

        try:
            leg_index = tuple(self.contracts.values()).index(symbol)
        except ValueError as error:
            raise ValueError(f"unknown contract {symbol}") from error
        end = self.minute_end(minute_index)
        result = []
        for sample in range(60):
            event_time = end - timedelta(seconds=60 - sample)
            received_at = event_time
            sequence = self._quote_sequence(minute_index, sample, leg_index)
            price = self._quote_prices(minute_index, symbol)
            typed = CtpQuoteEvidence(
                symbol=symbol,
                exchange=self.exchange,
                asset_type="ctp-option" if symbol != self.contracts["future"] else "ctp-future",
                bid=float(price["bid"]),
                ask=float(price["ask"]),
                bid_size=float(price["bid_qty"]),
                ask_size=float(price["ask_qty"]),
                last=float((price["bid"] + price["ask"]) / Decimal("2")),
                lower_limit=0.01,
                upper_limit=100_000.0,
                source_epoch=_epoch(event_time),
                receive_epoch=_epoch(received_at),
                receive_monotonic_ns=self.clock_mapping.map_wall_to_mono_ns(received_at),
                ingest_seq=sequence,
                connection_generation=self.generation,
                subscription_epoch=1,
                trading_day=self.trading_day,
                action_day=self.trading_day,
                clock_domain_id=REPLAY_CLOCK_DOMAIN,
                rules_hash=self.rules_hash,
                source="iter24-explicit-replay-quote",
                event_time_source="exchange-event-fixture",
                source_clock_error_ms=0.0,
                receive_clock_error_ms=0.0,
            )
            result.append(self._quote_mapping(typed, event_time, received_at))
        return tuple(result)

    def _quote_mapping(
        self, quote: CtpQuoteEvidence, event_time: datetime, received_at: datetime
    ) -> Dict[str, Any]:
        return {
            "symbol": quote.symbol,
            "exchange": quote.exchange,
            "event_time": _aware(event_time),
            "received_at": _aware(received_at),
            "received_monotonic_ns": quote.receive_monotonic_ns,
            "ingest_seq": quote.ingest_seq,
            "generation": quote.connection_generation,
            "trading_day": quote.trading_day,
            "action_day": quote.action_day,
            "session_segment": REPLAY_SESSION,
            "rules_hash": quote.rules_hash,
            "clock_domain": quote.clock_domain_id,
            "clock_mode": "replay",
            "candidate_id": self.candidate_id,
            "quality": "GOOD",
            "volume_complete": True,
            "bid": quote.bid,
            "ask": quote.ask,
            "bid_qty": quote.bid_size,
            "ask_qty": quote.ask_size,
            "last": quote.last,
            "source": quote.source,
            "event_time_source": quote.event_time_source,
            "source_clock_error_ms": quote.source_clock_error_ms,
            "receive_clock_error_ms": quote.receive_clock_error_ms,
        }

    def bar_for(self, minute_index: int, symbol: str, data: Any, leg_index: int) -> BarEvidence:
        if symbol not in self.contracts.values():
            raise ValueError(f"unknown contract {symbol}")
        if type(leg_index) is not int or leg_index not in range(3):
            raise ValueError("leg_index must identify one of the three contracts")
        end = self.minute_end(minute_index)
        start = end - timedelta(minutes=1)
        seal_at = end + timedelta(milliseconds=500 + 100 * leg_index)
        quote_events = self.quote_events_for(minute_index, symbol)
        bar_sequence = minute_index * 3 + leg_index + 1
        trade_sequence = (minute_index + 1) * 100_000 + leg_index + 1
        return BarEvidence(
            symbol=symbol,
            exchange=self.exchange,
            bucket_start=start,
            bucket_end=end,
            available_at=seal_at,
            seal_received_mono=self.clock_mapping.map_wall_to_mono_ns(seal_at) / 1_000_000_000,
            seal_received_at=seal_at,
            trading_day=self.trading_day,
            generation=self.generation,
            session_segment=REPLAY_SESSION,
            rules_hash=self.rules_hash,
            quality="GOOD",
            volume_complete=True,
            first_ingest_seq=trade_sequence,
            last_ingest_seq=trade_sequence,
            quote_cutoff_seq=max(event["ingest_seq"] for event in quote_events),
            bar_id=f"{self.candidate_id}:{symbol}:{end.isoformat()}:{bar_sequence}",
            bar_sequence=bar_sequence,
            closure_reason="replay_recorded_seal",
            watermark=end,
            max_event_time=end - timedelta(microseconds=1),
            open=float(data.open[0]),
            high=float(data.high[0]),
            low=float(data.low[0]),
            close=float(data.close[0]),
            volume=float(data.volume[0]),
            openinterest=float(data.openinterest[0]),
            quote_events=quote_events,
            clock_domain=REPLAY_CLOCK_DOMAIN,
            clock_mode="replay",
            candidate_id=self.candidate_id,
            timeframe_seconds=60.0,
            trade_count=1,
            complete=True,
            clock_mapping=self.clock_mapping,
        )

    def tick_for(
        self,
        minute_index: int,
        *,
        symbol: Optional[str] = None,
        at_cutoff: bool = False,
    ) -> Dict[str, Any]:
        symbol = symbol or self.contracts["future"]
        event = self.quote_events_for(minute_index, symbol)[-1]
        end = self.minute_end(minute_index)
        event = dict(event)
        event["received_at"] = end if at_cutoff else end - timedelta(milliseconds=1)
        event["received_monotonic_ns"] = self.clock_mapping.map_wall_to_mono_ns(
            event["received_at"]
        )
        return event


__all__ = ["REPLAY_BASE", "REPLAY_CLOCK_DOMAIN", "REPLAY_SESSION", "ReplayQuoteProducer"]
