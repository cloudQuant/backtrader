"""Focused contracts for service-proxied complete orderbook images."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from bt_api_base.account_protocol import (
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_protocol import (
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
    MarketInstrumentKey,
    MarketSourceDescriptor,
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

from backtrader.stores.service_read_proxy import (
    SERVICE_ORDERBOOK_SCHEMA_VERSION,
    ServiceOrderBookBinding,
    ServiceReadProxy,
    ServiceReadProxyError,
)


_NOW = datetime.now(timezone.utc).replace(microsecond=0)
_NOW_UTC = _NOW.isoformat(timespec="seconds").replace("+00:00", "Z")
_ACCOUNT = AccountKey("venue", "XNYS", "paper", "account-1")
_RESOURCE = AccountResourceKey("spot", "paper-wallet")
_INSTRUMENT = MarketInstrumentKey(
    "venue", "XNYS", "paper", "spot", "BTC-USD", "BTCUSD"
)
_KEY = MarketSubscriptionKey(
    "market-source",
    "market-entitlement",
    _INSTRUMENT,
    "orderbook",
    depth=5,
)
_SCOPE = WireScope("market-domain")
_EPOCH = "market-epoch-1"


def _source_descriptor(*, key: MarketSubscriptionKey = _KEY) -> MarketSourceDescriptor:
    return MarketSourceDescriptor(
        key=key,
        stream_id=key.stream_id,
        epoch=_EPOCH,
        provider=key.instrument.provider,
        source="synthetic.orderbook",
        connection_generation=1,
        clock_domain_id="synthetic-market-clock",
        clock_source_session_id="synthetic-session-1",
        clock_source="synthetic-provider-time",
    )


def _book_data(
    sequence: int,
    *,
    previous_sequence: int | None = None,
    kind: str = "snapshot",
    continuity: str = "snapshot",
    stale: bool = False,
    stale_reason: str = "",
    recovery_snapshot: bool = False,
    bids=((100, 2), (99, 3)),
    asks=((101, 4), (102, 5)),
    **changes,
):
    result = {
        "schema_version": SERVICE_ORDERBOOK_SCHEMA_VERSION,
        "complete_state": True,
        "timestamp": _NOW.timestamp() - 0.1,
        "symbol": _INSTRUMENT.native_symbol,
        "exchange": _INSTRUMENT.venue,
        "asset_type": _INSTRUMENT.product_type,
        "bids": bids,
        "asks": asks,
        "sequence": sequence,
        "previous_sequence": previous_sequence,
        "snapshot_or_delta": kind,
        "continuity_status": continuity,
        "stale": stale,
        "stale_reason": stale_reason,
        "recovery_snapshot": recovery_snapshot,
    }
    result.update(changes)
    return result


def _event(service_sequence: int, data, *, key: MarketSubscriptionKey = _KEY):
    return WireEnvelope(
        WireHeader(
            protocol_version=WIRE_PROTOCOL_VERSION,
            kind=WireMessageKind.EVENT,
            message_id=f"orderbook-{service_sequence}",
            correlation_id=None,
            identity=WireIdentity(WireRole.SERVICE, "market-service", "market-service"),
            scope=_SCOPE,
            operation=MARKET_EVENT_OPERATION,
            schema_id=MARKET_EVENT_SCHEMA,
            schema_version=MARKET_EVENT_SCHEMA_VERSION,
            sent_at_utc=_NOW_UTC,
            stream_id=key.stream_id,
            stream_epoch=_EPOCH,
            sequence=service_sequence,
        ),
        {"key": key.to_dict(), "data": data},
    )


class _AccountClient:
    expected_account = _ACCOUNT
    required_coverage = (_RESOURCE,)
    require_open_orders = True

    def refresh(self):
        observation = AccountObservation(
            account_key=_ACCOUNT,
            observation_id="account-observation-1",
            coverage=(_RESOURCE,),
            balances=(AccountBalance(_RESOURCE, "USD", "100", "90", "10", _NOW_UTC),),
            positions=(),
            valuation=AccountValuation("USD", "90", "100", _NOW_UTC),
            started_at_utc=_NOW_UTC,
            completed_at_utc=_NOW_UTC,
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
    healthy = True
    recovery_required = False

    def __init__(self, events=(), *, bootstrap=None, key=_KEY):
        self.key = key
        self.stream_scope = _SCOPE
        self.events = deque(events)
        self.bootstrap = bootstrap
        self._descriptor = None
        self.closed = False

    @property
    def source_descriptor(self):
        return self._descriptor

    def start(self):
        self._descriptor = _source_descriptor(key=self.key)
        bootstrap_sequence = 0 if self.bootstrap is None else 1
        return SimpleNamespace(
            snapshot=self.bootstrap,
            snapshot_kind="latest_event",
            snapshot_complete=False,
            full_baseline_available=False,
            stream_id=self.key.stream_id,
            snapshot_epoch=_EPOCH,
            snapshot_sequence=bootstrap_sequence,
            resync_required=False,
            source_descriptor=self._descriptor,
        )

    def poll(self, *, timeout_ms=0):
        assert timeout_ms == 0
        return self.events.popleft() if self.events else None

    def history(self, _request):
        raise AssertionError("orderbook binding must not query bar history")

    def close(self):
        self.closed = True


def _proxy(*, events=(), bootstrap=None, key=_KEY, quantity_multiplier="2"):
    market = _MarketClient(events, bootstrap=bootstrap, key=key)
    binding = ServiceOrderBookBinding(
        market,
        _RESOURCE,
        "base",
        quantity_multiplier=quantity_multiplier,
        max_depth=5,
    )
    proxy = ServiceReadProxy(
        _AccountClient(),
        {key.instrument.native_symbol: binding},
        valuation_currency="USD",
        position_mode="net",
        clock=lambda: _NOW,
    )
    proxy.connect()
    proxy.subscribe(key.instrument.native_symbol)
    return proxy, market, key.instrument.native_symbol


def test_orderbook_projects_complete_snapshot_and_contiguous_delta():
    bootstrap = _event(1, _book_data(100))
    delta = _event(
        2,
        _book_data(
            101,
            previous_sequence=100,
            kind="delta",
            continuity="continuous",
        ),
    )
    proxy, _market, dataname = _proxy(events=(delta,), bootstrap=bootstrap)

    source = proxy.orderbook_source_descriptor(dataname)
    first = proxy.poll_orderbook(dataname)
    second = proxy.poll_orderbook(dataname)

    assert source == _source_descriptor()
    assert first is not None and first.validate()
    assert (first.sequence, first.previous_sequence) == (100, None)
    assert first.snapshot_or_delta == "snapshot"
    assert first.stale is False
    assert first.source == source.source
    assert first.bids == [(100.0, 4.0), (99.0, 6.0)]
    assert first.asks == [(101.0, 8.0), (102.0, 10.0)]
    assert second is not None and second.validate()
    assert (second.sequence, second.previous_sequence) == (101, 100)
    assert second.snapshot_or_delta == "delta"


def test_provider_gap_requires_a_fresh_snapshot_before_delta_recovery():
    bootstrap = _event(1, _book_data(100))
    proxy, market, dataname = _proxy(bootstrap=bootstrap)
    first = proxy.poll_orderbook(dataname)
    assert first is not None

    market.events.extend(
        (
            _event(
                2,
                _book_data(
                    102,
                    previous_sequence=99,
                    kind="delta",
                    continuity="continuous",
                ),
            ),
            _event(
                3,
                _book_data(
                    103,
                    previous_sequence=102,
                    kind="delta",
                    continuity="continuous",
                ),
            ),
            _event(
                4,
                _book_data(105, kind="snapshot", continuity="snapshot", recovery_snapshot=True),
            ),
            _event(
                5,
                _book_data(
                    106,
                    previous_sequence=105,
                    kind="delta",
                    continuity="continuous",
                ),
            ),
        )
    )

    with pytest.raises(ServiceReadProxyError) as gap:
        proxy.poll_orderbook(dataname)
    with pytest.raises(ServiceReadProxyError) as recovery_delta:
        proxy.poll_orderbook(dataname)
    recovered = proxy.poll_orderbook(dataname)
    after_recovery = proxy.poll_orderbook(dataname)

    assert gap.value.code == "ORDERBOOK_SEQUENCE_GAP"
    assert recovery_delta.value.code == "ORDERBOOK_SEQUENCE_GAP"
    assert recovered is not None and recovered.sequence == 105
    assert recovered.stale is False and recovered.recovery_snapshot is True
    assert after_recovery is not None and after_recovery.sequence == 106
    assert after_recovery.stale is False


def test_stale_payload_latches_recovery_until_a_healthy_snapshot():
    bootstrap = _event(1, _book_data(200))
    proxy, market, dataname = _proxy(bootstrap=bootstrap)
    assert proxy.poll_orderbook(dataname) is not None

    market.events.extend(
        (
            _event(
                2,
                _book_data(
                    201,
                    previous_sequence=200,
                    kind="delta",
                    continuity="continuous",
                    stale=True,
                    stale_reason="provider_delay",
                ),
            ),
            _event(
                3,
                _book_data(
                    202,
                    previous_sequence=201,
                    kind="delta",
                    continuity="continuous",
                ),
            ),
            _event(4, _book_data(203, kind="snapshot", continuity="snapshot")),
        )
    )

    stale = proxy.poll_orderbook(dataname)
    blocked_delta = proxy.poll_orderbook(dataname)
    recovered = proxy.poll_orderbook(dataname)

    assert stale is not None and stale.stale is True
    assert stale.stale_reason == "provider_delay"
    assert blocked_delta is not None and blocked_delta.stale is True
    assert blocked_delta.stale_reason == "orderbook_recovery_snapshot_required"
    assert recovered is not None and recovered.stale is False


def test_invalid_depth_payload_consumes_only_transport_cursor():
    proxy, market, dataname = _proxy()
    market.events.extend(
        (
            _event(1, _book_data(10, bids=((100, 1),) * 6)),
            _event(2, _book_data(11)),
        )
    )

    with pytest.raises(ServiceReadProxyError) as invalid:
        proxy.poll_orderbook(dataname)
    recovered = proxy.poll_orderbook(dataname)

    assert invalid.value.code == "ORDERBOOK_EVENT_INVALID"
    assert recovered is not None and recovered.sequence == 11


@pytest.mark.parametrize(
    "changes",
    [
        {"complete_state": False},
        {"continuity_status": "unverified"},
        {"stale": True},
        {"recovery_snapshot": True, "snapshot_or_delta": "delta", "previous_sequence": 0},
    ],
)
def test_orderbook_rejects_incomplete_or_ambiguous_event_contract(changes):
    proxy, market, dataname = _proxy()
    market.events.append(_event(1, _book_data(1, **changes)))

    with pytest.raises(ServiceReadProxyError) as rejected:
        proxy.poll_orderbook(dataname)

    assert rejected.value.code == "ORDERBOOK_EVENT_INVALID"


def test_binding_rejects_unbounded_key_and_wrong_resource_product():
    unbounded_key = MarketSubscriptionKey(
        "market-source",
        "market-entitlement",
        _INSTRUMENT,
        "orderbook",
        depth=None,
    )
    unbounded_market = _MarketClient(key=unbounded_key)
    with pytest.raises(ValueError, match="bounded explicit depth"):
        ServiceOrderBookBinding(unbounded_market, _RESOURCE, "base")

    wrong_resource = AccountResourceKey("future", "paper-future-wallet")
    with pytest.raises(ValueError, match="product_type"):
        ServiceOrderBookBinding(_MarketClient(), wrong_resource, "contracts")
