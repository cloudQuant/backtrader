"""Iteration 60, step 60.10: Gateway market path across real processes.

A child process plays the Gateway publisher (CURVE PUB, MessagePack v1). This
process subscribes, decodes each received message once, binds it to its own
authenticated subscription source and projects it through the Backtrader
adapter. Verified here:

* decoded payloads equal what the publisher meant to send;
* every decode yields a distinct immutable object (no cross-process identity);
* deliberately skipped sequences are reported as gaps, never hidden;
* after the publisher is killed and restarts under a new epoch, the receiver
  sees NEW_EPOCH and must bind with the new source epoch (old-epoch binding
  is refused).
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
pytest.importorskip("bt_api_py.gateway_market_receiver")

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_py.gateway_market_receiver import (  # noqa: E402
    GatewayMarketBindingError,
    bind_received_tick,
)
from bt_api_transport_zmq.market_v2 import (  # noqa: E402
    MARKET_WIRE_VERSION_MSGPACK_V1,
    ContainerSequenceMonitor,
    ZmqMarketSubscriber,
)
from bt_api_transport_zmq.server import CurveClientCredentials  # noqa: E402

from backtrader.feeds.market_tick_adapter import adapt_market_tick_event  # noqa: E402
from tests.integration import iter60_gateway_publisher_process as child  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as baseline  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


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

    def subscriber(self):
        return ZmqMarketSubscriber(
            self.endpoint,
            WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
            WireScope(execution_domain_ref="public:ctp-market"),
            credentials=CurveClientCredentials(
                self.server_public, self.client_public, self.client_secret
            ),
            wire_version=MARKET_WIRE_VERSION_MSGPACK_V1,
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
        message = subscriber.receive_container(timeout_ms=50)
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
    monitor = ContainerSequenceMonitor()
    outcomes = [monitor.observe(message) for message in messages]
    sequences = [message.stream.sequence for message in messages]
    # Skipped sequences (every 25th) are visible as gaps.
    assert "GAP" in outcomes
    assert not any(sequence % child.GAP_EVERY == 0 for sequence in sequences)
    for message in messages:
        assert message.payload == child.expected_payload(message.stream.sequence)
        fields = adapt_market_tick_event(bind_received_tick(message, baseline.SOURCE))
        assert fields.last_price == 1500.0 + message.stream.sequence
        assert fields.sequence == message.stream.sequence
    # One decode per message: no two messages share a payload object.
    assert len({id(message.payload) for message in messages}) == len(messages)


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
    monitor = ContainerSequenceMonitor()
    for message in before:
        monitor.observe(message)
    assert monitor.observe(after[0]) == "NEW_EPOCH"
    # The old subscription source no longer binds the restarted stream ...
    with pytest.raises(GatewayMarketBindingError) as info:
        bind_received_tick(after[0], baseline.SOURCE)
    assert info.value.code == "GATEWAY_STREAM_MISMATCH"
    # ... the receiver must resynchronize with the new epoch's source.
    renewed = dataclasses.replace(baseline.SOURCE, epoch="epoch-2")
    assert bind_received_tick(after[0], renewed).cursor.epoch == "epoch-2"
