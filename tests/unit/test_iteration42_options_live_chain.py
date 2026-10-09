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
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_ctp")

import backtrader as bt  # noqa: E402
from backtrader.feeds import BarEvidence, BtApiFeed, ClockMapping  # noqa: E402
from backtrader.stores import btapistore as _btapistore  # noqa: E402

_WRAPPER_CLS = _btapistore._create_ctp_wrapper_class()

DOMAIN = "iter42-chain-domain"
RULES_HASH = "iter42-chain-rules"
GENERATION = 5
CANDIDATE_ID = "ctp-options-lowfreq-live-r1"
_TRADING_DAY = "20261012"


def _payload(update_time: str, millisec: int, volume: float, price: float) -> SimpleNamespace:
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
        TradingDay=_TRADING_DAY,
        ActionDay=_TRADING_DAY,
        UpdateTime=update_time,
        UpdateMillisec=millisec,
    )


class _LiveEvidenceProvider:
    """Same shape as the 014_1 live run.py provider (compact form)."""

    def __init__(self, mapping: ClockMapping) -> None:
        self.mapping = mapping
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
        )


def _mapping() -> ClockMapping:
    wall0 = dt.datetime(2026, 10, 12, 1, 0, tzinfo=dt.timezone.utc)
    return ClockMapping(
        mapping_id="iter42-chain-mapping",
        wall_utc_at_anchor=wall0,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id=DOMAIN,
        connection_generation=GENERATION,
        source="iter42-chain-test",
        error_bound_ns=0,
        valid_until_mono_ns=1_000_000_000 + 10**15,
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
            "session_segment": f"czce-live:{_TRADING_DAY}",
            "generation": GENERATION,
            "source": "iter42-chain-test",
        },
    )
    # Bucket A (09:00-09:15) plus one tick in bucket B to close A.
    wrapper._handle_md_tick(_payload("09:00:00", 0, 5.0, 1000.0))
    wrapper._handle_md_tick(_payload("09:10:00", 0, 8.0, 1002.0))
    wrapper._handle_md_tick(_payload("09:15:01", 0, 12.0, 1003.0))

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
    assert evidence.session_segment == f"czce-live:{_TRADING_DAY}"
    assert evidence.candidate_id == CANDIDATE_ID
    assert evidence.complete is True
    assert evidence.clock_mapping == mapping
    assert evidence.trading_day == _TRADING_DAY
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
    assert evidence.bucket_start == dt.datetime(2026, 10, 12, 1, 0, tzinfo=dt.timezone.utc)
    assert evidence.bucket_end == dt.datetime(2026, 10, 12, 1, 15, tzinfo=dt.timezone.utc)


def test_unstamped_ticks_cannot_produce_live_evidence():
    """Without provenance the same pipeline fails the live evidence contract."""
    wrapper = _WRAPPER_CLS(
        broker_id="fake",
        investor_id="fake",
        password="fake",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
    )
    wrapper._handle_md_tick(_payload("09:00:00", 0, 5.0, 1000.0))
    wrapper._handle_md_tick(_payload("09:10:00", 0, 8.0, 1002.0))
    wrapper._handle_md_tick(_payload("09:15:01", 0, 12.0, 1003.0))

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
