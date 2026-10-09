"""Focused test for the additive live tick provenance stamping (iteration 42).

The CTP direct tick objects normally carry only the native callback fields.
When an iteration-42 options adapter passes ``live_tick_provenance`` (the
run-scoped clock identity it also uses for its ``ClockMapping`` and sealed
bar evidence), each queued TickEvent is stamped so the feed's closed-bar
evidence can carry that same identity.  Default-off behavior is asserted too.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_ctp")

from backtrader.stores import btapistore as _btapistore  # noqa: E402

_WRAPPER_CLS = _btapistore._create_ctp_wrapper_class()


def _payload(volume: float, *, millisec: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        InstrumentID="SA701",
        ExchangeID="CZCE",
        LastPrice=1000.0,
        Volume=volume,
        BidPrice1=999.0,
        AskPrice1=1001.0,
        BidVolume1=3.0,
        AskVolume1=4.0,
        OpenInterest=123.0,
        Turnover=456.0,
        TradingDay="20261012",
        ActionDay="20261012",
        UpdateTime="09:30:00",
        UpdateMillisec=millisec,
    )


def _wrapper(**extra):
    kwargs = {
        "broker_id": "fake",
        "investor_id": "fake",
        "password": "fake",
        "md_front": "tcp://127.0.0.1:1",
        "td_front": "tcp://127.0.0.1:2",
    }
    kwargs.update(extra)
    return _WRAPPER_CLS(**kwargs)


def test_live_tick_provenance_stamps_the_caller_owned_clock_identity():
    provenance = {
        "clock_domain_id": "iter42-test-domain",
        "rules_hash": "iter42-test-rules",
        "session_segment": "day-session",
        "generation": 7,
        "source": "unit-test-live-source",
    }
    wrapper = _wrapper(live_tick_provenance=provenance)
    wrapper._handle_md_tick(_payload(5.0))
    wrapper._handle_md_tick(_payload(9.0, millisec=500))

    events = list(wrapper._tick_queues["SA701"])
    assert len(events) == 2
    first, second = events

    assert first.clock_domain_id == "iter42-test-domain"
    assert first.rules_hash == "iter42-test-rules"
    assert first.session_segment == "day-session"
    assert first.connection_generation == 7
    assert first.stream_generation == 7
    assert first.source == "unit-test-live-source"
    assert first.ingest_seq == 1
    assert first.sequence == 1
    assert first.previous_sequence is None
    assert first.continuity_status == "continuous"
    assert first.stale is False
    assert first.received_monotonic_ns > 0
    assert first.received_monotonic_ns == first.recv_monotonic_ns
    assert first.received_wall_time > 0
    assert first.event_id.startswith("ctp-SA701-1")
    assert first.trading_day == "20261012"
    assert first.exchange_time == first.timestamp
    # Cumulative CTP volume is surfaced as the delta the bar builder reads.
    assert first.delta_volume == first.volume
    assert first.volume_complete is True
    assert first.volume_semantics == "delta"

    assert second.ingest_seq == 2
    assert second.previous_sequence == 1
    assert second.delta_volume == second.volume


def test_stamped_fields_are_exactly_what_the_bar_builder_reads():
    """The feed's own field readers pick up every stamped provenance value."""
    from backtrader.feeds import btapifeed as _btapifeed

    provenance = {
        "clock_domain_id": "iter42-test-domain",
        "rules_hash": "iter42-test-rules",
        "session_segment": "day-session",
        "generation": 9,
        "source": "unit-test-live-source",
    }
    wrapper = _wrapper(live_tick_provenance=provenance)
    wrapper._handle_md_tick(_payload(5.0))
    wrapper._handle_md_tick(_payload(9.0, millisec=500))
    tick = list(wrapper._tick_queues["SA701"])[1]

    causal = _btapifeed._causal_event_kwargs(tick)
    assert causal["received_monotonic_ns"] == tick.received_monotonic_ns
    assert causal["clock_domain_id"] == "iter42-test-domain"
    assert causal["source"] == "unit-test-live-source"
    assert causal["continuity_status"] == "continuous"
    assert _btapifeed._tick_value(tick, "rules_hash", default=None) == "iter42-test-rules"
    assert _btapifeed._tick_value(tick, "session_segment", default=None) == "day-session"
    assert (
        _btapifeed._tick_value(tick, "connection_generation", "stream_generation", default=None)
        == 9
    )
    assert _btapifeed._tick_value(tick, "ingest_seq", "sequence", default=None) == 2
    # The first tick of a subscription is the cumulative-volume baseline
    # (delta zero); later ticks carry the exact delta the bar builder reads.
    assert _btapifeed._tick_value(tick, "delta_volume", "volume", default=None) == 4.0
    assert _btapifeed._tick_value(tick, "volume_complete", default=None) is True


def test_default_off_keeps_native_tick_objects_unstamped():
    wrapper = _wrapper()
    wrapper._handle_md_tick(_payload(5.0))
    event = list(wrapper._tick_queues["SA701"])[0]
    # The TickEvent's own process-scoped clock domain stays untouched, and no
    # caller identity fields are attached.
    assert str(event.clock_domain_id).startswith("process-")
    assert getattr(event, "rules_hash", None) in (None, "")
    assert getattr(event, "session_segment", None) in (None, "")
    assert getattr(event, "ingest_seq", None) in (None, 0)
    assert getattr(event, "sequence", None) in (None, 0)
    assert not str(getattr(event, "event_id", "") or "").startswith("ctp-")
