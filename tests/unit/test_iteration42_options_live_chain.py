"""Composed offline check: stamped CTP ticks -> real feed seal -> provider.

This closes the handoff between the two iteration-42 pieces for the strict
options live tier:

* the CTP wrapper's opt-in ``live_tick_provenance`` stamping (btapistore),
* the real ``BtApiFeed`` bucket builder + closed-bar seal,
* the example-owned ``BarEvidence`` provider whose mapping/candidate/rules
  identity must match the stamped tick identity.

The feed is driven directly (no store session, no network); the provider
builds the same ``BarEvidence`` shape the live run.py uses, and the feed's own
seal-time validation must accept it.
"""

from __future__ import annotations

import datetime as dt
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_ctp")

import backtrader as bt  # noqa: E402
from backtrader.feeds import (  # noqa: E402
    BarEvidence,
    BtApiFeed,
    ClockMapping,
    validate_quote_against_bar,
)
from backtrader.stores import btapistore as _btapistore  # noqa: E402

_WRAPPER_CLS = _btapistore._create_ctp_wrapper_class()

DOMAIN = "iter42-chain-domain"
RULES_HASH = "iter42-chain-rules"
GENERATION = 5
CANDIDATE_ID = "ctp-options-lowfreq-live-r1"
_BEIJING = dt.timezone(dt.timedelta(hours=8))

# Real-clock time plan: bucket A is the previous 15-minute grid bucket and
# the closer tick is "now", so the live watermark (last event time + ingest
# elapsed) seals bucket A at the real present.  Wall ordering
# (event < receive < seal) then holds against the real clock.
_NOW = dt.datetime.now(dt.timezone.utc)
_FLOOR = _NOW.replace(second=0, microsecond=0)
_FLOOR = _FLOOR.replace(minute=(_FLOOR.minute // 15) * 15) - dt.timedelta(minutes=15)
_TICK_A0 = _FLOOR + dt.timedelta(seconds=1)
_TICK_A1 = _FLOOR + dt.timedelta(minutes=5)
_TICK_A2 = _FLOOR + dt.timedelta(minutes=14)
_TICK_A3 = _FLOOR + dt.timedelta(minutes=14, seconds=30)
_CLOSER = _NOW - dt.timedelta(seconds=3)
_MONO_BASE = time.monotonic_ns()


class _FrozenClock:
    """Minimal stand-in for the store module's ``time`` during one stamp."""

    def __init__(self, wall: float, mono_ns: int) -> None:
        self._wall = wall
        self._mono_ns = mono_ns

    def time(self) -> float:
        return self._wall

    def monotonic_ns(self) -> int:
        return self._mono_ns


def _stamp_tick(wrapper, instant: dt.datetime, volume: float, price: float) -> None:
    """Stamp one payload as if the CTP callback arrived at ``instant``.

    Production ticks are stamped at their true arrival instant, strictly
    before the bar's causal seal; the frozen clock keeps that ordering real
    while the wrapper otherwise uses process time.
    """
    offset_ns = int((_NOW - instant).total_seconds() * 1_000_000_000)
    frozen = _FrozenClock(instant.timestamp(), _MONO_BASE - offset_ns)
    original = _btapistore.time
    _btapistore.time = frozen
    try:
        wrapper._handle_md_tick(_payload(instant, volume, price))
    finally:
        _btapistore.time = original


def _payload(instant: dt.datetime, volume: float, price: float) -> SimpleNamespace:
    beijing = instant.astimezone(_BEIJING)
    return SimpleNamespace(
        InstrumentID="SA701",
        ExchangeID="CZCE",
        LastPrice=price,
        Volume=volume,
        BidPrice1=price - 1.0,
        AskPrice1=price + 1.0,
        BidVolume1=3.0,
        AskVolume1=4.0,
        OpenInterest=123.0,
        Turnover=456.0,
        TradingDay=beijing.strftime("%Y%m%d"),
        ActionDay=beijing.strftime("%Y%m%d"),
        UpdateTime=beijing.strftime("%H:%M:%S"),
        UpdateMillisec=0,
    )


class _LiveEvidenceProvider:
    """Same shape as the 014_1 live run.py provider (compact form)."""

    def __init__(self, mapping: ClockMapping) -> None:
        self.mapping = mapping
        self.candidate_id = CANDIDATE_ID
        self.calls = []

    def __call__(self, bar):
        self.calls.append(str(bar.symbol))
        seal_received_at = bar.available_at
        return BarEvidence(
            symbol=bar.symbol,
            exchange=bar.exchange,
            bucket_start=bar.bucket_start,
            bucket_end=bar.bucket_end,
            available_at=bar.available_at,
            seal_received_mono=self.mapping.map_wall_to_mono_ns(seal_received_at) / 1_000_000_000.0,
            seal_received_at=seal_received_at,
            trading_day=bar.trading_day,
            generation=bar.connection_generation,
            session_segment=bar.session_segment,
            rules_hash=bar.rules_hash,
            quality=bar.quality,
            volume_complete=bar.volume_complete,
            first_ingest_seq=bar.first_ingest_seq,
            last_ingest_seq=bar.last_ingest_seq,
            quote_cutoff_seq=bar.quote_cutoff_seq,
            bar_id=bar.bar_id,
            bar_sequence=bar.bar_sequence,
            closure_reason=bar.closure_reason,
            watermark=bar.watermark,
            max_event_time=bar.max_event_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            openinterest=bar.openinterest,
            clock_domain=self.mapping.clock_domain_id,
            clock_mode="live",
            candidate_id=CANDIDATE_ID,
            timeframe_seconds=900.0,
            trade_count=bar.trade_count,
            complete=bar.complete,
            clock_mapping=self.mapping,
            quote_events=tuple(
                {**dict(item), "candidate_id": self.candidate_id}
                for item in getattr(bar, "quote_events", ()) or ()
            ),
        )


def _mapping() -> ClockMapping:
    mono0 = time.monotonic_ns()
    return ClockMapping(
        mapping_id="iter42-chain-mapping",
        wall_utc_at_anchor=dt.datetime.now(dt.timezone.utc),
        mono_ns_at_anchor=mono0,
        clock_domain_id=DOMAIN,
        connection_generation=GENERATION,
        source="iter42-chain-test",
        error_bound_ns=250_000_000,
        valid_until_mono_ns=mono0 + 4 * 3600 * 10**9,
        rules_hash=RULES_HASH,
        synthetic=False,
    )


def test_stamped_ticks_flow_through_the_real_feed_into_sealed_evidence():
    wrapper = _WRAPPER_CLS(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
        live_tick_provenance={
            "clock_domain_id": DOMAIN,
            "rules_hash": RULES_HASH,
            "session_segment": f"czce-live:{_TICK_A0.astimezone(_BEIJING).strftime('%Y%m%d')}",
            "generation": GENERATION,
            "source": "iter42-chain-test",
        },
    )
    # Bucket A (09:00-09:15) plus one tick in bucket B to close A.
    _stamp_tick(wrapper, _TICK_A0, 5.0, 1000.0)
    _stamp_tick(wrapper, _TICK_A1, 8.0, 1002.0)
    _stamp_tick(wrapper, _CLOSER, 12.0, 1003.0)

    mapping = _mapping()
    provider = _LiveEvidenceProvider(mapping)
    feed = BtApiFeed(
        dataname="SA701",
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        closed_bar_evidence_provider=provider,
        bar_watermark_ms=500.0,
    )
    feed._timeframe = bt.TimeFrame.Minutes
    feed._compression = 15

    captured = []
    original_enqueue = feed._enqueue_bar_event

    def _capture(bar_event, bar_datetime, *, deliver_lines=True):
        captured.append(bar_event)
        original_enqueue(bar_event, bar_datetime, deliver_lines=deliver_lines)

    feed._enqueue_bar_event = _capture

    while True:
        tick = wrapper.poll_tick("SA701")
        if tick is None:
            break
        # Mirror the poll path: quality/flags/watermark first, then the bar
        # builder consumes the prepared tick.
        feed._prepare_tick(tick)
        feed._ingest_tick(tick)
    feed._flush_ready_bars(reason="test")

    assert provider.calls == ["SA701"], "provider must run once for the sealed bucket"
    assert len(captured) == 1
    sealed = captured[0]
    evidence = getattr(sealed, "closed_bar_evidence", None)
    assert isinstance(evidence, BarEvidence)
    assert evidence.symbol == "SA701"
    assert evidence.exchange == "CZCE"
    assert evidence.clock_mode == "live"
    assert evidence.clock_domain == DOMAIN
    assert evidence.generation == GENERATION
    assert evidence.rules_hash == RULES_HASH
    assert evidence.session_segment == f"czce-live:{_TICK_A0.astimezone(_BEIJING).strftime('%Y%m%d')}"
    assert evidence.candidate_id == CANDIDATE_ID
    assert evidence.complete is True
    assert evidence.clock_mapping == mapping
    assert evidence.trading_day == _TICK_A0.astimezone(_BEIJING).strftime("%Y%m%d")
    # The first tick of a subscription is the cumulative-volume baseline
    # (delta zero) and never enters a bar; bucket A is built from the 09:10
    # tick only, and bucket B's 09:15 tick must not leak in.
    assert evidence.open == 1002.0
    assert evidence.high == 1002.0
    assert evidence.low == 1002.0
    assert evidence.close == 1002.0
    assert evidence.volume == 3.0
    assert evidence.first_ingest_seq == 2
    assert evidence.last_ingest_seq == 2
    assert evidence.bucket_start == _FLOOR
    assert evidence.bucket_end == _FLOOR + dt.timedelta(minutes=15)


def test_unstamped_ticks_cannot_produce_live_evidence():
    """Without provenance the same pipeline fails the live evidence contract."""
    wrapper = _WRAPPER_CLS(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
    )
    _stamp_tick(wrapper, _TICK_A0, 5.0, 1000.0)
    _stamp_tick(wrapper, _TICK_A1, 8.0, 1002.0)
    _stamp_tick(wrapper, _CLOSER, 12.0, 1003.0)

    provider = _LiveEvidenceProvider(_mapping())
    feed = BtApiFeed(
        dataname="SA701",
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        closed_bar_evidence_provider=provider,
        bar_watermark_ms=500.0,
    )
    feed._timeframe = bt.TimeFrame.Minutes
    feed._compression = 15
    while True:
        tick = wrapper.poll_tick("SA701")
        if tick is None:
            break
        feed._prepare_tick(tick)
        feed._ingest_tick(tick)
    with pytest.raises(ValueError):
        # The seal-time validation rejects evidence whose identity cannot be
        # produced from the unstamped tick fields (empty rules hash, session
        # segment and clock domain fail the BarEvidence provenance contract).
        feed._flush_ready_bars(reason="test")


def _drive(wrapper, feed):
    while True:
        tick = wrapper.poll_tick("SA701")
        if tick is None:
            break
        feed._prepare_tick(tick)
        feed._ingest_tick(tick)
    feed._flush_ready_bars(reason="test")


def test_bounded_quote_capture_produces_bar_bound_live_quotes():
    wrapper = _WRAPPER_CLS(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
        live_tick_provenance={
            "clock_domain_id": DOMAIN,
            "rules_hash": RULES_HASH,
            "session_segment": f"czce-live:{_TICK_A0.astimezone(_BEIJING).strftime('%Y%m%d')}",
            "generation": GENERATION,
            "source": "iter42-chain-test",
        },
    )
    _stamp_tick(wrapper, _TICK_A0, 5.0, 1000.0)
    _stamp_tick(wrapper, _TICK_A1, 6.0, 1001.0)
    _stamp_tick(wrapper, _TICK_A2, 7.0, 1002.0)
    _stamp_tick(wrapper, _TICK_A3, 8.0, 1002.5)
    _stamp_tick(wrapper, _CLOSER, 12.0, 1003.0)

    mapping = _mapping()
    provider = _LiveEvidenceProvider(mapping)
    feed = BtApiFeed(
        dataname="SA701",
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        closed_bar_evidence_provider=provider,
        bar_watermark_ms=500.0,
        closed_bar_quote_capture=True,
        closed_bar_quote_limit=16,
    )
    feed._timeframe = bt.TimeFrame.Minutes
    feed._compression = 15
    captured = []
    original_enqueue = feed._enqueue_bar_event
    feed._enqueue_bar_event = lambda bar_event, bar_datetime, deliver_lines=True: (
        captured.append(bar_event),
        original_enqueue(bar_event, bar_datetime, deliver_lines=deliver_lines),
    )[-1]
    _drive(wrapper, feed)

    assert len(captured) == 1
    evidence = captured[0].closed_bar_evidence
    quotes = list(evidence.quote_events)
    # The cumulative-volume baseline tick never enters a bar; the three
    # remaining bucket-A ticks are captured in order.
    assert [item["ingest_seq"] for item in quotes] == [2, 3, 4]
    assert all(item["clock_domain"] == DOMAIN for item in quotes)
    assert all(item["generation"] == GENERATION for item in quotes)
    assert all(item["clock_mode"] == "live" for item in quotes)
    assert all(item["volume_complete"] is True for item in quotes)
    for quote in quotes:
        result = validate_quote_against_bar(quote, bar=evidence, max_skew_ms=500.0)
        assert result.accepted is True, (quote["ingest_seq"], result.reason)
    # Quotes stay strictly inside the sealed bucket window.
    assert all(item["event_time"] < evidence.bucket_end for item in quotes)


def test_quote_capture_overflow_drops_oldest_and_invalidates_completeness():
    wrapper = _WRAPPER_CLS(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
        live_tick_provenance={
            "clock_domain_id": DOMAIN,
            "rules_hash": RULES_HASH,
            "session_segment": f"czce-live:{_TICK_A0.astimezone(_BEIJING).strftime('%Y%m%d')}",
            "generation": GENERATION,
            "source": "iter42-chain-test",
        },
    )
    _stamp_tick(wrapper, _TICK_A0, 5.0, 1000.0)
    _stamp_tick(wrapper, _TICK_A1, 6.0, 1001.0)
    _stamp_tick(wrapper, _TICK_A2, 7.0, 1002.0)
    _stamp_tick(wrapper, _TICK_A3, 8.0, 1002.5)
    _stamp_tick(wrapper, _CLOSER, 12.0, 1003.0)

    provider = _LiveEvidenceProvider(_mapping())
    feed = BtApiFeed(
        dataname="SA701",
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        closed_bar_evidence_provider=provider,
        bar_watermark_ms=500.0,
        closed_bar_quote_capture=True,
        closed_bar_quote_limit=1,
    )
    feed._timeframe = bt.TimeFrame.Minutes
    feed._compression = 15
    captured = []
    original_enqueue = feed._enqueue_bar_event
    feed._enqueue_bar_event = lambda bar_event, bar_datetime, deliver_lines=True: (
        captured.append(bar_event),
        original_enqueue(bar_event, bar_datetime, deliver_lines=deliver_lines),
    )[-1]
    _drive(wrapper, feed)

    evidence = captured[0].closed_bar_evidence
    assert [item["ingest_seq"] for item in evidence.quote_events] == [4]
    # The overflow flag keeps the sealed bar from claiming completeness.
    assert evidence.complete is False
