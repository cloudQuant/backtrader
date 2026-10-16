"""Focused source contracts for service-proxied CTP V2 tick events."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest
from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountOpenOrder,
    AccountObservation,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_protocol import (
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
    MarketInstrumentKey,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION,
    WireEnvelope,
    WireHeader,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
)
from backtrader.dataseries import TimeFrame
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore

from backtrader.stores.service_read_proxy import (
    ServiceCtpTickBinding,
    ServiceFeedBinding,
    ServiceReadProxy,
    ServiceReadProxyError,
)


_OBSERVED = "2026-10-17T02:00:00Z"
_ACCOUNT = AccountKey("ctp", "CZCE", "simnow", "account-0142")
_RESOURCE = AccountResourceKey("option", "ctp")
_INSTRUMENT = MarketInstrumentKey(
    "ctp", "CZCE", "simnow", "option", "SA701C1080", "CZCE.SA701C1080"
)
_KEY = MarketSubscriptionKey(
    "ctp-md-source",
    "ctp-md-entitlement",
    _INSTRUMENT,
    "ctp.quote.v2",
)
_SCOPE = WireScope("ctp-market-domain", strategy_ref="ctp_options_midfreq")
_CLOCK_DOMAIN = "ctp-md-clock-v1"


def _tick(*, generation=7, subscription_epoch=3, ingest_seq=20, **changes):
    value = {
        "schema_version": "ctp.quote.v2",
        "symbol": _INSTRUMENT.native_symbol,
        "instrument_id": _INSTRUMENT.instrument_id,
        "exchange_id": _INSTRUMENT.venue,
        "event_time_utc": "2026-10-17T01:59:59.900000Z",
        "recv_time_utc": _OBSERVED,
        "recv_monotonic_ns": 12_345_678_900,
        "connection_generation": generation,
        "subscription_epoch": subscription_epoch,
        "ingest_seq": ingest_seq,
        "clock_domain_id": _CLOCK_DOMAIN,
        "volume_semantics": "delta",
        "delta_volume": 1.0,
        "cum_volume": 101.0,
        "quality_flags": [],
    }
    value.update(changes)
    return value


def _event(sequence: int, data, *, scope=_SCOPE, stream_epoch="market-epoch-1"):
    return WireEnvelope(
        WireHeader(
            protocol_version=WIRE_PROTOCOL_VERSION,
            kind=WireMessageKind.EVENT,
            message_id=f"event-{sequence}",
            correlation_id=None,
            identity=WireIdentity(WireRole.SERVICE, "ctp-market-service", "ctp-market-service"),
            scope=scope,
            operation=MARKET_EVENT_OPERATION,
            schema_id=MARKET_EVENT_SCHEMA,
            schema_version=MARKET_EVENT_SCHEMA_VERSION,
            sent_at_utc=_OBSERVED,
            stream_id=_KEY.stream_id,
            stream_epoch=stream_epoch,
            sequence=sequence,
        ),
        {"key": _KEY.to_dict(), "data": data},
    )


class _AccountClient:
    expected_account = _ACCOUNT
    required_coverage = (_RESOURCE,)
    require_open_orders = True

    def __init__(self, observation=None):
        self.observation = observation

    def refresh(self):
        if self.observation is not None:
            return SimpleNamespace(observation=self.observation)
        observation = AccountObservation(
            account_key=_ACCOUNT,
            observation_id="account-observation-1",
            coverage=(_RESOURCE,),
            balances=(AccountBalance(_RESOURCE, "CNY", "100", "90", "10", _OBSERVED),),
            positions=(),
            valuation=AccountValuation("CNY", "90", "100", _OBSERVED),
            started_at_utc=_OBSERVED,
            completed_at_utc=_OBSERVED,
            consistency="provider_atomic",
            balances_complete=True,
            positions_complete=True,
            open_orders=(),
            open_orders_complete=True,
        )
        return SimpleNamespace(observation=observation)

    snapshot = refresh

    def close(self):
        return None


class _MarketClient:
    key = _KEY
    stream_scope = _SCOPE
    healthy = True
    recovery_required = False

    def __init__(self, events=()):
        self.events = deque(events)
        self.closed = False

    def start(self):
        return SimpleNamespace(
            snapshot=None,
            snapshot_kind="latest_event",
            snapshot_complete=False,
            full_baseline_available=False,
            stream_id=self.key.stream_id,
            snapshot_epoch="market-epoch-1",
            snapshot_sequence=0,
            resync_required=False,
        )

    def poll(self, *, timeout_ms=0):
        assert timeout_ms == 0
        return self.events.popleft() if self.events else None

    def history(self, _request):
        raise AssertionError("history must not be called by the tick probe")

    def close(self):
        self.closed = True


def _proxy(events=(), *, scope=_SCOPE, clock_domain=_CLOCK_DOMAIN, observation=None):
    market = _MarketClient(events)
    if scope != _SCOPE:
        market.stream_scope = scope
    proxy = ServiceReadProxy(
        _AccountClient(observation),
        {
            _INSTRUMENT.native_symbol: ServiceCtpTickBinding(
                market,
                _RESOURCE,
                "contracts",
                clock_domain,
            )
        },
        valuation_currency="CNY",
        position_mode="net",
    )
    proxy.connect()
    proxy.subscribe(_INSTRUMENT.native_symbol)
    return proxy, market


def test_poll_tick_preserves_provider_payload_and_validates_both_cursors():
    source_tick = _tick()
    proxy, _ = _proxy((_event(1, source_tick),))

    result = proxy.poll_tick(_INSTRUMENT.native_symbol)

    assert {key: value for key, value in source_tick.items() if key != "quality_flags"} == {
        key: value for key, value in result.items() if key != "quality_flags"
    }
    assert result["quality_flags"] == ()
    assert result["connection_generation"] == 7
    assert result["subscription_epoch"] == 3
    assert result["ingest_seq"] == 20
    assert result["recv_monotonic_ns"] == source_tick["recv_monotonic_ns"]
    assert result["clock_domain_id"] == _CLOCK_DOMAIN
    assert "bar" not in result


@pytest.mark.parametrize(
    "event,code",
    [
        (_event(2, _tick()), "CTP_TICK_EVENT_INVALID"),
        (_event(1, _tick(), stream_epoch="wrong-market-epoch"), "CTP_TICK_EVENT_INVALID"),
        (_event(1, _tick(clock_domain_id="other-clock")), "CTP_TICK_EVENT_INVALID"),
        (_event(1, _tick(symbol="CZCE.SA701P1080")), "CTP_TICK_EVENT_INVALID"),
        (_event(1, _tick(connection_generation=True)), "CTP_TICK_EVENT_INVALID"),
        (_event(1, _tick(ingest_seq=0)), "CTP_TICK_EVENT_INVALID"),
    ],
)
def test_poll_tick_fails_closed_on_wire_or_source_identity_gap(event, code):
    proxy, _ = _proxy((event,))

    with pytest.raises(ServiceReadProxyError, match=code):
        proxy.poll_tick(_INSTRUMENT.native_symbol)


def test_poll_tick_rejects_wrong_authenticated_scope():
    wrong_scope = WireScope("other-domain", strategy_ref="ctp_options_midfreq")
    proxy, _ = _proxy((_event(1, _tick(), scope=wrong_scope),))

    with pytest.raises(ServiceReadProxyError, match="CTP_TICK_EVENT_INVALID"):
        proxy.poll_tick(_INSTRUMENT.native_symbol)


def test_poll_tick_rejects_provider_generation_change_and_nonmonotonic_source_sequence():
    first = _tick()
    proxy, _ = _proxy((_event(1, first), _event(2, _tick(generation=8, ingest_seq=21))))
    proxy.poll_tick(_INSTRUMENT.native_symbol)
    with pytest.raises(ServiceReadProxyError, match="CTP_SOURCE_SCOPE_CHANGED"):
        proxy.poll_tick(_INSTRUMENT.native_symbol)

    proxy, _ = _proxy((_event(1, first), _event(2, _tick(subscription_epoch=4, ingest_seq=21))))
    proxy.poll_tick(_INSTRUMENT.native_symbol)
    with pytest.raises(ServiceReadProxyError, match="CTP_SOURCE_SCOPE_CHANGED"):
        proxy.poll_tick(_INSTRUMENT.native_symbol)

    proxy, _ = _proxy((_event(1, first), _event(2, _tick(ingest_seq=20))))
    proxy.poll_tick(_INSTRUMENT.native_symbol)
    with pytest.raises(ServiceReadProxyError, match="CTP_INGEST_SEQUENCE_INVALID"):
        proxy.poll_tick(_INSTRUMENT.native_symbol)


def test_ctp_tick_binding_rejects_bar_route_or_missing_clock_domain():
    market = _MarketClient()
    market.key = MarketSubscriptionKey(
        "ctp-md-source", "ctp-md-entitlement", _INSTRUMENT, "bar", timeframe="1m"
    )
    with pytest.raises(ValueError, match="fixed ctp.quote.v2"):
        ServiceCtpTickBinding(market, _RESOURCE, "contracts", _CLOCK_DOMAIN)
    with pytest.raises(ValueError, match="clock_domain_id"):
        ServiceCtpTickBinding(_MarketClient(), _RESOURCE, "contracts", "")


def test_ctp_tick_route_never_reads_or_emits_bars():
    proxy, market = _proxy((_event(1, _tick()),))

    with pytest.raises(ServiceReadProxyError, match="CTP_TICK_HISTORY_UNSUPPORTED"):
        proxy.fetch_bars(_INSTRUMENT.native_symbol)
    assert proxy.poll_bar(_INSTRUMENT.native_symbol) is None
    assert len(market.events) == 1


def test_bar_binding_tick_probe_is_idle_and_does_not_break_bar_facade():
    market = _MarketClient()
    market.key = MarketSubscriptionKey(
        "ctp-md-source", "ctp-md-entitlement", _INSTRUMENT, "bar", timeframe="1m"
    )
    proxy = ServiceReadProxy(
        _AccountClient(),
        {
            _INSTRUMENT.native_symbol: ServiceFeedBinding(
                market, _RESOURCE, "contracts", "1m"
            )
        },
        valuation_currency="CNY",
        position_mode="net",
    )
    proxy.connect()
    proxy.subscribe(_INSTRUMENT.native_symbol)

    assert proxy.poll_tick(_INSTRUMENT.native_symbol) is None


def test_tick_binding_maps_account_positions_and_open_orders():
    observation = AccountObservation(
        account_key=_ACCOUNT,
        observation_id="account-observation-with-position-and-order",
        coverage=(_RESOURCE,),
        balances=(AccountBalance(_RESOURCE, "CNY", "100", "90", "10", _OBSERVED),),
        positions=(
            AccountPosition(
                _RESOURCE,
                _INSTRUMENT,
                "net",
                "2",
                "contracts",
                "10",
                "CNY",
                _OBSERVED,
            ),
        ),
        valuation=AccountValuation("CNY", "90", "100", _OBSERVED),
        started_at_utc=_OBSERVED,
        completed_at_utc=_OBSERVED,
        consistency="provider_atomic",
        balances_complete=True,
        positions_complete=True,
        open_orders=(
            AccountOpenOrder(
                resource=_RESOURCE,
                instrument=_INSTRUMENT,
                order_id="ctp-open-order-1",
                side="buy",
                position_side="net",
                order_type="limit",
                status="partially_filled",
                quantity="3",
                filled_quantity="1",
                qty_unit="contracts",
                created_at_utc=_OBSERVED,
                observed_at_utc=_OBSERVED,
                client_order_id="ctp-client-order-1",
                limit_price="9.5",
                price_currency="CNY",
                reduce_only=False,
            ),
        ),
        open_orders_complete=True,
    )
    proxy, _ = _proxy(observation=observation)

    positions = proxy.get_positions()
    orders = proxy.fetch_open_orders()

    assert len(positions) == 1
    assert positions[0]["size"] == 2.0
    assert positions[0]["data_name"] == _INSTRUMENT.native_symbol
    assert len(orders) == 1
    assert orders[0]["order_id"] == "ctp-open-order-1"
    assert orders[0]["quantity"] == 3.0
    assert orders[0]["filled_quantity"] == 1.0


def test_tick_only_service_store_feed_idle_does_not_request_a_bar():
    proxy, market = _proxy()
    store = BtApiStore(provider="btapi", api=proxy)
    feed = BtApiFeed(
        dataname=_INSTRUMENT.native_symbol,
        store=store,
        provider="btapi",
        timeframe=TimeFrame.Ticks,
        compression=1,
        dispatch_ticks=True,
        dispatch_bars=False,
        backfill_start=False,
        qcheck=0,
    )

    feed.start()
    try:
        assert feed._load() is None
    finally:
        feed.stop()
        store.stop()

    assert list(market.events) == []
