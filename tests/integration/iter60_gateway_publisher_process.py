"""Child process for the iteration-60 multi-process Gateway test.

Publishes tick market events (service wire v3 MessagePack envelopes, market
wire v2 topic framing: the product Gateway path) over a CURVE PUB socket until
stdin closes.
Sequences divisible by ``GAP_EVERY`` are skipped on purpose so the receiver
can prove gaps are observable. Configuration comes from the environment:
``ITER60_SERVER_PUBLIC``/``ITER60_SERVER_SECRET``/``ITER60_CLIENT_PUBLIC``
(Z85) and ``ITER60_EPOCH``. The bound endpoint is printed on stdout.
"""

from __future__ import annotations

import os
import sys
import threading
import time

GAP_EVERY = 25


def expected_payload(sequence: int):
    from tests.unit.feeds import test_market_tick_adapter_baseline as baseline

    return baseline._payload(last_price=1500.0 + sequence, provider_sequence=sequence)


def main() -> int:
    import uuid
    from datetime import datetime, timezone

    from bt_api_base.market_protocol import (
        MARKET_EVENT_OPERATION,
        MARKET_EVENT_SCHEMA,
        MARKET_EVENT_SCHEMA_VERSION,
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
    from bt_api_transport_zmq.market_v2 import (
        MARKET_WIRE_VERSION_TOPIC_FILTERED,
        ZmqMarketPublisher,
    )
    from bt_api_transport_zmq.server import CurveServerCredentials
    from tests.unit.feeds import test_market_tick_adapter_baseline as baseline

    identity = WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider")
    scope = WireScope(execution_domain_ref="public:ctp-market")
    publisher = ZmqMarketPublisher(
        "tcp://127.0.0.1:*",
        identity,
        scope,
        {os.environ["ITER60_CLIENT_PUBLIC"].encode(): "strategy-host-1"},
        credentials=CurveServerCredentials(
            os.environ["ITER60_SERVER_PUBLIC"].encode(),
            os.environ["ITER60_SERVER_SECRET"].encode(),
        ),
        wire_version=MARKET_WIRE_VERSION_TOPIC_FILTERED,
    )
    print(publisher.endpoint, flush=True)
    stop = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.read(), stop.set()), daemon=True).start()
    epoch = os.environ["ITER60_EPOCH"]
    sequence = 0
    deadline = time.monotonic() + 30
    try:
        while not stop.is_set() and time.monotonic() < deadline:
            sequence += 1
            if sequence % GAP_EVERY == 0:
                continue
            publisher.try_publish(
                WireEnvelope(
                    header=WireHeader(
                        protocol_version=WIRE_PROTOCOL_VERSION,
                        kind=WireMessageKind.EVENT,
                        message_id=uuid.uuid4().hex,
                        correlation_id=None,
                        identity=identity,
                        scope=scope,
                        operation=MARKET_EVENT_OPERATION,
                        schema_id=MARKET_EVENT_SCHEMA,
                        schema_version=MARKET_EVENT_SCHEMA_VERSION,
                        sent_at_utc=datetime.now(timezone.utc)
                        .isoformat(timespec="microseconds")
                        .replace("+00:00", "Z"),
                        stream_id=baseline.SUBSCRIPTION.stream_id,
                        stream_epoch=epoch,
                        sequence=sequence,
                    ),
                    payload={
                        "key": baseline.SUBSCRIPTION.to_dict(),
                        "data": expected_payload(sequence).to_dict(),
                    },
                )
            )
            time.sleep(0.001)
    finally:
        publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
