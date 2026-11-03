"""Iteration 60 end-to-end performance (acceptance report P1-7).

Thresholds are fixed in THRESHOLDS below *before* any run and printed with
every result. Three measurements, one machine, one interpreter, fixed inputs:

1. codec: service-envelope encode + strict decode round trip of one tick
   market event (same validation on both sides: decode_envelope +
   WireEnvelope freeze). Run once on the current Base (wire v3 MessagePack)
   and once with PYTHONPATH pointing at the pre-v3 Base (wire v2 JSON) to
   compare at equal validation strength.
2. direct: per-tick bind_market_tick_event + Backtrader adapter, in process.
3. gateway: a real child process publishes N ticks at a fixed rate over
   CURVE PUB/SUB (product framing); this process receives, decodes, binds to
   its own source and runs the Backtrader adapter. Latency is
   receive-complete minus publish-start (time.monotonic_ns is system-wide).
   Reports p50/p95/p99, loss, throughput and RSS growth.

Usage::

    python bench_e2e.py [--messages 20000] [--rate 2000] [--codec-only]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(REPO))

THRESHOLDS = {
    # Gateway path at --rate messages/s, per tick, publish -> BT adapter done.
    "gateway_p99_ms": 5.0,
    "gateway_loss": 0,
    "gateway_rss_growth_mb": 50.0,
    # In-process direct path (bind + BT adapter) per tick.
    "direct_p99_us": 200.0,
    # v3 MessagePack envelope round trip vs v2 JSON at equal validation:
    # GO only if not slower by more than 10% (with the msgpack C extension).
    "codec_v3_vs_v2_max_ratio": 1.10,
}


def _pct(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _envelope(sequence, *, epoch="bench-epoch", sent_ns=None):
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
    from tests.unit.feeds import test_market_tick_adapter_baseline as baseline

    payload = baseline._payload(last_price=1500.0 + sequence, provider_sequence=sequence)
    return WireEnvelope(
        header=WireHeader(
            protocol_version=WIRE_PROTOCOL_VERSION,
            kind=WireMessageKind.EVENT,
            message_id=f"{sequence}-{sent_ns or 0}-{uuid.uuid4().hex[:8]}",
            correlation_id=None,
            identity=WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
            scope=WireScope(execution_domain_ref="public:ctp-market"),
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
        payload={"key": baseline.SUBSCRIPTION.to_dict(), "data": payload.to_dict()},
    )


def bench_codec(n=20000):
    from bt_api_base import service_protocol as protocol

    envelope = _envelope(1)
    samples = []
    for _ in range(n):
        start = time.perf_counter_ns()
        protocol.decode_envelope(protocol.encode_envelope(envelope))
        samples.append(time.perf_counter_ns() - start)
    try:
        from msgpack import _cmsgpack  # noqa: F401

        backend = "c"
    except ImportError:
        backend = "python"
    return {
        "protocol_version": protocol.WIRE_PROTOCOL_VERSION,
        "msgpack_backend": backend,
        "bytes": len(protocol.encode_envelope(envelope)),
        "median_us": statistics.median(samples) / 1000,
        "p99_us": _pct(samples, 0.99) / 1000,
    }


def _thaw(value):
    if type(value).__name__ == "mappingproxy" or isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _consume(envelope, source):
    from bt_api_base.market_tick_protocol import (
        MarketEventCursor,
        MarketTickPayload,
        bind_market_tick_event,
    )

    from backtrader.feeds.market_tick_adapter import adapt_market_tick_event

    header = envelope.header
    event = bind_market_tick_event(
        MarketTickPayload.from_dict(_thaw(envelope.payload["data"])),
        source,
        MarketEventCursor(
            stream_id=header.stream_id, epoch=header.stream_epoch, sequence=header.sequence
        ),
    )
    return adapt_market_tick_event(event)


def bench_direct(n=20000):
    from bt_api_base.market_tick_protocol import MarketEventCursor, bind_market_tick_event

    from backtrader.feeds.market_tick_adapter import adapt_market_tick_event
    from tests.unit.feeds import test_market_tick_adapter_baseline as baseline

    payloads = [baseline._payload(last_price=1500.0 + i, provider_sequence=i + 1) for i in range(64)]
    samples = []
    for i in range(n):
        start = time.perf_counter_ns()
        adapt_market_tick_event(
            bind_market_tick_event(
                payloads[i % 64],
                baseline.SOURCE,
                MarketEventCursor(
                    stream_id=baseline.SOURCE.stream_id, epoch=baseline.SOURCE.epoch, sequence=i + 1
                ),
            )
        )
        samples.append(time.perf_counter_ns() - start)
    return {"median_us": statistics.median(samples) / 1000, "p99_us": _pct(samples, 0.99) / 1000}


def _publisher_child(messages, rate):
    import zmq  # noqa: F401
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_transport_zmq.market_v2 import MARKET_WIRE_VERSION_TOPIC_FILTERED, ZmqMarketPublisher
    from bt_api_transport_zmq.server import CurveServerCredentials

    publisher = ZmqMarketPublisher(
        "tcp://127.0.0.1:*",
        WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
        WireScope(execution_domain_ref="public:ctp-market"),
        {os.environ["B_CLIENT_PUBLIC"].encode(): "bench-client"},
        credentials=CurveServerCredentials(
            os.environ["B_SERVER_PUBLIC"].encode(), os.environ["B_SERVER_SECRET"].encode()
        ),
        wire_version=MARKET_WIRE_VERSION_TOPIC_FILTERED,
        high_water_mark=100_000,
    )
    print(publisher.endpoint, flush=True)
    sys.stdin.readline()  # subscriber is ready
    interval = 1.0 / rate
    start = time.monotonic()
    for sequence in range(1, messages + 1):
        target = start + (sequence - 1) * interval
        while time.monotonic() < target:
            pass
        sent_ns = time.monotonic_ns()
        if not publisher.try_publish(_envelope(sequence, sent_ns=sent_ns)):
            print(f"HWM_DROP {sequence}", file=sys.stderr, flush=True)
    time.sleep(1.0)
    publisher.close()


def bench_gateway(messages, rate):
    import zmq
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_transport_zmq.market_v2 import MARKET_WIRE_VERSION_TOPIC_FILTERED, ZmqMarketSubscriber
    from bt_api_transport_zmq.server import CurveClientCredentials
    from tests.unit.feeds import test_market_tick_adapter_baseline as baseline

    source = __import__("dataclasses").replace(baseline.SOURCE, epoch="bench-epoch")
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    env = dict(
        os.environ,
        B_SERVER_PUBLIC=server_public.decode(),
        B_SERVER_SECRET=server_secret.decode(),
        B_CLIENT_PUBLIC=client_public.decode(),
    )
    child = subprocess.Popen(
        [sys.executable, __file__, "--child", "--messages", str(messages), "--rate", str(rate)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    endpoint = child.stdout.readline().strip()
    subscriber = ZmqMarketSubscriber(
        endpoint,
        WireIdentity(WireRole.SERVICE, "gateway-market-hub", "ctp-provider"),
        WireScope(execution_domain_ref="public:ctp-market"),
        credentials=CurveClientCredentials(server_public, client_public, client_secret),
        wire_version=MARKET_WIRE_VERSION_TOPIC_FILTERED,
        subscription_key=baseline.SUBSCRIPTION,
        high_water_mark=100_000,
    )
    time.sleep(0.5)  # let the subscription propagate
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child.stdin.write("go\n")
    child.stdin.flush()
    latencies, seen = [], set()
    first = last = None
    deadline = time.monotonic() + messages / rate + 10
    while len(seen) < messages and time.monotonic() < deadline:
        envelope = subscriber.receive(timeout_ms=200)
        if envelope is None:
            continue
        _consume(envelope, source)
        now = time.monotonic_ns()
        sent_ns = int(envelope.header.message_id.split("-")[1])
        latencies.append(now - sent_ns)
        seen.add(envelope.header.sequence)
        first = first or now
        last = now
    subscriber.close()
    child.wait(timeout=30)
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS, KiB on Linux
    return {
        "messages": messages,
        "rate_per_s": rate,
        "received": len(seen),
        "loss": messages - len(seen),
        "p50_ms": _pct(latencies, 0.50) / 1e6,
        "p95_ms": _pct(latencies, 0.95) / 1e6,
        "p99_ms": _pct(latencies, 0.99) / 1e6,
        "max_ms": max(latencies) / 1e6,
        "throughput_per_s": len(seen) / ((last - first) / 1e9) if last and first and last > first else 0,
        "rss_growth_mb": (rss_after - rss_before) * scale / 1e6,
        "publisher_hwm_drops": child.stderr.read().count("HWM_DROP"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", type=int, default=20000)
    parser.add_argument("--rate", type=int, default=2000)
    parser.add_argument("--codec-only", action="store_true")
    parser.add_argument("--child", action="store_true")
    options = parser.parse_args()
    if options.child:
        _publisher_child(options.messages, options.rate)
        return
    result = {"thresholds": THRESHOLDS, "python": sys.version.split()[0], "codec": bench_codec()}
    if not options.codec_only:
        result["direct"] = bench_direct()
        result["gateway"] = bench_gateway(options.messages, options.rate)
        gateway = result["gateway"]
        result["verdict"] = {
            "gateway_p99": gateway["p99_ms"] <= THRESHOLDS["gateway_p99_ms"],
            "gateway_loss": gateway["loss"] <= THRESHOLDS["gateway_loss"],
            "gateway_rss": gateway["rss_growth_mb"] <= THRESHOLDS["gateway_rss_growth_mb"],
            "direct_p99": result["direct"]["p99_us"] <= THRESHOLDS["direct_p99_us"],
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
