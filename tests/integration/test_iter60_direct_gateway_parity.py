"""Iteration 60 (60.09/60.10, acceptance report P1-2/P1-3): direct and Gateway ticks agree.

The same neutral payload travels two ways:

* direct: SDK binds it to the authenticated source -> BT adapter;
* Gateway (product path): a market event envelope is encoded as service wire
  v3 MessagePack, decoded once, and the receiving side binds the tick to its
  own authenticated subscription source -> BT adapter.

Backtrader must see field-for-field identical projections (plan §10
"direct / Gateway 对等"), and the receiver must refuse a message that does not
belong to its subscription.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone

import pytest

pytest.importorskip("msgpack")
pytest.importorskip("bt_api_base.market_protocol")

from bt_api_base.market_protocol import (  # noqa: E402
    MARKET_EVENT_OPERATION,
    MARKET_EVENT_SCHEMA,
    MARKET_EVENT_SCHEMA_VERSION,
)
from bt_api_base.market_tick_protocol import (  # noqa: E402
    MarketEventCursor,
    MarketTickContractError,
    MarketTickPayload,
    bind_market_tick_event,
)
from bt_api_base.service_protocol import (  # noqa: E402
    WIRE_PROTOCOL_VERSION,
    WireEnvelope,
    WireHeader,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
    decode_envelope,
    encode_envelope,
    envelope_to_wire_mapping,
)

from backtrader.feeds.market_tick_adapter import adapt_market_tick_event  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as baseline  # noqa: E402

SOURCE = baseline.SOURCE


def _direct(payload):
    event = bind_market_tick_event(
        payload,
        SOURCE,
        MarketEventCursor(stream_id=SOURCE.stream_id, epoch=SOURCE.epoch, sequence=7),
    )
    return adapt_market_tick_event(event)


def _wire(payload, *, stream_id=None, epoch=None, sequence=7) -> bytes:
    envelope = WireEnvelope(
        header=WireHeader(
            protocol_version=WIRE_PROTOCOL_VERSION,
            kind=WireMessageKind.EVENT,
            message_id=uuid.uuid4().hex,
            correlation_id=None,
            identity=WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
            scope=WireScope(execution_domain_ref="public:ctp-market"),
            operation=MARKET_EVENT_OPERATION,
            schema_id=MARKET_EVENT_SCHEMA,
            schema_version=MARKET_EVENT_SCHEMA_VERSION,
            sent_at_utc=datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            stream_id=stream_id or SOURCE.stream_id,
            stream_epoch=epoch or SOURCE.epoch,
            sequence=sequence,
        ),
        payload={"key": baseline.SUBSCRIPTION.to_dict(), "data": payload.to_dict()},
    )
    return encode_envelope(envelope)


def _receive(raw: bytes, source=SOURCE):
    envelope = decode_envelope(raw)
    data = envelope_to_wire_mapping(envelope)["payload"]["data"]
    header = envelope.header
    return bind_market_tick_event(
        MarketTickPayload.from_dict(data),
        source,
        MarketEventCursor(
            stream_id=header.stream_id, epoch=header.stream_epoch, sequence=header.sequence
        ),
    )


def _comparable(fields):
    values = dict(vars(fields))
    event = values.pop("market_tick_event")
    return values, event


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"delta_volume": None, "volume_complete": False},
        {"quality_flags": ("CROSSED_BOOK",)},
        {"execution_eligible": False, "last_price": 1500.25, "turnover": 123456789.125},
    ],
)
def test_direct_and_gateway_projections_are_identical(overrides):
    payload = baseline._payload(**overrides)
    direct_values, direct_event = _comparable(_direct(payload))
    gateway_values, gateway_event = _comparable(adapt_market_tick_event(_receive(_wire(payload))))
    assert gateway_values == direct_values
    # Different objects (one per process boundary) but equal facts.
    assert gateway_event == direct_event
    assert gateway_event is not direct_event


def test_receiver_rejects_a_message_for_another_stream_or_epoch():
    payload = baseline._payload()
    for raw in (
        _wire(payload, stream_id="market-" + "0" * 64),
        _wire(payload, epoch="epoch-2"),
    ):
        with pytest.raises(MarketTickContractError):
            _receive(raw)
    renewed = dataclasses.replace(SOURCE, epoch="epoch-2")
    assert _receive(_wire(payload, epoch="epoch-2"), renewed).cursor.epoch == "epoch-2"


def test_receiver_rejects_a_payload_from_another_source_generation():
    payload = baseline._payload(provider_connection_generation=2)
    with pytest.raises(MarketTickContractError):
        _receive(_wire(payload))
