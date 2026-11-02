"""60.10 perf: JSON WireEnvelope (existing transport) vs MessagePack wire v1."""
import dataclasses, json, statistics, sys, timeit, platform
sys.path[:0] = ["."]
import msgpack
from tests.unit.feeds import test_market_tick_adapter_baseline as B
from bt_api_base.wire_codec_v1 import StreamPosition, encode_message, decode_message
from bt_api_py.gateway_market_receiver import bind_received_tick
from backtrader.feeds.market_tick_adapter import adapt_market_tick_event

def med(fn, n):
    return statistics.median(min(timeit.repeat(fn, number=n, repeat=1)) / n * 1e9 for _ in range(7))

try:
    import msgpack._cmsgpack  # noqa: F401
    impl = "C extension"
except Exception:
    impl = "pure-Python fallback"
payload = B._payload()
stream = StreamPosition(B.SOURCE.stream_id, B.SOURCE.epoch, 7)
mp = encode_message("tick", payload, stream=stream)
# JSON baseline: the same neutral fields as a plain JSON object (what the
# existing transport's JSON WireEnvelope carries in its payload).
def to_json():
    data = dataclasses.asdict(payload)
    for k, v in list(data.items()):
        if hasattr(v, "value"):
            data[k] = v.value
    return json.dumps({"key": "k", "data": data}, separators=(",", ":"), default=str).encode()
js = to_json()
print(f"python {platform.python_version()} {platform.machine()}; msgpack {msgpack.version} ({impl})")
print(f"message bytes: msgpack_v1={len(mp)} json={len(js)}")
print(f"encode  msgpack_v1           {med(lambda: encode_message('tick', payload, stream=stream), 5000):9.0f} ns")
print(f"encode  json(asdict+dumps)   {med(to_json, 5000):9.0f} ns")
print(f"decode  msgpack_v1 -> frozen {med(lambda: decode_message(mp), 5000):9.0f} ns")
print(f"decode  json.loads only      {med(lambda: json.loads(js), 5000):9.0f} ns")
msg = decode_message(mp)
print(f"bind    receiver source      {med(lambda: bind_received_tick(msg, B.SOURCE), 5000):9.0f} ns")
event = bind_received_tick(msg, B.SOURCE)
print(f"adapt   BT projection        {med(lambda: adapt_market_tick_event(event), 5000):9.0f} ns")
print(f"e2e     decode+bind+adapt    {med(lambda: adapt_market_tick_event(bind_received_tick(decode_message(mp), B.SOURCE)), 2000):9.0f} ns")

# Breakdown of the decode cost.
from bt_api_base.market_tick_protocol import MarketTickPayload
raw = msgpack.unpackb(mp, raw=False)
fields = {f.name: getattr(payload, f.name) for f in dataclasses.fields(MarketTickPayload)}
print(f"part    msgpack.unpackb (bare)   {med(lambda: msgpack.unpackb(mp, raw=False), 5000):9.0f} ns")
print(f"part    MarketTickPayload(**)    {med(lambda: MarketTickPayload(**fields), 5000):9.0f} ns")
try:
    import msgspec
    enc = msgspec.msgpack.encode(raw)
    print(f"part    msgspec.msgpack.decode   {med(lambda: msgspec.msgpack.decode(enc), 20000):9.0f} ns  (msgspec {msgspec.__version__}, C)")
    print(f"part    msgspec.msgpack.encode   {med(lambda: msgspec.msgpack.encode(raw), 20000):9.0f} ns")
except ImportError:
    print("msgspec not installed")

# Like-for-like: JSON all the way back to the same frozen container.
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.market_tick_protocol import MarketClockQuality, MarketFreshnessStatus
_ENUMS = {"source_clock_quality": MarketClockQuality, "receive_clock_quality": MarketClockQuality,
          "freshness_status": MarketFreshnessStatus}
def json_to_container():
    data = json.loads(js)["data"]
    data["instrument"] = MarketInstrumentKey(**data["instrument"])
    for k, enum in _ENUMS.items():
        data[k] = enum(data[k])
    for k in ("freshness_reason_codes", "quality_flags"):
        data[k] = tuple(data[k])
    return MarketTickPayload(**data)
assert json_to_container() == payload
print(f"decode  json -> frozen (fair)    {med(json_to_container, 5000):9.0f} ns")
