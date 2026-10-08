"""Standalone source-fake QA for the internal TH01 fixed-GET transport.

This component test loads the exact owner source bytes with ``compile`` and
``exec``. It imports no TH01 reader, collector, availability probe, R3
bootstrap, account fixture, or provider runtime, and it never reads credentials
or creates an OS process or pipe.
"""

from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
import time
import types

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
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
OWNER_MODULE_NAME = "_iteration41_th01_fixed_get_transport_component_owner"


def _load_pinned_owner():
    raw = OWNER_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == OWNER_SHA256
    before = set(sys.modules)
    module = types.ModuleType(OWNER_MODULE_NAME)
    module.__file__ = str(OWNER_PATH)
    module.__package__ = ""
    sys.modules[OWNER_MODULE_NAME] = module
    exec(compile(raw, str(OWNER_PATH), "exec"), module.__dict__)
    module.__component_import_delta__ = frozenset(set(sys.modules) - before)
    return module


source = _load_pinned_owner()


@pytest.fixture(autouse=True)
def _clear_active_workers():
    source._ACTIVE_ROOT_FIXED_WORKERS.clear()
    yield
    source._ACTIVE_ROOT_FIXED_WORKERS.clear()


class _PipeEnd:
    def __init__(self, shared, side):
        self.shared = shared
        self.side = side

    def send(self, frame):
        assert self.side == "child"
        self.shared["frames"].append(frame)

    def close(self):
        if self.side == "child":
            self.shared["writer_closed"] = True
        else:
            self.shared["reader_closed"] = True

    def poll(self, _timeout=0):
        if self.shared["frames"]:
            return True
        if self.side == "parent" and self.shared["writer_closed"]:
            error = OSError("synthetic Windows broken-pipe poll")
            error.winerror = 109
            raise error
        return False

    def recv(self):
        if self.shared["frames"]:
            return self.shared["frames"].pop(0)
        if self.shared["case"] == "recv_error":
            raise OSError("synthetic read detail must stay private")
        raise EOFError


class _ParentProcess:
    def __init__(self, shared, target, args):
        self.shared = shared
        self.target = target
        self.args = args
        self.alive = False
        self.closed = False
        self.exitcode = None

    def start(self):
        mode = self.shared["case"]
        if mode == "worker":
            self.target(*self.args)
            self.exitcode = 0
            return

        child, resource, planned, _key, _secret, _history_start, _deadline = self.args
        started_ms = int(time.time() * 1000) - 1
        timestamp = started_ms - 1 if mode == "out_of_range" else started_ms + 1
        actual_query = dict(planned)
        actual_query.update(
            {"recvWindow": source.FIXED_RECV_WINDOW_MS, "timestamp": timestamp}
        )
        frame = (200, b"{}", True, None, actual_query, started_ms, started_ms + 2)
        if mode == "malformed":
            frame = (200, "body-is-not-bytes", True, None, actual_query, started_ms, started_ms + 2)
        child.send(frame)
        if mode == "second_frame":
            child.send(frame)
        self.alive = mode == "still_alive"
        self.exitcode = None if self.alive else 0

    def is_alive(self):
        if self.closed:
            raise ValueError("process object is closed")
        return self.alive

    def join(self, timeout=None):
        return None

    def terminate(self):
        if self.shared["case"] == "still_alive":
            return
        self.alive = False
        self.exitcode = -15

    def kill(self):
        self.terminate()

    def close(self):
        if self.alive:
            raise ValueError("cannot close a started process while it is alive")
        if self.shared["case"] == "close_uncertain":
            raise OSError("synthetic close uncertainty")
        self.closed = True


class _Context:
    def __init__(self, case):
        self.shared = {
            "case": case,
            "frames": [],
            "writer_closed": False,
            "reader_closed": False,
            "workers": [],
            "wait_calls": 0,
        }

    def Pipe(self, duplex=False):
        assert duplex is False
        return _PipeEnd(self.shared, "parent"), _PipeEnd(self.shared, "child")

    def Process(self, target, args, **_kwargs):
        worker = _ParentProcess(self.shared, target, args)
        self.shared["workers"].append(worker)
        return worker


def _run_parent_case(monkeypatch, case):
    source._ACTIVE_ROOT_FIXED_WORKERS.clear()
    context = _Context(case)
    monkeypatch.setattr(source.multiprocessing, "get_context", lambda _method: context)

    def bounded_wait(connections, timeout=None):
        assert len(connections) == 1
        assert timeout == 0.1
        connection = connections[0]
        context.shared["wait_calls"] += 1
        if case == "not_ready":
            return []
        if case == "wait_error":
            raise OSError("synthetic wait detail must stay private")
        return connections if context.shared["frames"] or context.shared["writer_closed"] else []

    monkeypatch.setattr(source, "wait_for_connections", bounded_wait)
    try:
        outcome = source._run_root_fixed_signed_get(
            "account_configuration",
            {},
            "synthetic-key",
            "synthetic-secret",
            0,
            time.monotonic() + 5.0,
        )
        return context, outcome, None
    except source.RootTH01AccountWindowBlocked as exc:
        return context, None, exc


def test_parent_accepts_one_bounded_frame_and_keeps_uncertain_cleanup_blocked(monkeypatch):
    context, outcome, error = _run_parent_case(monkeypatch, "valid")
    assert error is None
    assert outcome.worker_exit_code == 0
    assert outcome.pipe_eof is True
    assert context.shared["wait_calls"] == 1
    assert context.shared["workers"][0].closed is True
    assert context.shared["workers"][0] not in source._ACTIVE_ROOT_FIXED_WORKERS

    for case, expected_code in (
        ("out_of_range", "fixed_get_frame_invalid"),
        ("malformed", "fixed_get_frame_invalid"),
        ("second_frame", "fixed_get_multiple_frames"),
        ("not_ready", "fixed_get_response_pipe_uncertain"),
        ("wait_error", "fixed_get_worker_failed"),
        ("recv_error", "fixed_get_worker_failed"),
    ):
        context, outcome, error = _run_parent_case(monkeypatch, case)
        assert outcome is None
        assert type(error) is source.RootTH01AccountWindowBlocked
        assert error.code == expected_code
        assert context.shared["workers"][0].closed is True
        assert context.shared["workers"][0] not in source._ACTIVE_ROOT_FIXED_WORKERS
        assert context.shared["wait_calls"] == 1

    for case, expected_code in (
        ("still_alive", "fixed_get_worker_cleanup_uncertain"),
        ("close_uncertain", "fixed_get_worker_close_uncertain"),
    ):
        context, outcome, error = _run_parent_case(monkeypatch, case)
        assert outcome is None
        assert type(error) is source.RootTH01AccountWindowBlocked
        assert error.code == expected_code
        assert context.shared["workers"][0] in source._ACTIVE_ROOT_FIXED_WORKERS
        assert context.shared["workers"][0].closed is False
    source._ACTIVE_ROOT_FIXED_WORKERS.clear()


def test_component_import_loads_no_full_th01_or_provider_runtime():
    imported = source.__component_import_delta__
    assert not any(
        name == "backtrader_runtime"
        or name.startswith("backtrader_runtime.")
        or name == "_certification"
        or name.startswith("_certification.")
        for name in imported
    )
    assert source._ACTIVE_ROOT_FIXED_WORKERS == []
    assert source._ACTIVE_ROOT_PROBE_RECEIPTS == []


def test_actual_worker_function_is_get_only_and_public_diagnostics_are_closed(monkeypatch):
    synthetic_ssl_context = object()
    requests = []

    class _Socket:
        def settimeout(self, _timeout):
            return None

    class _Response:
        def __init__(self, status):
            self.status = status
            self.body = b"{}"
            self._read = False

        def getheader(self, name, default=None):
            return {
                "Content-Encoding": "identity",
                "Content-Length": str(len(self.body)),
            }.get(name, default)

        def read1(self, _limit):
            if self._read:
                return b""
            self._read = True
            return self.body

    class _HTTPSConnection:
        def __init__(self, host, *, timeout, context):
            assert host == source.FIXED_HOST
            assert 0 < timeout <= source.FIXED_REQUEST_TIMEOUT_SECONDS
            assert context is synthetic_ssl_context
            self.sock = None
            self.status = 401 if requests and requests[-1]["case"] == "client_rejected" else 200

        def connect(self):
            self.sock = _Socket()

        def request(self, method, target, *, headers):
            assert method == "GET"
            assert target.split("?", 1)[0] == source.FIXED_RESOURCE_PATHS[
                "account_configuration"
            ]
            assert headers["Accept-Encoding"] == "identity"
            assert headers["X-MBX-APIKEY"] == "synthetic-key"
            requests[-1]["method"] = method
            requests[-1]["path"] = target.split("?", 1)[0]

        def getresponse(self):
            return _Response(self.status)

        def close(self):
            return None

    monkeypatch.setattr(source.http.client, "HTTPSConnection", _HTTPSConnection)
    monkeypatch.setattr(source.ssl, "create_default_context", lambda: synthetic_ssl_context)

    for case, expected in (
        ("worker", "expected_200"),
        ("client_rejected", "client_rejected"),
    ):
        requests.append({"case": case})
        context, outcome, error = _run_parent_case(monkeypatch, "worker")
        assert error is None
        diagnostic = source._fixed_get_transport_diagnostic_document(
            source._fixed_get_outcome_diagnostic(outcome)
        )
        assert diagnostic["http_response_category"] == expected
        assert diagnostic["cleanup_status"] == "clean"
        assert requests[-1]["method"] == "GET"
        assert requests[-1]["path"] == source.FIXED_RESOURCE_PATHS[
            "account_configuration"
        ]
        assert context.shared["workers"][0].closed is True

    rendered = json.dumps(diagnostic, sort_keys=True)
    assert "synthetic-key" not in rendered
    assert "synthetic-secret" not in rendered
    assert "signature" not in rendered
    assert all(item.get("method") == "GET" for item in requests)

