"""Child process for the iteration-60 multi-process Gateway test.

Publishes MessagePack v1 ticks over a CURVE PUB socket until stdin closes.
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
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_base.wire_codec_v1 import StreamPosition
    from bt_api_transport_zmq.market_v2 import MARKET_WIRE_VERSION_MSGPACK_V1, ZmqMarketPublisher
    from bt_api_transport_zmq.server import CurveServerCredentials
    from tests.unit.feeds import test_market_tick_adapter_baseline as baseline

    publisher = ZmqMarketPublisher(
        "tcp://127.0.0.1:*",
        WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
        WireScope(execution_domain_ref="public:ctp-market"),
        {os.environ["ITER60_CLIENT_PUBLIC"].encode(): "strategy-host-1"},
        credentials=CurveServerCredentials(
            os.environ["ITER60_SERVER_PUBLIC"].encode(),
            os.environ["ITER60_SERVER_SECRET"].encode(),
        ),
        wire_version=MARKET_WIRE_VERSION_MSGPACK_V1,
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
            publisher.try_publish_container(
                "tick",
                expected_payload(sequence),
                StreamPosition(baseline.SOURCE.stream_id, epoch, sequence),
            )
            time.sleep(0.001)
    finally:
        publisher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
