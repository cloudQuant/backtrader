"""Iteration 60 (60.09/60.10): direct and Gateway ticks reach Backtrader identically.

The same neutral payload travels two ways:

* direct: SDK binds it to the authenticated source -> BT adapter;
* Gateway: MessagePack v1 encode -> decode once -> receiving SDK binds it to
  its own authenticated subscription source -> BT adapter.

Backtrader must see field-for-field identical projections (plan §10
"direct / Gateway 对等"), and the receiver must refuse a message that does not
belong to its subscription.
"""

from __future__ import annotations

import pytest

pytest.importorskip("msgpack")
pytest.importorskip("bt_api_py.gateway_market_receiver")

from bt_api_base.market_tick_protocol import MarketEventCursor, bind_market_tick_event  # noqa: E402
from bt_api_base.wire_codec_v1 import StreamPosition, decode_message, encode_message  # noqa: E402
from bt_api_py.gateway_market_receiver import (  # noqa: E402
    GatewayMarketBindingError,
    bind_received_tick,
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


def _gateway(payload, *, stream=None):
    stream = stream or StreamPosition(SOURCE.stream_id, SOURCE.epoch, 7)
    message = decode_message(encode_message("tick", payload, stream=stream))
    return adapt_market_tick_event(bind_received_tick(message, SOURCE))


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
    gateway_values, gateway_event = _comparable(_gateway(payload))
    assert gateway_values == direct_values
    # Different objects (one per process boundary) but equal facts.
    assert gateway_event == direct_event
    assert gateway_event is not direct_event


def test_receiver_rejects_a_message_for_another_stream_or_epoch():
    payload = baseline._payload()
    for stream in (
        StreamPosition("market-" + "0" * 64, SOURCE.epoch, 7),
        StreamPosition(SOURCE.stream_id, "epoch-2", 7),
    ):
        message = decode_message(encode_message("tick", payload, stream=stream))
        with pytest.raises(GatewayMarketBindingError) as info:
            bind_received_tick(message, SOURCE)
        assert info.value.code == "GATEWAY_STREAM_MISMATCH"


def test_receiver_rejects_a_payload_from_another_source_generation():
    payload = baseline._payload(provider_connection_generation=2)
    message = decode_message(
        encode_message("tick", payload, stream=StreamPosition(SOURCE.stream_id, SOURCE.epoch, 7))
    )
    with pytest.raises(GatewayMarketBindingError):
        bind_received_tick(message, SOURCE)
