"""Duck-typed gateway client used by the certification cases and strategies.

`GatewayClient` exposes the *same* surface as the suite's direct
``certlib.binance_client.BinanceDemoClient`` (``connect``, ``describe``,
``account_config``, ``balances``, ``position_risk``, ``open_orders``,
``filters``, ``mark_price``, ``place_order``, ``cancel_order``,
``query_order``, plus the ``host``/``server_time_ms``/``time_offset_ms``/
``connect_rtt_ms``/``calls``/``frozen`` attributes strategies and the evidence
builder read), but forwards one command per call to a
`optional16.gateway_server.GatewayServer` over the localhost ZMQ transport (or
the documented stdlib fallback) and returns the provider result unchanged.

Evidence behaviour
------------------
* ``.calls`` records per forwarded command: local time, command, redacted
  params, request id, outcome, round-trip duration, and either the error or a
  bounded result copy plus a result digest.
* ``.describe()`` reports ``transport="gateway_zmq"`` (or ``gateway_stdlib``)
  and the last server facts (endpoint, pid, journal path, provider freeze
  state), so one evidence file shows both provider and gateway.
* ``.host`` becomes the *venue* host the provider reports at ``connect()``;
  the gateway's own address stays in ``gateway_host``/``port``.

Failure semantics (mirrors the direct client's write policy)
------------------------------------------------------------
An uncorrelated reply (timeout, stopped/broken server, mismatched late frame)
raises ``GatewayCommandUncertain``; for a *write* that also freezes the client
so no compensating action follows an unknown outcome. Transport faults raise
``GatewayUnavailable``. After an uncertain outcome the link is re-created so a
stale reply frame can never be consumed as the next command's answer; the
command itself is never resent.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
import uuid
from typing import Any, Mapping, Optional

from .gateway_server import (
    DEFAULT_SCOPE,
    GatewayServer,
    load_transport_package,
    read_frame,
    transport_name,
    write_frame,
)

DEFAULT_TIMEOUT_SECONDS = 10.0
RESULT_COPY_CHARS = 4_096
_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "credential", "passphrase",
                        "password", "private_key", "secret", "token")


class GatewayError(RuntimeError):
    """Base class for gateway client failures."""


class GatewayUnavailable(GatewayError):
    """The gateway endpoint refused the connection or has already been closed."""


class GatewayCommandUncertain(GatewayError):
    """A command may have reached the server; the outcome is unknown."""


class GatewayRejected(GatewayError):
    """The transport or server rejected the request before/without a result."""


class ClientFrozen(GatewayError):
    """A previous write left the outcome unknown; writes are refused."""


class _ZmqLink:
    """One command channel over ``bt_api_transport_zmq.ZmqCommandClient``."""

    name = "zmq"

    def __init__(self, host: str, port: int, token: str, timeout_ms: int, max_message_bytes: int):
        self._module = load_transport_package()
        if self._module is None:  # pragma: no cover - the factory only picks zmq when importable
            raise GatewayUnavailable("transport_package_unavailable")
        self._endpoint = "tcp://%s:%d" % (host, port)
        self._token = token
        self._timeout_ms = timeout_ms
        self._max = max_message_bytes
        self._sequence = 0
        self._client = self._module.ZmqCommandClient(self._endpoint, max_message_bytes=self._max)

    @property
    def request_timeout_ms(self) -> int:
        return self._timeout_ms

    def call(self, command: str, params: Mapping) -> dict:
        module = self._module
        if self._client is None:
            raise GatewayUnavailable("gateway_link_unavailable:" + self._endpoint)
        message_id = uuid.uuid4().hex
        self._sequence += 1
        message = module.WireMessage(message_id=message_id, channel=module.WireChannel.COMMAND,
                                     scope=DEFAULT_SCOPE, sequence=self._sequence,
                                     sent_at=time.time(),
                                     payload={"command": command, "params": dict(params),
                                              "auth": self._token})
        try:
            response = self._client.request(message, self._timeout_ms)
        except Exception as exc:
            self.reset()  # drop the socket so a stale frame cannot poison the next call
            raise GatewayCommandUncertain(
                "%s: no correlated reply for %s within %dms (request_id=%s)"
                % (type(exc).__name__, command, self._timeout_ms, message_id)) from exc
        payload = response.payload
        if payload.get("accepted") is not True:
            raise GatewayRejected(
                "transport_rejected:" + str(payload.get("error_code") or "unknown")
            )
        outcome = payload.get("outcome") or {}
        return {"ok": bool(outcome.get("ok")), "result": outcome.get("result"),
                "error": outcome.get("error"), "server": outcome.get("server") or {},
                "request_id": message_id}

    def reset(self) -> None:
        """Drop and rebuild the socket so a stale frame cannot answer the next command."""
        try:
            self._client.close()
        except Exception:
            pass
        try:
            self._client = self._module.ZmqCommandClient(self._endpoint,
                                                         max_message_bytes=self._max)
        except Exception:
            self._client = None  # a later call reports gateway_link_unavailable

    def close(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None


class _StdlibLink:
    """Fallback link: one length-prefixed JSON frame per loopback connection."""

    name = "stdlib"

    def __init__(self, host: str, port: int, token: str, timeout_ms: int, max_message_bytes: int):
        self._host = host
        self._port = int(port)
        self._token = token
        self._timeout_ms = timeout_ms
        self._max = max_message_bytes

    @property
    def request_timeout_ms(self) -> int:
        return self._timeout_ms

    def call(self, command: str, params: Mapping) -> dict:
        request_id = uuid.uuid4().hex
        request = {"request_id": request_id, "command": command, "params": dict(params),
                   "auth": self._token}
        try:
            connection = socket.create_connection(
                (self._host, self._port), timeout=min(5.0, self._timeout_ms / 1000.0))
        except OSError as exc:
            raise GatewayUnavailable("gateway_unreachable:%s:%d (%s)"
                                     % (self._host, self._port, type(exc).__name__)) from exc
        with connection:
            connection.settimeout(self._timeout_ms / 1000.0)
            try:
                write_frame(connection, request)
                response = read_frame(connection)
            except (socket.timeout, TimeoutError) as exc:
                raise GatewayCommandUncertain("no reply for %s within %dms (request_id=%s)"
                                              % (command, self._timeout_ms, request_id)) from exc
            except Exception as exc:
                raise GatewayUnavailable("gateway_reply_invalid:%s (request_id=%s)"
                                         % (type(exc).__name__, request_id)) from exc
        if not isinstance(response, Mapping):
            raise GatewayUnavailable("gateway_reply_invalid:not_an_object")
        if not response.get("ok") and str(response.get("error")) == "auth_rejected":
            raise GatewayRejected("auth_rejected")
        return {"ok": bool(response.get("ok")), "result": response.get("result"),
                "error": response.get("error"), "server": response.get("server") or {},
                "request_id": str(response.get("request_id") or request_id)}

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class GatewayClient:
    """Provider-shaped client whose session lives inside a `GatewayServer`."""

    def __init__(self, host: str = "127.0.0.1", port: Optional[int] = None,
                 token: Optional[str] = None, *, transport: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS, transport_margin_ms: int = 5_000,
                 embedded_server: Optional[GatewayServer] = None,
                 recv_window_ms: int = 60_000) -> None:
        self.gateway_host = embedded_server.host if embedded_server is not None else host
        self.port = embedded_server.port if embedded_server is not None else port
        token = embedded_server.token if embedded_server is not None else token
        if not self.port or not token:
            raise GatewayError("gateway_endpoint_incomplete")
        if transport is None:
            if embedded_server is not None:
                transport = embedded_server.transport_impl
            else:
                transport = transport_name()
        if transport not in ("zmq", "stdlib"):
            raise GatewayError("transport_unknown:" + str(transport))
        self.timeout = float(timeout)
        self.recv_window_ms = int(recv_window_ms)
        self._timeout_ms = int(self.timeout * 1000) + int(transport_margin_ms)
        self._embedded = embedded_server
        self._closed = False
        link_cls = _ZmqLink if transport == "zmq" else _StdlibLink
        self._link = link_cls(self.gateway_host, self.port, token, self._timeout_ms,
                              max_message_bytes=1_000_000)
        # Direct-client-compatible state read by strategies and the evidence builder.
        self.host = self.gateway_host
        self.server_time_ms = None
        self.time_offset_ms = 0
        self.connect_rtt_ms = None
        self.calls: list = []
        self.frozen = False
        self.frozen_reason = ""
        self.server_facts: dict = {}
        self.transport = "gateway_zmq" if transport == "zmq" else "gateway_stdlib"

    # ----------------------------------------------------------- construction
    @classmethod
    def from_connection_string(cls, value: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                               transport: Optional[str] = None) -> "GatewayClient":
        """Parse ``[zmq|stdlib@]host:port:token`` (the ``BT_CERT_GATEWAY`` format)."""
        text = str(value or "").strip()
        if "@" in text:
            prefix, _, text = text.partition("@")
            prefix = prefix.strip().lower()
            if prefix in ("zmq", "stdlib"):
                transport = prefix
            elif prefix:
                raise GatewayError("connection_string_transport_unknown:" + prefix)
        parts = text.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2]:
            raise GatewayError("connection_string_invalid")
        return cls(parts[0], int(parts[1]), parts[2], transport=transport, timeout=timeout)

    @classmethod
    def embedded(cls, server: GatewayServer, *,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS) -> "GatewayClient":
        """Attach to (and take ownership of) a server, starting it when needed."""
        server.start()
        return cls(embedded_server=server, timeout=timeout)

    # ---------------------------------------------------------------- forward
    def _call(self, command: str, params: Mapping, *, is_write: bool) -> dict:
        if self._closed:
            raise GatewayUnavailable("gateway_closed")
        if is_write and self.frozen:
            raise ClientFrozen("client frozen after unknown write: " + self.frozen_reason)
        started = time.monotonic()
        try:
            response = self._link.call(command, params)
        except Exception as exc:
            self._record(command, params, None, None, exc)
            if is_write:
                self._freeze("%s transport outcome unknown: %s" % (command, type(exc).__name__))
            raise
        duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        self._record(command, params, response, duration_ms, None)
        if response.get("server"):
            self._observe_server(response["server"])
        if not response.get("ok"):
            raise GatewayRejected("%s failed: %s" % (command, response.get("error")))
        return response

    def _freeze(self, reason: str) -> None:
        self.frozen = True
        self.frozen_reason = reason

    def _observe_server(self, facts: Mapping) -> None:
        self.server_facts = dict(facts)
        provider = facts.get("provider") or {}
        if provider.get("frozen") and not self.frozen:
            self._freeze("provider_frozen:" + str(provider.get("frozen_reason") or "")[:200])

    def _record(self, command, params, response, duration_ms, error) -> None:
        entry = {"t_ms": int(time.time() * 1000), "command": command, "params": _redact(params),
                 "request_id": (response or {}).get("request_id"), "duration_ms": duration_ms,
                 "ok": bool(response.get("ok")) if response else False}
        if error is not None:
            entry["error"] = "%s: %s" % (type(error).__name__, error)
        elif response is not None:
            entry["result"] = _result_copy(response.get("result"))
            entry["result_sha256"] = _result_digest(response.get("result"))
        self.calls.append(entry)

    # ------------------------------------------------------------- lifecycle
    def connect(self) -> dict:
        facts = self._call("connect", {}, is_write=False)["result"]
        if not isinstance(facts, Mapping):
            raise GatewayError("connect_result_invalid")
        self.host = facts.get("host", self.host)
        self.server_time_ms = facts.get("server_time_ms")
        self.time_offset_ms = facts.get("time_offset_ms", 0)
        self.connect_rtt_ms = facts.get("rtt_ms")
        return dict(facts)

    def describe(self) -> dict:
        provider = self.server_facts.get("provider") or {}
        return {"transport": self.transport, "gateway_host": self.gateway_host,
                "gateway_port": self.port, "gateway_closed": self._closed,
                "gateway_server": self.server_facts,
                "endpoint": self.server_facts.get("endpoint"),
                "journal": self.server_facts.get("journal"),
                "commands_served": self.server_facts.get("commands_served"),
                "host": self.host, "server_time_ms": self.server_time_ms,
                "time_offset_ms": self.time_offset_ms, "recv_window_ms": self.recv_window_ms,
                "frozen": self.frozen, "frozen_reason": self.frozen_reason,
                "call_count": len(self.calls), "provider_call_count": provider.get("call_count")}

    def close(self):
        if self._embedded is not None:
            self._embedded.stop()
        else:
            self._link.close()
        self._closed = True

    # ----------------------------------------------------------------- reads
    def _read(self, command: str, params: Mapping) -> Any:
        return self._call(command, params, is_write=False)["result"]

    def account_config(self):
        return self._read("account_config", {})

    def balances(self):
        return self._read("balances", {})

    def position_risk(self, symbol=None):
        return self._read("position_risk", _drop_none({"symbol": symbol}))

    def open_orders(self, symbol=None):
        return self._read("open_orders", _drop_none({"symbol": symbol}))

    def filters(self, symbol):
        return self._read("filters", {"symbol": symbol})

    def mark_price(self, symbol):
        return self._read("mark_price", {"symbol": symbol})

    def query_order(self, symbol, *, order_id=None, client_order_id=None):
        params = _order_params(symbol, order_id, client_order_id)
        return self._read("query_order", params)

    # ---------------------------------------------------------------- writes
    def place_order(self, symbol, side, order_type="LIMIT", quantity=None, price=None,
                    position_side=None, time_in_force=None, reduce_only=None,
                    client_order_id=None, close_position=None, working_type=None):
        params = {"symbol": symbol, "side": side, "order_type": order_type}
        params.update(_drop_none({"quantity": quantity, "price": price,
                                  "position_side": position_side,
                                  "time_in_force": time_in_force,
                                  "reduce_only": reduce_only, "close_position": close_position,
                                  "working_type": working_type,
                                  "client_order_id": client_order_id}))
        return self._call("place_order", params, is_write=True)["result"]

    def cancel_order(self, symbol, *, order_id=None, client_order_id=None):
        params = _order_params(symbol, order_id, client_order_id)
        return self._call("cancel_order", params, is_write=True)["result"]

    def server_fact(self, key: str, default=None):
        return self.server_facts.get(key, default)


# ------------------------------------------------------------------ helpers
def _drop_none(params: Mapping) -> dict:
    return {key: value for key, value in params.items() if value is not None}


def _order_params(symbol, order_id, client_order_id) -> dict:
    params = {"symbol": symbol}
    if order_id is not None:
        params["order_id"] = order_id
    if client_order_id is not None:
        params["client_order_id"] = client_order_id
    if "order_id" not in params and "client_order_id" not in params:
        raise ValueError("order identity required")
    return params


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        out = {}
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(p in normalized for p in _SENSITIVE_KEY_PARTS):
                out[key] = "***"
            else:
                out[key] = _redact(nested)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _result_copy(result: Any) -> Any:
    try:
        blob = json.dumps(result, sort_keys=True, default=str)
    except Exception:
        return {"unserializable": type(result).__name__}
    if len(blob) > RESULT_COPY_CHARS:
        return {"truncated": True, "chars": len(blob), "shape": type(result).__name__}
    return json.loads(blob)


def _result_digest(result: Any) -> str:
    try:
        blob = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        blob = repr(result)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()
