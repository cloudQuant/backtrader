"""Localhost-only gateway transport server for the optional-component matrix.

`GatewayServer` owns exactly one provider session (the penetration suite's
`certlib` Binance demo client) and serves a closed command whitelist over a
versioned request/response envelope. The preferred transport is the dev SDK
package `bt_api_transport_zmq` (`ZmqCommandServer` ROUTER + its strict
`WireMessage` envelope); when that package cannot be imported offline the
module falls back to a minimal stdlib TCP + length-prefixed JSON server with
the same envelope semantics. Both bind loopback only.

Security model and its documented limits
----------------------------------------
* Always binds ``127.0.0.1`` on a random per-run port.
* Every request must carry the per-run random token under the payload key
  ``auth`` (``hmac.compare_digest`` before dispatch). The key is ``auth``
  because the transport wire layer rejects secret-shaped names such as
  ``token``; the token is never journaled or echoed.
* The transport's CurveZMQ/ZAP remote client-key ACL is deliberately unused
  (it targets non-loopback endpoints; this server is loopback-only). Bind
  address + shared token separate *processes* only while the token stays
  private: this is **not** an OS-isolation boundary and offers nothing against
  a hostile same-user process able to read the environment.
* `bt_api_gateway`'s durable `GatewayCommandRouter`/`wire_mapping` chain is
  deliberately not wired: it needs receipt digests, expiry and writer
  authority only a real account-owner gateway can mint. Commands are mapped
  here and recorded in a local append-only JSONL journal instead.
* Commands are served serially: one provider session, one serve thread.

Embeddable API: ``GatewayServer(provider=... | config=..., env=...)`` then
``start()`` / ``stop()``; ``port``, ``token``, ``endpoint``,
``connection_string()`` and ``describe()`` are the runner-facing facts. A
standalone server's ``--config`` supplies credentials/environment only: case
policy (write grants, symbol allowlist, notionals) stays with each case's own
``config.yaml`` and the runner's CLI grants.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import socket
import struct
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

DEFAULT_SDK_ROOT = "D:/bt_api_py"
SDK_SOURCE_SUBDIRS = ("bt_api/bt_api_transport_zmq/src", "bt_api/bt_api_gateway/src")
PROTOCOL_TAG = "bt-cert-gateway-v1"
DEFAULT_SCOPE = "cert"
DEFAULT_MAX_MESSAGE_BYTES = 1_000_000
JOURNAL_RESULT_CHARS = 8_192
ERROR_CHARS = 500
_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "credential", "passphrase",
                        "password", "private_key", "secret", "token")
_STRING_PARAMS = ("symbol", "side", "client_order_id", "order_type", "position_side",
                  "time_in_force", "working_type")
_BOOL_PARAMS = ("reduce_only", "close_position")
_NUMBER_PARAMS = ("quantity", "price")
OPTIONAL16_ROOT = Path(__file__).resolve().parents[1]
VENUE_ROOT = OPTIONAL16_ROOT / "binance_penetration"

# command -> (required params, optional params, is_write)
PROVIDER_COMMANDS: dict = {
    "connect": ((), (), False),
    "describe": ((), (), False),
    "account_config": ((), (), False),
    "balances": ((), (), False),
    "position_risk": ((), ("symbol",), False),
    "open_orders": ((), ("symbol",), False),
    "filters": (("symbol",), (), False),
    "mark_price": (("symbol",), (), False),
    "place_order": (("symbol", "side"), ("order_type", "quantity", "price", "position_side",
                                         "time_in_force", "reduce_only", "close_position",
                                         "working_type", "client_order_id"), True),
    "cancel_order": (("symbol",), ("order_id", "client_order_id"), True),
    "query_order": (("symbol",), ("order_id", "client_order_id"), False),
}


class GatewayCommandError(RuntimeError):
    """The command envelope is invalid or the provider cannot serve it."""


def sdk_root() -> Path:
    return Path(os.environ.get("BT_API_PY_ROOT", DEFAULT_SDK_ROOT))


def ensure_import_paths() -> dict:
    """Insert the dev SDK sources and the venue root; returns what was added."""
    added = {"sdk": [], "venue": None}
    for subdir in SDK_SOURCE_SUBDIRS:
        candidate = sdk_root() / subdir
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            added["sdk"].append(str(candidate))
    if VENUE_ROOT.is_dir() and str(VENUE_ROOT) not in sys.path:
        sys.path.insert(0, str(VENUE_ROOT))
        added["venue"] = str(VENUE_ROOT)
    return added


_zmq_cache: dict = {}


def load_transport_package():
    """Import `bt_api_transport_zmq` (installed or dev source) or return None."""
    if "module" not in _zmq_cache:
        module = None
        try:
            import bt_api_transport_zmq as module  # type: ignore
        except Exception:
            ensure_import_paths()
            try:
                import bt_api_transport_zmq as module  # type: ignore
            except Exception:
                module = None
        _zmq_cache["module"] = module
    return _zmq_cache["module"]


def transport_name() -> str:
    return "zmq" if load_transport_package() is not None else "stdlib"


def _pick_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


def _error_text(exc: Any) -> str:
    return ("%s: %s" % (type(exc).__name__, exc))[:ERROR_CHARS]


def _json_bytes(value: Any) -> int:
    """Serialized size in bytes, or a sentinel making an unserializable value fail closed."""
    try:
        return len(json.dumps(value, sort_keys=True, allow_nan=False, default=str).encode("utf-8"))
    except Exception:
        return 2 ** 31


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
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "...(%d)" % len(value)
    return value


def _journal_result(result: Any) -> Any:
    if result is None:
        return None
    redacted = _redact(result)
    size = _json_bytes(redacted)
    if size > JOURNAL_RESULT_CHARS:
        return {"truncated": True, "shape": type(redacted).__name__, "json_chars": size}
    return redacted


class CommandJournal:
    """Append-only JSONL journal; one fsynced line per command or lifecycle event."""

    def __init__(self, directory: Optional[os.PathLike] = None) -> None:
        if directory is None:
            directory = tempfile.mkdtemp(prefix="bt-cert-gateway-journal-")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "commands.jsonl"
        self._handle = open(self.path, "a", encoding="utf-8")
        self._lock = threading.Lock()
        self.lines = 0

    def append(self, entry: Mapping[str, Any]) -> dict:
        record = {"protocol": PROTOCOL_TAG, "utc_ms": int(time.time() * 1000), **dict(entry)}
        with self._lock:
            if self._handle.closed:  # shutdown race: never raise from the journal
                return record
            self._handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self.lines += 1
        return record

    def close(self) -> None:
        with self._lock:
            if not self._handle.closed:
                self._handle.close()


class GatewayServer:
    """Loopback gateway that owns one provider session and serves commands."""

    def __init__(self, *, provider: Any = None, provider_factory: Optional[Callable] = None,
                 config: Optional[Mapping] = None, env: Optional[Mapping] = None,
                 journal_dir: Optional[os.PathLike] = None,
                 journal: Optional[CommandJournal] = None,
                 host: str = "127.0.0.1", port: int = 0, token: Optional[str] = None,
                 name: str = "optional16",
                 max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES) -> None:
        if provider is None and provider_factory is None:
            if config is None or env is None:
                raise GatewayCommandError("provider_or_config_required")
            provider_factory = build_direct_provider
        if host not in ("127.0.0.1", "localhost"):
            raise GatewayCommandError("loopback_bind_required:" + str(host))
        self.host, self.name = "127.0.0.1", name
        self.config, self.env = dict(config or {}), dict(env or {})
        self._provider_factory, self._provider = provider_factory, provider
        self._journal, self._journal_dir = journal, journal_dir
        self._requested_port = int(port)
        self._token = token or secrets.token_hex(24)
        self.port: Optional[int] = None
        self.max_message_bytes = int(max_message_bytes)
        self._transport = None
        self._transport_name = transport_name()
        self._thread: Optional[threading.Thread] = None
        self._stop: Optional[threading.Event] = None
        self.commands_served = 0
        self.started = False

    # ------------------------------------------------------------- lifecycle
    @property
    def token(self) -> str:
        return self._token

    @property
    def transport_impl(self) -> str:
        """``"zmq"`` (bt_api_transport_zmq) or ``"stdlib"`` (documented fallback)."""
        return self._transport_name

    @property
    def endpoint(self) -> Optional[str]:
        return self._transport.endpoint if self._transport is not None else None

    def connection_string(self) -> str:
        if self.port is None:
            raise GatewayCommandError("server_not_started")
        return "%s@%s:%d:%s" % (self._transport_name, self.host, self.port, self._token)

    def start(self) -> "GatewayServer":
        if self.started:
            return self
        if self._provider is None:
            self._provider = self._provider_factory(self.config, self.env)
        if self._journal is None:
            self._journal = CommandJournal(self._journal_dir)
        self._stop = threading.Event()
        self._transport = self._open_transport()
        self.port = self._transport.port
        self._thread = threading.Thread(target=self._run, name="bt-cert-gateway", daemon=True)
        self._thread.start()
        if self._journal.lines == 0:
            self._journal.append({"event": "server_start", "transport": self._transport_name,
                                  "endpoint": self.endpoint, "port": self.port,
                                  "pid": os.getpid(), "provider": self._provider_facts()})
        self.started = True
        return self

    def stop(self, timeout: float = 5.0) -> None:
        if not self.started:
            return
        self.started = False
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        close = getattr(self._provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:  # shutdown must never be masked by a provider error
                self._journal.append({"event": "provider_close_error", "error": _error_text(exc)})
        if self._journal is not None:
            self._journal.append({"event": "server_stop", "port": self.port, "pid": os.getpid()})
            self._journal.close()

    def __enter__(self) -> "GatewayServer":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    def _open_transport(self):
        module = load_transport_package()
        if module is not None:
            last = None
            for _attempt in range(5):
                port = self._requested_port or _pick_free_port(self.host)
                try:
                    return _ZmqTransport(module, self.host, port, self._token, self,
                                         self.max_message_bytes)
                except Exception as exc:  # port race -> retry; an explicit port surfaces the error
                    last = exc
                    if self._requested_port:
                        break
            raise GatewayCommandError("zmq_bind_failed:" + _error_text(last))
        return _StdlibTransport(self.host, self._requested_port or _pick_free_port(self.host), self)

    def _run(self) -> None:
        while self._stop is not None and not self._stop.is_set():
            try:
                self._transport.poll_once(100)
            except Exception as exc:
                self._journal.append({"event": "serve_error", "error": _error_text(exc)})
                time.sleep(0.05)

    # ---------------------------------------------------------------- facts
    def describe(self) -> dict:
        return {"name": self.name,
                "transport": "gateway_zmq" if self._transport_name == "zmq" else "gateway_stdlib",
                "transport_impl": self._transport_name, "endpoint": self.endpoint,
                "host": self.host, "port": self.port, "pid": os.getpid(),
                "journal": str(self._journal.path) if self._journal is not None else None,
                "journal_lines": self._journal.lines if self._journal is not None else 0,
                "commands_served": self.commands_served, "started": self.started,
                "provider": self._provider_facts()}

    def _provider_facts(self) -> dict:
        describe = getattr(self._provider, "describe", None)
        facts: dict = {}
        if callable(describe):
            try:
                facts = dict(describe())
            except Exception as exc:
                facts = {"describe_error": _error_text(exc)}
        facts["frozen"] = bool(getattr(self._provider, "frozen", False))
        return facts

    # -------------------------------------------------------------- dispatch
    def process(self, payload: Mapping) -> dict:
        """Validate, journal and execute one command; never raises."""
        payload = payload if isinstance(payload, Mapping) else {}
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        params = payload.get("params") or {}
        started = time.monotonic()
        try:
            outcome = {"ok": True, "result": self._invoke(payload.get("command"), params)}
        except Exception as exc:
            outcome = {"ok": False, "error": _error_text(exc)}
        outcome["server"] = self.describe()
        outcome = self._ensure_encodable(outcome)
        self._journal.append({"event": "command", "request_id": request_id,
                              "command": payload.get("command"), "params": _redact(params),
                              "ok": outcome.get("ok"),
                              "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
                              "result": _journal_result(outcome.get("result")),
                              "error": outcome.get("error")})
        self.commands_served += 1
        return {"request_id": request_id, "ok": bool(outcome.get("ok")),
                "result": outcome.get("result"), "error": outcome.get("error"),
                "server": outcome["server"]}

    def reject_auth(self, peer: str) -> None:
        """Journal a rejected client before the transport answers it."""
        self._journal.append({"event": "auth_rejected", "peer": str(peer)[:64], "ok": False})

    def _invoke(self, command: Any, params: Any):
        spec = PROVIDER_COMMANDS.get(command)
        if spec is None:
            raise GatewayCommandError("unknown_command:" + str(command))
        if not isinstance(params, Mapping):
            raise GatewayCommandError("params_invalid")
        required, optional, _is_write = spec
        unknown = sorted(str(key) for key in params if key not in set(required) | set(optional))
        if unknown:
            raise GatewayCommandError("unknown_param:" + ",".join(unknown))
        missing = [key for key in required if params.get(key) is None]
        if missing:
            raise GatewayCommandError("missing_param:" + ",".join(missing))
        kwargs = {key: params[key] for key in tuple(required) + tuple(optional)
                  if params.get(key) is not None}
        _validate_params(kwargs)
        if command in ("cancel_order", "query_order") and kwargs.get("order_id") is None \
                and not kwargs.get("client_order_id"):
            raise GatewayCommandError("order_identity_required")
        method = getattr(self._provider, command, None)
        if not callable(method):
            raise GatewayCommandError("provider_command_unavailable:" + str(command))
        if command in ("position_risk", "open_orders") and "symbol" not in kwargs:
            return method()
        return method(**kwargs)

    def _ensure_encodable(self, outcome: dict) -> dict:
        """Fail closed when the outcome cannot enter the transport envelope."""
        module = load_transport_package()
        try:
            if module is not None:
                probe = module.WireMessage(message_id="encode-probe",
                                           channel=module.WireChannel.RESPONSE, scope=DEFAULT_SCOPE,
                                           sequence=0, sent_at=time.time(),
                                           payload={"accepted": True, "outcome": outcome,
                                                    "status": "handled"})
                module.encode_message(probe, max_message_bytes=self.max_message_bytes)
            elif _json_bytes(outcome) > self.max_message_bytes:
                raise ValueError("too large")
        except Exception as exc:
            return {"ok": False, "error": "outcome_not_wire_safe:" + type(exc).__name__,
                    "server": outcome.get("server") or self.describe()}
        return outcome


def _validate_params(kwargs: Mapping) -> None:
    for key in _STRING_PARAMS:
        value = kwargs.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise GatewayCommandError("param_not_string:" + key)
    for key in _BOOL_PARAMS:
        value = kwargs.get(key)
        if value is not None and not isinstance(value, bool):
            raise GatewayCommandError("param_not_bool:" + key)
    for key in _NUMBER_PARAMS:
        value = kwargs.get(key)
        if value is not None and (isinstance(value, bool)
                                  or not isinstance(value, (str, int, float))):
            raise GatewayCommandError("param_not_numeric:" + key)
    order_id = kwargs.get("order_id")
    if order_id is not None:
        try:
            kwargs["order_id"] = int(order_id)
        except (TypeError, ValueError) as exc:
            raise GatewayCommandError("param_not_integer:order_id") from exc


class _ZmqTransport:
    """Adapter around ``bt_api_transport_zmq.ZmqCommandServer`` (local bind)."""

    def __init__(self, module, host: str, port: int, token: str, owner: GatewayServer,
                 max_message_bytes: int) -> None:
        self._module, self._token, self._owner = module, token, owner
        self.endpoint = "tcp://%s:%d" % (host, port)
        self.port = port
        self._server = module.ZmqCommandServer(self.endpoint, self._authenticate, self._handle,
                                               bind=True, high_water_mark=512,
                                               max_message_bytes=max_message_bytes)

    def _authenticate(self, peer_identity, message):
        auth = message.payload.get("auth")
        if not isinstance(auth, str) or not hmac.compare_digest(auth, self._token):
            self._owner.reject_auth(bytes(peer_identity).hex()[:32])
            raise self._module.TransportSecurityError("gateway client auth rejected")
        return {"principal": "local-cert-client", "peer": bytes(peer_identity).hex()[:32]}

    def _handle(self, _principal, message):
        return self._owner.process(message.payload)

    def poll_once(self, timeout_ms: int) -> bool:
        return bool(self._server.serve_once(timeout_ms))

    def close(self) -> None:
        self._server.close()


class _StdlibTransport:
    """Fallback: length-prefixed JSON frames over one loopback TCP listener."""

    def __init__(self, host: str, port: int, owner: GatewayServer) -> None:
        self._owner = owner
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(8)
        self._sock.settimeout(0.1)
        self.port = int(self._sock.getsockname()[1])
        self.endpoint = "tcp://%s:%d" % (host, self.port)

    def poll_once(self, timeout_ms: int) -> bool:
        self._sock.settimeout(max(timeout_ms, 1) / 1000.0)
        try:
            conn, peer = self._sock.accept()
        except (socket.timeout, TimeoutError):
            return False
        with conn:
            conn.settimeout(30.0)
            try:
                request = read_frame(conn)
            except Exception:
                return True
            if not isinstance(request, Mapping):
                response = {"request_id": "", "ok": False, "error": "request_invalid_format"}
            elif not hmac.compare_digest(str(request.get("auth") or ""), self._owner.token):
                self._owner.reject_auth("%s:%d" % (peer[0], peer[1]))
                response = {"request_id": "", "ok": False, "error": "auth_rejected"}
            else:
                response = self._owner.process(request)
            try:
                write_frame(conn, response)
            except Exception:
                pass
        return True

    def close(self) -> None:
        self._sock.close()


def read_frame(sock: socket.socket):
    (length,) = struct.unpack("!I", _recv_exact(sock, 4))
    if length > 64 * 1024 * 1024:
        raise GatewayCommandError("frame_too_large")
    return json.loads(_recv_exact(sock, length).decode("utf-8"))


def write_frame(sock: socket.socket, payload: Mapping) -> None:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    sock.sendall(struct.pack("!I", len(blob)) + blob)


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks, remaining = [], count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise GatewayCommandError("connection_closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def build_direct_provider(config: Mapping, env: Mapping):
    """Construct the suite's direct provider session (a fresh owned session)."""
    ensure_import_paths()
    from certlib import make_client  # local import: avoids an import cycle

    return make_client(dict(config), dict(env),
                       {"transport": "direct", "execution": False, "risk": False, "monitor": False})


def main(argv=None) -> int:
    """Run a standalone gateway server and print its connection facts."""
    parser = argparse.ArgumentParser(prog="optional16-gateway-server")
    parser.add_argument("--config", required=True, help="case config.yaml the server owns")
    parser.add_argument("--journal-dir", default=None, help="directory for commands.jsonl")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    ensure_import_paths()
    import yaml  # type: ignore
    from certlib import envfile

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    credentials = config.get("credentials", {})
    names = [n for n in (credentials.get("api_key_env"), credentials.get("secret_env")) if n]
    env_values, missing = envfile.load_env(names)
    if missing:
        print(json.dumps({"status": "BLOCKED", "reason": "credential_env_missing"}))
        return 2
    server = GatewayServer(config=config, env=env_values, journal_dir=args.journal_dir,
                           port=args.port)
    server.start()
    print(json.dumps({"status": "READY", "host": server.host, "port": server.port,
                      "token": server.token, "transport": server.transport_impl,
                      "endpoint": server.endpoint, "journal": str(server._journal.path),
                      "connection_string": server.connection_string()}, sort_keys=True), flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
