"""Credential-free fakes for the source-bound forceOrders GET extension."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import ssl as ssl
import socket
import sys
import time
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[3]
OWNER_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_root_protected_owner_r1.py"
)
EXTENSION_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_force_orders_transport_r9.py"
)
DRIVER_PATH = ROOT / "scripts" / "iteration41_binance_th01_account_window_candidate_r2.py"
ROOT_WRAPPER_PATH = ROOT / "scripts" / "iteration41_binance_th01_root_account_window_call_r1.py"
ACCOUNT_WINDOW_CANDIDATE_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_account_window_candidate_r2.py"
)
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
ACCOUNT_WINDOW_CANDIDATE_SHA256 = "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63"
EXTENSION_MODULE_NAME = (
    "examples.000_live_certification.binance_penetration._certification."
    "th01_force_orders_transport_r9"
)
extension = ModuleType(EXTENSION_MODULE_NAME)
extension.__file__ = str(EXTENSION_PATH)
extension.__package__ = EXTENSION_MODULE_NAME.rsplit(".", 1)[0]
sys.modules[EXTENSION_MODULE_NAME] = extension
exec(
    compile(EXTENSION_PATH.read_bytes(), str(EXTENSION_PATH), "exec", dont_inherit=True),
    extension.__dict__,
)
_ROOT_WRAPPERS_BY_OWNER_ID = {}


def _load_root_wrapper(monkeypatch) -> ModuleType:
    name = "_iteration41_binance_th01_root_attempt_wrapper_" + uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT_WRAPPER_PATH)
    assert spec is not None and spec.loader is not None
    module = ModuleType(name)
    module.__file__ = str(ROOT_WRAPPER_PATH)
    module.__package__ = ""
    module.__spec__ = spec
    module.__loader__ = spec.loader
    monkeypatch.setitem(sys.modules, name, module)
    raw = ROOT_WRAPPER_PATH.read_bytes()
    module.__th01_held_source_sha256__ = hashlib.sha256(raw).hexdigest()
    exec(compile(raw, str(ROOT_WRAPPER_PATH), "exec", dont_inherit=True), module.__dict__)
    return module


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("network access is forbidden in this source-fake suite")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _load_owner(
    monkeypatch,
    *,
    install: bool = True,
    module_name: str = "__main__",
    package: str | None = "examples.000_live_certification.binance_penetration._certification",
) -> ModuleType:
    root_wrapper_module = _load_root_wrapper(monkeypatch)
    raw = OWNER_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OWNER_SHA256
    owner = ModuleType(module_name)
    owner.__package__ = package
    owner.__file__ = str(DRIVER_PATH)
    owner.OWNER_PATH = OWNER_PATH
    owner.OWNER_SHA256 = OWNER_SHA256
    monkeypatch.setitem(sys.modules, "__main__", owner)
    owner.__file__ = str(OWNER_PATH)
    exec(compile(raw, str(OWNER_PATH), "exec", dont_inherit=True), owner.__dict__)
    owner.__file__ = str(DRIVER_PATH)
    owner.__th01_verified_owner_source_sha256__ = OWNER_SHA256
    owner.__th01_verified_owner_source_path__ = str(OWNER_PATH)
    candidate_name = "_iteration41_th01_account_window_candidate_r2_" + uuid4().hex
    candidate_raw = ACCOUNT_WINDOW_CANDIDATE_PATH.read_bytes()
    assert hashlib.sha256(candidate_raw).hexdigest() == ACCOUNT_WINDOW_CANDIDATE_SHA256
    candidate = ModuleType(candidate_name)
    candidate.__file__ = str(ACCOUNT_WINDOW_CANDIDATE_PATH)
    candidate.__package__ = ""
    candidate.__th01_verified_candidate_source_sha256__ = ACCOUNT_WINDOW_CANDIDATE_SHA256
    monkeypatch.setitem(sys.modules, candidate_name, candidate)
    exec(
        compile(
            candidate_raw,
            str(ACCOUNT_WINDOW_CANDIDATE_PATH),
            "exec",
            dont_inherit=True,
        ),
        candidate.__dict__,
    )
    owner._CANDIDATE_MODULE = candidate
    _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)] = root_wrapper_module
    if not install:
        return owner
    installed = extension.install_force_orders_extension(owner, root_wrapper_module)
    assert installed is owner
    assert (
        extension._read_extension_source()[1] == owner._ROOT_TH01_FORCE_ORDERS_EXTENSION_R9_SHA256
    )
    held_callbacks = extension.capture_force_orders_callback_bindings(owner)
    assert extension.verify_force_orders_callback_bindings(owner, held_callbacks) is True
    assert owner.verify_force_orders_owner_binding(owner) is True
    return owner


class _FakeDirectory:
    def __init__(self, path: Path):
        self.path = path
        self.records = []

    def write_json(self, name, document):
        self.records.append((name, document))


class _FakeSock:
    def settimeout(self, _timeout):
        return None


class _FakeResponse:
    def __init__(self, body: bytes):
        self.status = 200
        self.body = body
        self.read = False

    def getheader(self, name, default=None):
        headers = {
            "Content-Encoding": "identity",
            "Content-Length": str(len(self.body)),
        }
        return headers.get(name, default)

    def read1(self, _size):
        if self.read:
            return b""
        self.read = True
        return self.body


class _FakePipeState:
    def __init__(self):
        self.frames = []
        self.writer_closed = False


class _FakePipeEnd:
    def __init__(self, state: _FakePipeState, *, parent: bool):
        self.state = state
        self.parent = parent
        self.closed = False

    def send(self, frame):
        assert not self.parent
        self.state.frames.append(frame)

    def poll(self, _timeout):
        assert self.parent
        return bool(self.state.frames) or self.state.writer_closed

    def recv(self):
        assert self.parent
        if self.state.frames:
            return self.state.frames.pop(0)
        if self.state.writer_closed:
            raise EOFError
        raise OSError("fake pipe has no frame")

    def close(self):
        self.closed = True
        if not self.parent:
            self.state.writer_closed = True


class _FakeProcess:
    def __init__(self, target, args, **_kwargs):
        self.target = target
        self.args = args
        self.exitcode = None
        self.started = False
        self.closed = False
        self.terminated = False

    def start(self):
        self.started = True
        self.target(*self.args)
        self.exitcode = 0

    def is_alive(self):
        return False

    def join(self, timeout=None):
        assert timeout is None or timeout >= 0

    def close(self):
        self.closed = True

    def terminate(self):
        self.terminated = True


class _FakeSpawnContext:
    def __init__(self):
        self.processes = []
        self.pipe_states = []

    def Pipe(self, duplex=False):
        assert duplex is False
        state = _FakePipeState()
        self.pipe_states.append(state)
        return _FakePipeEnd(state, parent=True), _FakePipeEnd(state, parent=False)

    def Process(self, target, args, **kwargs):
        process = _FakeProcess(target, args, **kwargs)
        self.processes.append(process)
        return process


def _make_auth(owner, monkeypatch, *, rows=None):
    invocation = uuid4().hex
    evidence_window = "th01-window:" + invocation
    start_ms = int(time.time() * 1000) - 20_000
    directory = _FakeDirectory(Path("C:/fake/bt-iteration41-th01-" + invocation))
    helper = SimpleNamespace(PrivateArtifactDirectory=_FakeDirectory)
    monkeypatch.setattr(owner, "_private_helper", lambda: helper)
    writer = owner.RootTH01ProtectedWriterV1(
        invocation_id=invocation,
        _directory=directory,
        database_path=directory.path / owner.MONITOR_DATABASE_NAME,
        monitor_log_path=directory.path / owner.TRADELOGGER_NAME,
        _next_sequence=[0],
        _seal=owner._ROOT_TH01_PROTECTED_WRITER_SEAL,
    )
    credential_context = owner._RootTH01CredentialContextV1(
        source_digest="c" * 64,
        _account_binding_ref="b" * 64,
        _api_key="fake-api-key-1234567890",
        _secret="fake-secret-abcdefghijkl",
        _seal=owner._ROOT_TH01_CREDENTIAL_CONTEXT_SEAL,
    )
    auth = owner._make_root_account_window_auth(
        credential_context,
        writer,
        invocation,
        evidence_window,
        start_ms,
    )
    root_wrapper_module = _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)]
    attempt_ledger = root_wrapper_module.RootForceOrdersAttemptLedgerV1(auth)
    attempt_ledger.set_phase("before_cleanup")
    capability = owner.FixedForceOrdersGetV1(auth, attempt_ledger)
    return auth, capability, directory, start_ms


def _call_force_orders(owner, auth, capability, start_ms: int, end_ms: int):
    ledger = capability._root_attempt_ledger
    prior = ledger.snapshot()
    ticket = ledger.reserve(auth, start_ms, end_ms)
    assert ledger.verify_transition(prior, ticket, "reserved") is True
    reserved = ledger.snapshot()
    call_returned = False
    outcome = "interrupted"
    page = None
    try:
        assert ledger.verify(ticket, auth, start_ms, end_ms, expected_state="reserved") is True
        page = capability.force_orders(start_ms, end_ms, root_attempt=ticket)
        call_returned = True
        outcome = "page_received"
    except Exception:
        outcome = "blocked"
        raise
    finally:
        dispatch_started = ledger.verify_transition(reserved, ticket, "dispatching")
        still_reserved = ledger.verify_snapshot(reserved)
        assert dispatch_started or still_reserved
        if call_returned:
            assert dispatch_started
        ledger.finish(ticket, outcome)
        assert ledger.verify_transition(prior, ticket, "terminal", outcome) is True
        assert ledger.verify_snapshot(ledger.snapshot()) is True
    assert owner.verify_force_orders_page(auth, page, start_ms, end_ms, root_attempt=ticket) is True
    return page, ticket


def _install_fake_transport(owner, monkeypatch, body: bytes):
    context = _FakeSpawnContext()
    requests = []

    class FakeHTTPSConnection:
        def __init__(self, host, *, timeout, context=None):
            assert host == "demo-fapi.binance.com"
            assert 0 < timeout <= 8.0
            assert context == "fake-tls-context"
            self.host = host
            self.timeout = timeout
            self.context = context
            self.sock = _FakeSock()
            self.closed = False

        def connect(self):
            return None

        def request(self, method, path, *, headers):
            requests.append((self.host, method, path, dict(headers)))

        def getresponse(self):
            return _FakeResponse(body)

        def close(self):
            self.closed = True

    monkeypatch.setattr(owner.multiprocessing, "get_context", lambda name: _context(name))
    monkeypatch.setattr(owner.http.client, "HTTPSConnection", FakeHTTPSConnection)
    monkeypatch.setattr(owner.ssl, "create_default_context", lambda: "fake-tls-context")

    def _context(name):
        assert name == "spawn"
        return context

    def wait_for_fake_eof(connections, *, timeout):
        assert timeout == 0.1
        return list(connections) if context.pipe_states[-1].writer_closed else []

    monkeypatch.setattr(owner, "wait_for_connections", wait_for_fake_eof)
    return context, requests


def _force_row(order_id: int, when_ms: int):
    return {
        "orderId": order_id,
        "symbol": "BTCUSDT",
        "side": "SELL",
        "positionSide": "BOTH",
        "status": "FILLED",
        "time": when_ms,
        "origQty": "0.1",
        "executedQty": "0.1",
        "averagePrice": "20.0",
        "type": "LIQUIDATION",
    }


def test_force_orders_dispatches_one_signed_get_through_fake_http_pipe_and_shared_reader(
    monkeypatch,
):
    owner = _load_owner(monkeypatch)
    rows = [_force_row(index + 1, int(time.time() * 1000) - 500) for index in range(100)]
    body = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("ascii")
    context, requests = _install_fake_transport(owner, monkeypatch, body)
    auth, capability, directory, start_ms = _make_auth(owner, monkeypatch)
    end_ms = int(time.time() * 1000) - 1

    assert owner.verify_force_orders_reader_binding(owner, auth, capability) is True
    page, ticket = _call_force_orders(owner, auth, capability, start_ms, end_ms)

    assert type(page) is owner._RootTH01AccountWindowPageV1
    assert page.resource == "force_orders_in_window"
    assert page.row_count == 100
    assert page.row_limit == 100
    assert page.terminal_proof == "interval_saturated"
    assert page.has_more is False
    assert page.request_cursor is None
    assert page.next_cursor is None
    assert owner.verify_force_orders_page(auth, page, start_ms, end_ms, root_attempt=ticket) is True
    assert owner.verify_force_orders_reader_binding(owner, auth, capability) is True
    assert auth._reader._request_count[0] == 1
    assert auth._reader._row_count[0] == 100
    assert auth._reader._response_bytes[0] == len(body)
    assert auth._reader._first_request_ms[0] is not None
    assert auth._reader._last_response_ms[0] is not None
    assert auth._reader._capture_deadline_monotonic[0] is not None
    assert len(directory.records) == 1
    assert len(requests) == 1
    assert context.processes[0].started is True
    assert context.processes[0].closed is True
    assert context.processes[0].terminated is False

    host, method, path, headers = requests[0]
    parsed = urlsplit(path)
    query = {name: values[0] for name, values in parse_qs(parsed.query).items()}
    assert host == "demo-fapi.binance.com"
    assert method == "GET"
    assert parsed.path == "/fapi/v1/forceOrders"
    assert set(query) == {"startTime", "endTime", "limit", "recvWindow", "timestamp", "signature"}
    assert int(query["startTime"]) == start_ms
    assert int(query["endTime"]) == end_ms
    assert query["limit"] == "100"
    assert query["recvWindow"] == "5000"
    assert len(query["signature"]) == 64
    assert headers["X-MBX-APIKEY"] == "fake-api-key-1234567890"
    private_query = dict(directory.records[0][1]["document"]["unsigned_query"])
    assert set(private_query) == {"startTime", "endTime", "limit", "recvWindow", "timestamp"}


def test_cold_wrapper_session_and_postflight_use_three_argument_reader_binding(monkeypatch):
    owner = _load_owner(monkeypatch, install=False)
    root_wrapper = _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)]

    def install_and_capture(owner_arg, force_module, wrapper_module):
        assert owner_arg is owner
        assert force_module is extension
        assert wrapper_module is root_wrapper
        assert extension.install_force_orders_extension(owner_arg, wrapper_module) is owner
        callback_bindings = extension.capture_force_orders_callback_bindings(owner)
        capture = extension.capture_force_orders_callback_bindings
        verify = extension.verify_force_orders_callback_bindings
        api_snapshot = (
            force_module,
            root_wrapper._module_binding_snapshot(
                force_module,
                mutable_globals=frozenset(),
            ),
            capture,
            root_wrapper._function_binding_shape(capture),
            verify,
            root_wrapper._function_binding_shape(verify),
        )
        return owner.FixedForceOrdersGetV1, callback_bindings, api_snapshot

    adapter = ModuleType("_iteration41_force_orders_sourcefake_adapter")
    adapter.root_th01_read_action = lambda auth, **kwargs: SimpleNamespace(
        auth=auth,
        kwargs=kwargs,
    )
    source_modules = {"runner": ModuleType("_iteration41_force_orders_sourcefake_runner")}
    held_sources = {}

    monkeypatch.setattr(root_wrapper, "FORCE_EXTENSION_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(root_wrapper, "_verify_cuv2_bindings", lambda _module: None)
    monkeypatch.setattr(root_wrapper, "_verify_cuv2_scope", lambda *_args: held_sources)
    monkeypatch.setattr(root_wrapper, "_verify_wrapper_namespace", lambda *_args: root_wrapper)
    monkeypatch.setattr(root_wrapper, "_verify_runtime", lambda *_args: None)
    monkeypatch.setattr(
        root_wrapper,
        "_verify_owner_namespace",
        lambda *_args, **_kwargs: (owner, owner._CANDIDATE_MODULE),
    )
    monkeypatch.setattr(
        root_wrapper,
        "_load_and_verify_source_dependencies",
        lambda **_kwargs: (ModuleType("_readonly_fake"), adapter, extension),
    )
    monkeypatch.setattr(root_wrapper, "_install_and_capture_force_extension", install_and_capture)
    monkeypatch.setattr(root_wrapper, "_r3_source_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(root_wrapper, "_all_expected_pins", lambda *_args: {})
    monkeypatch.setattr(root_wrapper, "_verify_source_map", lambda *_args: None)
    monkeypatch.setattr(
        root_wrapper,
        "_verify_loaded_source_package",
        lambda *_args: source_modules,
    )
    monkeypatch.setattr(
        root_wrapper,
        "_capture_source_binding_snapshots",
        lambda **_kwargs: (),
    )
    monkeypatch.setattr(root_wrapper, "_verify_source_binding_snapshots", lambda *_args: None)
    monkeypatch.setattr(root_wrapper, "_pre_action_mutable_globals", lambda *_args: {})
    monkeypatch.setattr(
        root_wrapper,
        "_verified_active_trade_logger_config_snapshot_id",
        lambda *_args: "sourcefake-config-snapshot",
    )
    monkeypatch.setattr(
        root_wrapper,
        "_expected_owner_code",
        lambda *_args: {"_root_fixed_signed_get_worker": ()},
    )

    credential_context = owner._RootTH01CredentialContextV1(
        source_digest="c" * 64,
        _account_binding_ref="b" * 64,
        _api_key="fake-api-key-1234567890",
        _secret="fake-secret-abcdefghijkl",
        _seal=owner._ROOT_TH01_CREDENTIAL_CONTEXT_SEAL,
    )
    helper = SimpleNamespace(PrivateArtifactDirectory=_FakeDirectory)
    monkeypatch.setattr(owner, "_private_helper", lambda: helper)
    monkeypatch.setattr(owner, "_root_th01_credential_context", lambda _path: credential_context)

    def fake_writer(invocation_id):
        directory = _FakeDirectory(Path("C:/fake/bt-iteration41-th01-" + invocation_id))
        return owner.RootTH01ProtectedWriterV1(
            invocation_id=invocation_id,
            _directory=directory,
            database_path=directory.path / owner.MONITOR_DATABASE_NAME,
            monitor_log_path=directory.path / owner.TRADELOGGER_NAME,
            _next_sequence=[0],
            _seal=owner._ROOT_TH01_PROTECTED_WRITER_SEAL,
        )

    monkeypatch.setattr(owner, "create_root_protected_writer", fake_writer)

    def sourcefake_collect_one(self, action, phase):
        assert action is self.action
        assert phase == "baseline"
        self._verify_force_extension_state()
        raise root_wrapper.RootAccountWindowCallBlocked("sourcefake_stop")

    monkeypatch.setattr(
        root_wrapper.RootSnapshotBackendHookV1,
        "_collect_one",
        sourcefake_collect_one,
    )

    result = root_wrapper.run_root_cold_account_window(
        ModuleType("_sourcefake_cuv2"),
        lease=object(),
        yielded=object(),
        public_pins={},
        software_pins={},
        active_trade_logger=object(),
        root=ROOT,
    )

    assert result.status == "BLOCKED_ACCOUNT_SNAPSHOT"
    assert result.first_failure == "sourcefake_stop"
    assert result.source_preflight_complete is True
    assert result.source_postflight_complete is True
    assert result.force_orders_bound is True
    assert result.request_count == 0
    assert result.worker_lifecycle_complete is False
    assert result.root_host_retention_required is True
    assert len(owner._ACTIVE_ROOT_ACCOUNT_AUTH) == 1
    assert len(root_wrapper._ACTIVE_SESSIONS) == 1
    retained = root_wrapper._ACTIVE_SESSIONS.pop()
    owner._ACTIVE_ROOT_ACCOUNT_AUTH.clear()
    assert retained.auth is result.session.auth


def test_force_orders_short_page_is_one_shot_and_page_verifier_rejects_rebinding(monkeypatch):
    owner = _load_owner(monkeypatch)
    now_ms = int(time.time() * 1000)
    body = json.dumps([_force_row(7, now_ms - 500)], separators=(",", ":")).encode("ascii")
    _context, requests = _install_fake_transport(owner, monkeypatch, body)
    auth, capability, _directory, start_ms = _make_auth(owner, monkeypatch)
    end_ms = int(time.time() * 1000) - 1

    page, ticket = _call_force_orders(owner, auth, capability, start_ms, end_ms)
    assert page.row_count == 1
    assert page.terminal_proof == "short_page"
    assert owner.verify_force_orders_page(auth, page, start_ms, end_ms, root_attempt=ticket) is True
    assert (
        owner.verify_force_orders_page(auth, page, start_ms, end_ms - 1, root_attempt=ticket)
        is False
    )
    assert (
        owner.verify_force_orders_page(
            auth,
            replace(page, _account_binding_ref="d" * 64),
            start_ms,
            end_ms,
            root_attempt=ticket,
        )
        is False
    )
    assert (
        owner.verify_force_orders_page(
            auth,
            replace(page, rows=()),
            start_ms,
            end_ms,
            root_attempt=ticket,
        )
        is False
    )
    assert (
        owner.verify_force_orders_page(
            auth,
            replace(page, request_ref="forged-request-ref"),
            start_ms,
            end_ms,
            root_attempt=ticket,
        )
        is False
    )

    before = auth._reader._request_count[0]
    with pytest.raises(owner.RootTH01AccountWindowBlocked) as exc:
        capability.force_orders(start_ms, end_ms, root_attempt=ticket)
    assert exc.value.code == "force_orders_attempt_ledger_invalid"
    assert auth._reader._request_count[0] == before
    assert len(requests) == 1


def test_root_attempt_terminal_blocks_retry_after_reader_progress_erasure(monkeypatch):
    owner = _load_owner(monkeypatch)
    held_callbacks = extension.capture_force_orders_callback_bindings(owner)
    now_ms = int(time.time() * 1000)
    rows = [_force_row(index + 1, now_ms - 500) for index in range(1000)]
    body = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("ascii")
    context, requests = _install_fake_transport(owner, monkeypatch, body)
    auth, capability, directory, start_ms = _make_auth(owner, monkeypatch)
    end_ms = int(time.time() * 1000) - 1

    ledger = capability._root_attempt_ledger
    prior = ledger.snapshot()
    ticket = ledger.reserve(auth, start_ms, end_ms)
    assert ledger.verify_transition(prior, ticket, "reserved") is True
    reserved = ledger.snapshot()
    with pytest.raises(owner.RootTH01AccountWindowBlocked) as exc:
        try:
            capability.force_orders(start_ms, end_ms, root_attempt=ticket)
        finally:
            assert ledger.verify_transition(reserved, ticket, "dispatching") is True
            ledger.finish(ticket, "blocked")
            assert ledger.verify_transition(prior, ticket, "terminal", "blocked") is True
    assert exc.value.code == "force_orders_response_overbound"
    assert len(requests) == 1
    assert len(directory.records) == 1
    assert auth._reader._request_count[0] == 1
    assert auth._reader._row_count[0] == 1000
    assert context.processes[0].closed is True

    state = owner.__dict__[extension._INSTALL_STATE_ATTR]
    assert "attempted_intervals" not in state
    assert owner.verify_force_orders_owner_binding(owner) is True
    assert extension.verify_force_orders_callback_bindings(owner, held_callbacks) is True

    progress = auth._reader._page_progress
    progress_key = (extension.FORCE_ORDERS_RESOURCE, None, start_ms, end_ms)
    progress.pop(progress_key, None)
    assert owner.verify_force_orders_owner_binding(owner) is True
    assert extension.verify_force_orders_callback_bindings(owner, held_callbacks) is True

    with pytest.raises(owner.RootTH01AccountWindowBlocked) as replay:
        capability.force_orders(start_ms, end_ms, root_attempt=ticket)
    assert replay.value.code == "force_orders_attempt_ledger_invalid"
    assert ledger.verify(ticket, auth, start_ms, end_ms, expected_state="terminal") is True
    assert ledger.snapshot()[3][-1][7:] == ("terminal", "blocked")
    root_module = _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)]
    with pytest.raises(root_module.RootAccountWindowCallBlocked) as duplicate:
        ledger.reserve(auth, start_ms, end_ms)
    assert duplicate.value.code == "force_orders_attempt_replay"
    assert len(requests) == 1
    assert auth._reader._request_count[0] == 1


def test_force_orders_same_interval_reuses_reader_progress_only_after_root_phase_change(
    monkeypatch,
):
    owner = _load_owner(monkeypatch)
    now_ms = int(time.time() * 1000)
    body = json.dumps([_force_row(11, now_ms - 500)], separators=(",", ":")).encode("ascii")
    _context, requests = _install_fake_transport(owner, monkeypatch, body)
    auth, capability, _directory, start_ms = _make_auth(owner, monkeypatch)
    end_ms = int(time.time() * 1000) - 1

    first_page, first_ticket = _call_force_orders(owner, auth, capability, start_ms, end_ms)
    assert first_ticket.sequence == 0
    assert len(requests) == 1

    ledger = capability._root_attempt_ledger
    ledger.set_phase("after_cleanup")
    second_page, second_ticket = _call_force_orders(owner, auth, capability, start_ms, end_ms)

    assert second_ticket.sequence == 1
    assert second_ticket is not first_ticket
    assert second_page.request_ref != first_page.request_ref
    assert auth._reader._request_count[0] == 2
    assert len(requests) == 2
    assert (
        owner.verify_force_orders_page(
            auth, first_page, start_ms, end_ms, root_attempt=first_ticket
        )
        is True
    )
    assert (
        owner.verify_force_orders_page(
            auth, second_page, start_ms, end_ms, root_attempt=second_ticket
        )
        is True
    )


def test_force_orders_path_rejects_unknown_symbol_cursor_overbound_and_mutation_routes(
    monkeypatch,
):
    owner = _load_owner(monkeypatch)
    now_ms = int(time.time() * 1000)
    history_start_ms = now_ms - 10 * 24 * 60 * 60 * 1000
    start_ms = history_start_ms
    query = {"startTime": start_ms, "endTime": start_ms + 60 * 60 * 1000, "limit": 100}

    path, planned, history = owner._fixed_request_path(
        "force_orders_in_window", query, history_start_ms, now_ms
    )
    assert path == "/fapi/v1/forceOrders"
    assert planned == query
    assert history is True

    rejected = (
        ("unknown_route", query),
        ("force_orders_in_window", {**query, "symbol": "BTCUSDT"}),
        ("force_orders_in_window", {**query, "page": 1}),
        ("force_orders_in_window", {**query, "autoCloseType": "LIQUIDATION"}),
        ("force_orders_in_window", {**query, "limit": 101}),
        ("cancel_order", {"symbol": "BTCUSDT", "orderId": 1}),
    )
    for resource, bad_query in rejected:
        with pytest.raises(owner.RootTH01AccountWindowBlocked):
            owner._fixed_request_path(resource, bad_query, history_start_ms, now_ms)

    seven_days = 7 * 24 * 60 * 60 * 1000
    overbound = {
        "startTime": history_start_ms,
        "endTime": history_start_ms + seven_days,
        "limit": 100,
    }
    with pytest.raises(owner.RootTH01AccountWindowBlocked) as exc:
        owner._fixed_request_path("force_orders_in_window", overbound, history_start_ms, now_ms)
    assert exc.value.code == "fixed_get_window_rejected"


def test_force_orders_install_rejects_unverified_or_non_main_owner(monkeypatch):
    owner = _load_owner(monkeypatch)
    other = ModuleType("__main__")
    with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
        extension.install_force_orders_extension(other, _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)])
    assert exc.value.code == "force_orders_owner_binding_invalid"
    with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
        extension.install_force_orders_extension(owner, _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)])
    assert exc.value.code == "force_orders_extension_already_installed"


def test_extension_and_owner_source_pins_are_exact():
    assert hashlib.sha256(OWNER_PATH.read_bytes()).hexdigest() == OWNER_SHA256
    assert (
        hashlib.sha256(ACCOUNT_WINDOW_CANDIDATE_PATH.read_bytes()).hexdigest()
        == ACCOUNT_WINDOW_CANDIDATE_SHA256
    )
    assert (
        hashlib.sha256(EXTENSION_PATH.read_bytes()).hexdigest()
        == extension._read_extension_source()[1]
    )
    assert extension.BASE_OWNER_SHA256 == OWNER_SHA256
    assert extension.FORCE_ORDERS_PATH == "/fapi/v1/forceOrders"


def test_installed_owner_binding_verifier_detects_mutated_dispatcher(monkeypatch):
    owner = _load_owner(monkeypatch)
    original = owner._run_root_fixed_signed_get
    owner._run_root_fixed_signed_get = lambda *_args, **_kwargs: None
    assert owner.verify_force_orders_owner_binding(owner) is False
    owner._run_root_fixed_signed_get = original
    assert owner.verify_force_orders_owner_binding(owner) is True


def test_root_attempt_method_and_module_binding_mutations_are_detected(monkeypatch):
    owner = _load_owner(monkeypatch)
    root_module = _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)]
    method = root_module.RootForceOrdersAttemptLedgerV1.verify
    original_code = method.__code__

    def reject_all(*_args, **_kwargs):
        return False

    method.__code__ = reject_all.__code__
    assert owner.verify_force_orders_owner_binding(owner) is False
    method.__code__ = original_code
    assert owner.verify_force_orders_owner_binding(owner) is True

    original_phases = root_module.PHASES
    root_module.PHASES = ("baseline", "unexpected")
    assert owner.verify_force_orders_owner_binding(owner) is False
    root_module.PHASES = original_phases
    assert owner.verify_force_orders_owner_binding(owner) is True


def test_install_rejects_candidate_from_wrong_r2_driver(monkeypatch):
    owner = _load_owner(monkeypatch, install=False)
    owner._CANDIDATE_MODULE.DRIVER_PATH = OWNER_PATH
    with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
        extension.install_force_orders_extension(owner, _ROOT_WRAPPERS_BY_OWNER_ID[id(owner)])
    assert exc.value.code == "force_orders_candidate_binding_invalid"


def test_callback_snapshot_detects_in_place_verifier_code_mutation(monkeypatch):
    owner = _load_owner(monkeypatch)
    held = extension.capture_force_orders_callback_bindings(owner)
    verifier = owner.verify_force_orders_owner_binding
    original_code = verifier.__code__

    def replacement_factory():
        first = object()
        second = object()

        def always_true(_candidate):
            _ = first
            _ = second
            return True

        return always_true

    verifier.__code__ = replacement_factory().__code__
    assert verifier(object()) is True
    assert extension.verify_force_orders_callback_bindings(owner, held) is False

    verifier.__code__ = original_code
    assert extension.verify_force_orders_callback_bindings(owner, held) is True
    assert verifier(owner) is True


def test_callback_snapshot_detects_nested_require_function_code_mutation(monkeypatch):
    owner = _load_owner(monkeypatch)
    held = extension.capture_force_orders_callback_bindings(owner)
    route_closure = dict(
        zip(owner._fixed_request_path.__code__.co_freevars, owner._fixed_request_path.__closure__)
    )
    require_binding = route_closure["require_owner_binding"]
    require = require_binding.cell_contents
    original_code = require.__code__

    def replacement():
        return None

    require.__code__ = replacement.__code__.replace(co_freevars=original_code.co_freevars)
    assert owner.verify_force_orders_owner_binding(owner) is True
    assert extension.verify_force_orders_callback_bindings(owner, held) is False
    with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
        extension.capture_force_orders_callback_bindings(owner)
    assert exc.value.code == "force_orders_callback_binding_invalid"

    require.__code__ = original_code
    assert extension.verify_force_orders_callback_bindings(owner, held) is True
    assert owner.verify_force_orders_owner_binding(owner) is True


def test_callback_snapshot_detects_module_global_source_reader_code_mutation(monkeypatch):
    owner = _load_owner(monkeypatch)
    held = extension.capture_force_orders_callback_bindings(owner)
    extension_digest = extension._read_extension_source()[1]
    source_reader = extension._read_extension_source
    original_code = source_reader.__code__
    replacement_namespace = {"sys": sys, "__name__": extension.__name__}
    replacement_source = (
        "def replacement():\n" f"    return (sys.modules[__name__], {extension_digest!r})\n"
    )
    exec(compile(replacement_source, "<source-fake-replacement>", "exec"), replacement_namespace)

    source_reader.__code__ = replacement_namespace["replacement"].__code__
    try:
        assert source_reader() == (extension, extension_digest)
        assert owner.verify_force_orders_owner_binding(owner) is False
        assert extension.verify_force_orders_callback_bindings(owner, held) is False
        with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
            extension.capture_force_orders_callback_bindings(owner)
        assert exc.value.code == "force_orders_callback_binding_invalid"
    finally:
        source_reader.__code__ = original_code

    assert extension.verify_force_orders_callback_bindings(owner, held) is True
    assert owner.verify_force_orders_owner_binding(owner) is True


def test_extension_global_snapshot_detects_replace_rebinding(monkeypatch):
    owner = _load_owner(monkeypatch)
    held = extension.capture_force_orders_callback_bindings(owner)
    original_replace = extension.replace
    extension.replace = lambda page, **_changes: page
    try:
        assert owner.verify_force_orders_owner_binding(owner) is False
        assert extension.verify_force_orders_callback_bindings(owner, held) is False
    finally:
        extension.replace = original_replace
    assert owner.verify_force_orders_owner_binding(owner) is True
    assert extension.verify_force_orders_callback_bindings(owner, held) is True


def test_route_binding_snapshot_detects_mutable_map_injection(monkeypatch):
    owner = _load_owner(monkeypatch)
    held = extension.capture_force_orders_callback_bindings(owner)
    route_closure = dict(
        zip(owner._fixed_request_path.__code__.co_freevars, owner._fixed_request_path.__closure__)
    )
    base_routes = route_closure["base_routes"].cell_contents
    require_binding = route_closure["require_owner_binding"].cell_contents
    require_closure = dict(zip(require_binding.__code__.co_freevars, require_binding.__closure__))
    expected_routes = require_closure["expected"].cell_contents["FIXED_RESOURCE_PATHS"]
    route_name = "public_review_added_route"
    route_path = "/fapi/v1/unapproved"
    assert route_name not in base_routes
    assert route_name not in expected_routes

    base_routes[route_name] = route_path
    expected_routes[route_name] = route_path
    try:
        assert owner.verify_force_orders_owner_binding(owner) is False
        assert extension.verify_force_orders_callback_bindings(owner, held) is False
        with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
            extension.capture_force_orders_callback_bindings(owner)
        assert exc.value.code == "force_orders_callback_binding_invalid"
        with pytest.raises(owner.RootTH01AccountWindowBlocked) as route_exc:
            owner._fixed_request_path(route_name, {}, 1_000, 1_001)
        assert route_exc.value.code == "force_orders_owner_binding_lost"
    finally:
        base_routes.pop(route_name, None)
        expected_routes.pop(route_name, None)

    assert owner.verify_force_orders_owner_binding(owner) is True
    assert extension.verify_force_orders_callback_bindings(owner, held) is True


def test_imported_hash_callable_binding_detects_hashlib_attribute_mutation(monkeypatch):
    owner = _load_owner(monkeypatch)
    held = extension.capture_force_orders_callback_bindings(owner)
    original_sha256 = hashlib.sha256

    class _ForgedDigest:
        def hexdigest(self):
            return extension._EXTENSION_SELF_PIN

    def forged_sha256(_payload):
        return _ForgedDigest()

    hashlib.sha256 = forged_sha256
    try:
        assert owner.verify_force_orders_owner_binding(owner) is False
        assert extension.verify_force_orders_callback_bindings(owner, held) is False
        with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
            extension.capture_force_orders_callback_bindings(owner)
        assert exc.value.code == "force_orders_callback_binding_invalid"
    finally:
        hashlib.sha256 = original_sha256

    assert owner.verify_force_orders_owner_binding(owner) is True
    assert extension.verify_force_orders_callback_bindings(owner, held) is True


def test_install_publication_rolls_back_partial_bindings_and_latches_failure():
    class FailOnceDict(dict):
        def __setitem__(self, key, value):
            if key == "second":
                raise RuntimeError("injected publication failure")
            super().__setitem__(key, value)

    original = {"baseline": object()}
    target = FailOnceDict(original)
    state = {"installation_phase": "publishing"}
    failed_value = "f" * 64

    with pytest.raises(RuntimeError, match="injected publication failure"):
        extension._publish_module_bindings(
            target,
            {"first": object(), "second": object()},
            extension._INSTALL_FAILED_ATTR,
            failed_value,
            state,
        )

    assert {
        key: value for key, value in target.items() if key != extension._INSTALL_FAILED_ATTR
    } == original
    assert target[extension._INSTALL_FAILED_ATTR] == failed_value
    assert state["installation_phase"] == "failed"


def test_install_rejects_module_subclass_before_any_publication(monkeypatch):
    owner = _load_owner(monkeypatch, install=False)

    class FailModule(ModuleType):
        def __setattr__(self, name, value):
            if name == "verify_force_orders_reader_binding":
                raise RuntimeError("injected module attribute failure")
            super().__setattr__(name, value)

    subclass = FailModule("__main__")
    subclass.__dict__.update(owner.__dict__)
    subclass.__dict__["__package__"] = None
    monkeypatch.setitem(sys.modules, "__main__", subclass)
    before = dict(subclass.__dict__)

    with pytest.raises(extension.ForceOrdersExtensionBlocked) as child_exc:
        extension._force_orders_spawn_worker(None, "invalid_resource", {}, "", "", 0, 0.0)
    assert child_exc.value.code == "force_orders_spawn_binding_invalid"
    assert subclass.__package__ is None

    with pytest.raises(extension.ForceOrdersExtensionBlocked) as exc:
        extension.install_force_orders_extension(subclass)

    assert exc.value.code == "force_orders_owner_binding_invalid"
    assert subclass.__dict__ == before
    assert extension._INSTALL_STATE_ATTR not in subclass.__dict__
    assert extension._INSTALL_FAILED_ATTR not in subclass.__dict__


def test_child_trampoline_binds_package_before_install_and_delegation(monkeypatch):
    owner = _load_owner(monkeypatch, install=False, module_name="__mp_main__", package=None)
    with pytest.raises(owner.RootTH01AccountWindowBlocked) as exc:
        extension._force_orders_spawn_worker(None, "invalid_resource", {}, "", "", 0, 0.0)
    assert exc.value.code == "fixed_get_worker_input_invalid"
    assert owner.__package__ == "examples.000_live_certification.binance_penetration._certification"
    assert owner.verify_force_orders_owner_binding(owner) is True
