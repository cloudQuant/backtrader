"""Iteration 60, step 60.10 / acceptance report P1-2: Gateway market path across processes.

A child process plays the Gateway publisher on the product path: CURVE PUB,
market wire v2 topic framing, service wire v3 MessagePack envelopes. This
process subscribes, decodes each envelope once, binds the tick to its *own*
authenticated subscription source (``bind_market_tick_event``, as the SDK
service tick projection does) and projects it through the Backtrader adapter.
Verified here:

* decoded payloads equal what the publisher meant to send;
* deliberately skipped sequences are visible as gaps, never hidden;
* after the publisher is killed and restarts under a new epoch, the receiver
  sees a new stream epoch and must bind with the new source epoch (binding
  with the old epoch is refused);
* a client whose CURVE key is not in the audience receives nothing.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("msgpack")
zmq = pytest.importorskip("zmq")
pytest.importorskip("bt_api_transport_zmq.market_v2")

from bt_api_base.market_tick_protocol import (  # noqa: E402
    MarketEventCursor,
    MarketTickContractError,
    MarketTickPayload,
    bind_market_tick_event,
)
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_transport_zmq.market_v2 import (  # noqa: E402
    MARKET_WIRE_VERSION_TOPIC_FILTERED,
    ZmqMarketSubscriber,
)
from bt_api_transport_zmq.server import CurveClientCredentials  # noqa: E402

from backtrader.feeds.market_tick_adapter import adapt_market_tick_event  # noqa: E402
from tests.integration import iter60_gateway_publisher_process as child  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as baseline  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _thaw(value):
    if isinstance(value, dict) or type(value).__name__ == "mappingproxy":
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _bind(envelope, source):
    payload = MarketTickPayload.from_dict(_thaw(envelope.payload["data"]))
    header = envelope.header
    return bind_market_tick_event(
        payload,
        source,
        MarketEventCursor(
            stream_id=header.stream_id, epoch=header.stream_epoch, sequence=header.sequence
        ),
    )


class _Gateway:
    def __init__(self, epoch: str):
        self.server_public, self.server_secret = zmq.curve_keypair()
        self.client_public, self.client_secret = zmq.curve_keypair()
        env = dict(
            os.environ,
            ITER60_SERVER_PUBLIC=self.server_public.decode(),
            ITER60_SERVER_SECRET=self.server_secret.decode(),
            ITER60_CLIENT_PUBLIC=self.client_public.decode(),
            ITER60_EPOCH=epoch,
            PYTHONPATH=str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "tests.integration.iter60_gateway_publisher_process"],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.endpoint = self.process.stdout.readline().strip()
        if not self.endpoint.startswith("tcp://"):
            self.process.kill()
            raise AssertionError(self.process.stderr.read())

    def subscriber(self, *, client_keys=None):
        public, secret = client_keys or (self.client_public, self.client_secret)
        return ZmqMarketSubscriber(
            self.endpoint,
            WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
            WireScope(execution_domain_ref="public:ctp-market"),
            credentials=CurveClientCredentials(self.server_public, public, secret),
            wire_version=MARKET_WIRE_VERSION_TOPIC_FILTERED,
            subscription_key=baseline.SUBSCRIPTION,
        )

    def stop(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)

    def kill(self):
        self.process.kill()
        self.process.wait(timeout=10)


def _receive(subscriber, count, *, timeout=8.0):
    messages = []
    deadline = time.monotonic() + timeout
    while len(messages) < count and time.monotonic() < deadline:
        message = subscriber.receive(timeout_ms=50)
        if message is not None:
            messages.append(message)
    return messages


def test_gateway_publisher_process_to_backtrader_adapter():
    gateway = _Gateway("epoch-1")
    subscriber = gateway.subscriber()
    try:
        messages = _receive(subscriber, 120)
    finally:
        subscriber.close()
        gateway.stop()
    assert len(messages) >= 60, len(messages)
    sequences = [message.header.sequence for message in messages]
    assert sequences == sorted(sequences)
    # Skipped sequences (every 25th) are visible as gaps.
    gaps = [b - a for a, b in zip(sequences, sequences[1:]) if b - a > 1]
    assert gaps and not any(sequence % child.GAP_EVERY == 0 for sequence in sequences)
    for message in messages:
        sequence = message.header.sequence
        event = _bind(message, baseline.SOURCE)
        assert event.data == child.expected_payload(sequence)
        fields = adapt_market_tick_event(event)
        assert fields.last_price == 1500.0 + sequence
        assert fields.sequence == sequence


def test_publisher_crash_and_restart_is_seen_as_a_new_epoch():
    first = _Gateway("epoch-1")
    subscriber = first.subscriber()
    try:
        before = _receive(subscriber, 10)
    finally:
        subscriber.close()
        first.kill()  # abrupt: no clean shutdown
    second = _Gateway("epoch-2")
    subscriber = second.subscriber()
    try:
        after = _receive(subscriber, 10)
    finally:
        subscriber.close()
        second.stop()
    assert before and after
    assert {m.header.stream_epoch for m in before} == {"epoch-1"}
    assert after[0].header.stream_epoch == "epoch-2"
    # The old subscription source no longer binds the restarted stream ...
    with pytest.raises(MarketTickContractError):
        _bind(after[0], baseline.SOURCE)
    # ... the receiver must resynchronize with the new epoch's source.
    renewed = dataclasses.replace(baseline.SOURCE, epoch="epoch-2")
    assert _bind(after[0], renewed).cursor.epoch == "epoch-2"


def test_a_key_outside_the_audience_receives_nothing():
    gateway = _Gateway("epoch-1")
    stranger = gateway.subscriber(client_keys=zmq.curve_keypair())
    try:
        assert _receive(stranger, 1, timeout=1.5) == []
    finally:
        stranger.close()
        gateway.stop()
