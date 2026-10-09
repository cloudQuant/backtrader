"""Source-fake contracts for the additive Binance TH01 account snapshot R2.

All HTTP responses, rows, account references, and protected artifacts in this
module are synthetic. No provider account, credential source, native API, or
process transport is accessed.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import sys
import time
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[3]
SUITE = ROOT / "examples" / "000_live_certification" / "binance_penetration"
CERT = SUITE / "_certification"
OWNER_PATH = CERT / "th01_root_protected_owner_r1.py"
R1_PATH = CERT / "th01_account_full_snapshot_r1.py"
R2_PATH = CERT / "th01_account_full_snapshot_r2.py"
R9_PATH = CERT / "th01_force_orders_transport_r9.py"
DRIVER_PATH = ROOT / "scripts" / "iteration41_binance_th01_account_window_candidate_r2.py"
ROOT_WRAPPER_PATH = ROOT / "scripts" / "iteration41_binance_th01_root_account_window_call_r1.py"
CANDIDATE_PATH = CERT / "th01_account_window_candidate_r2.py"
if str(SUITE) not in sys.path:
    sys.path.insert(0, str(SUITE))

from _certification import th01_account_full_snapshot_r1 as r1  # noqa: E402
from _certification import th01_account_full_snapshot_r2 as r2  # noqa: E402


OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
R9_SHA256 = "c937a07671a6df7991fb29e131d895c0eca21644d28140542fab7c8b0db1b944"
CANDIDATE_SHA256 = "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63"
ROOT_WRAPPER_SHA256 = "ba0360ecc5ed99b37196e3d077e25a78cd771facec8e224ab1371635cf9be021"
R9_MODULE_NAME = r2.R9_MODULE_NAME


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        pytest.fail("network access is forbidden in the R2 source-fake suite")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


class FakeDirectory:
    def __init__(self, path: Path):
        self.path = path
        self.records: list[tuple[str, dict]] = []

    def write_json(self, name, document):
        self.records.append((name, document))


class FakeResponse:
    def __init__(self, body: bytes):
        self.status = 200
        self.body = body
        self._read = False

    def getheader(self, name, default=None):
        return {
            "Content-Encoding": "identity",
            "Content-Length": str(len(self.body)),
        }.get(name, default)

    def read(self, size=-1):
        assert size > 0
        if self._read:
            return b""
        self._read = True
        return self.body[:size]

    def read1(self, size=-1):
        return self.read(size)


class FakeSock:
    def settimeout(self, _timeout):
        return None


class FakePipeState:
    def __init__(self):
        self.frames = []
        self.writer_closed = False


class FakePipeEnd:
    def __init__(self, state: FakePipeState, *, parent: bool):
        self.state = state
        self.parent = parent
        self.closed = False

    def send(self, frame):
        assert not self.parent and not self.closed
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
        raise OSError("synthetic pipe has no frame")

    def close(self):
        self.closed = True
        if not self.parent:
            self.state.writer_closed = True


class FakeProcess:
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


class FakeSpawnContext:
    def __init__(self):
        self.processes = []
        self.pipe_states = []
        self.endpoints = []

    def Pipe(self, duplex=False):
        assert duplex is False
        state = FakePipeState()
        parent, child = FakePipeEnd(state, parent=True), FakePipeEnd(state, parent=False)
        self.pipe_states.append(state)
        self.endpoints.extend((parent, child))
        return parent, child

    def Process(self, target, args, **kwargs):
        process = FakeProcess(target, args, **kwargs)
        self.processes.append(process)
        return process


class FakeClock:
    def __init__(self, now_ms: int):
        self.now_ms = now_ms
        self.monotonic_seconds = 10_000.0

    def time(self):
        return self.now_ms / 1000.0

    def monotonic(self):
        return self.monotonic_seconds

    def advance(self, milliseconds: int):
        assert milliseconds >= 0
        self.now_ms += milliseconds
        self.monotonic_seconds += milliseconds / 1000.0


class Fixture:
    def __init__(self, owner, wrapper, force_module, hook, writer, auth, action, clock):
        self.owner = owner
        self.wrapper = wrapper
        self.force_module = force_module
        self.hook = hook
        self.writer = writer
        self.auth = auth
        self.action = action
        self.clock = clock
        self.counter = 0

    def page(
        self,
        resource,
        rows,
        *,
        started_ms,
        requested_start_ms=0,
        requested_end_ms=0,
        row_limit=1000,
        cursor=None,
        next_cursor=None,
        page_index=0,
        has_more=False,
        terminal=None,
    ):
        self.counter += 1
        body = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        parsed = self.owner._root_parse_page_rows(body)
        private_ref = uuid4().hex
        reader = self.auth._reader
        reader._private_record_refs.append(private_ref)
        completed_ms = started_ms + 1
        reader._request_count[0] += 1
        reader._row_count[0] += len(parsed)
        reader._response_bytes[0] += len(body)
        reader._first_request_ms[0] = (
            started_ms
            if reader._first_request_ms[0] is None
            else min(reader._first_request_ms[0], started_ms)
        )
        reader._last_response_ms[0] = max(reader._last_response_ms[0] or 0, completed_ms)
        return self.owner._RootTH01AccountWindowPageV1(
            resource=resource,
            request_ref=str(uuid4()),
            response_ref=str(uuid4()),
            request_cursor=cursor,
            next_cursor=next_cursor,
            page_index=page_index,
            requested_start_ms=requested_start_ms,
            requested_end_ms=requested_end_ms,
            request_started_at_ms=started_ms,
            response_completed_at_ms=completed_ms,
            http_status=200,
            transport_complete=True,
            row_limit=row_limit,
            row_count=len(parsed),
            has_more=has_more,
            terminal_proof=terminal or ("unknown" if has_more else "short_page"),
            truncated=False,
            provider_watermark_ms=None,
            rows=parsed,
            response_body=body,
            _private_record_ref=private_ref,
            _invocation_id=self.auth.invocation_id,
            _evidence_window_id=self.auth.evidence_window_id,
            _account_binding_ref=self.auth._account_binding_ref,
            _seal=self.owner._ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL,
        )

    def current_pages(self, started_ms, *, positions=None, balance="1000"):
        rows = {
            "account_configuration": [
                {"canTrade": True, "dualSidePosition": False, "multiAssetsMargin": False}
            ],
            "account_v2": [
                {
                    "assets": [{"asset": "USDT", "walletBalance": balance}],
                    "positions": list(positions or []),
                }
            ],
            "standard_open_orders": [],
            "algo_open_orders": [],
        }
        return {
            resource: self.page(
                resource,
                rows[resource],
                started_ms=started_ms + index * 2,
                row_limit=5000,
                terminal="single_response",
            )
            for index, resource in enumerate(r1.CURRENT_ROUTES)
        }

    def history_page(
        self,
        resource,
        rows,
        *,
        start_ms,
        cutoff_ms,
        started_ms,
        row_limit,
        terminal="short_page",
        has_more=False,
    ):
        return self.page(
            resource,
            rows,
            started_ms=started_ms,
            requested_start_ms=start_ms,
            requested_end_ms=cutoff_ms,
            row_limit=row_limit,
            terminal=terminal,
            has_more=has_more,
        )


def _load_exact_module(monkeypatch, name: str, path: Path, digest: str | None = None):
    raw = path.read_bytes()
    if digest is not None:
        assert hashlib.sha256(raw).hexdigest() == digest
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _fixture(monkeypatch):
    wrapper_name = "_iteration41_r2_root_wrapper_" + uuid4().hex
    wrapper_spec = importlib.util.spec_from_file_location(wrapper_name, ROOT_WRAPPER_PATH)
    assert wrapper_spec is not None and wrapper_spec.loader is not None
    wrapper_raw = ROOT_WRAPPER_PATH.read_bytes()
    assert hashlib.sha256(wrapper_raw).hexdigest() == ROOT_WRAPPER_SHA256
    wrapper = ModuleType(wrapper_name)
    wrapper.__file__ = str(ROOT_WRAPPER_PATH)
    wrapper.__package__ = ""
    wrapper.__spec__ = wrapper_spec
    wrapper.__loader__ = wrapper_spec.loader
    monkeypatch.setitem(sys.modules, wrapper_name, wrapper)
    exec(compile(wrapper_raw, str(ROOT_WRAPPER_PATH), "exec", dont_inherit=True), wrapper.__dict__)
    wrapper.__th01_held_source_sha256__ = ROOT_WRAPPER_SHA256

    owner_raw = OWNER_PATH.read_bytes()
    assert hashlib.sha256(owner_raw).hexdigest() == OWNER_SHA256
    owner = ModuleType("__main__")
    owner.__package__ = "examples.000_live_certification.binance_penetration._certification"
    owner.__file__ = str(OWNER_PATH)
    monkeypatch.setitem(sys.modules, "__main__", owner)
    exec(compile(owner_raw, str(OWNER_PATH), "exec", dont_inherit=True), owner.__dict__)
    owner.__file__ = str(DRIVER_PATH)
    owner.OWNER_PATH = OWNER_PATH
    owner.OWNER_SHA256 = OWNER_SHA256
    owner.__th01_verified_owner_source_sha256__ = OWNER_SHA256
    owner.__th01_verified_owner_source_path__ = str(OWNER_PATH)

    candidate = _load_exact_module(
        monkeypatch,
        "_iteration41_th01_account_window_candidate_r2_" + uuid4().hex,
        CANDIDATE_PATH,
        CANDIDATE_SHA256,
    )
    candidate.__th01_verified_candidate_source_sha256__ = CANDIDATE_SHA256
    candidate.DRIVER_PATH = DRIVER_PATH
    owner._CANDIDATE_MODULE = candidate

    force_module = sys.modules.get(R9_MODULE_NAME)
    if force_module is None:
        force_module = _load_exact_module(monkeypatch, R9_MODULE_NAME, R9_PATH, R9_SHA256)
    assert Path(force_module.__file__).resolve() == R9_PATH.resolve()
    assert force_module.install_force_orders_extension(owner, wrapper) is owner
    callback_bindings = owner.capture_force_orders_callback_bindings(owner)
    assert owner.verify_force_orders_callback_bindings(owner, callback_bindings) is True

    fake_directory_type = FakeDirectory
    fake_helper = SimpleNamespace(PrivateArtifactDirectory=fake_directory_type)
    monkeypatch.setattr(owner, "_private_helper", lambda: fake_helper)
    clock = FakeClock(int(time.time() * 1000))
    owner.time = clock
    wrapper.time = clock
    r1.time = clock
    r2.time = clock
    invocation = uuid4().hex
    directory = FakeDirectory(Path("C:/fake/bt-iteration41-th01-" + invocation))
    writer = owner.RootTH01ProtectedWriterV1(
        invocation_id=invocation,
        _directory=directory,
        database_path=directory.path / owner.MONITOR_DATABASE_NAME,
        monitor_log_path=directory.path / owner.TRADELOGGER_NAME,
        _next_sequence=[0],
        _seal=owner._ROOT_TH01_PROTECTED_WRITER_SEAL,
    )
    credential = owner._RootTH01CredentialContextV1(
        source_digest="c" * 64,
        _account_binding_ref="b" * 64,
        _api_key="SYNTHETIC-API-KEY-ONLY",
        _secret="SYNTHETIC-SECRET-ONLY",
        _seal=owner._ROOT_TH01_CREDENTIAL_CONTEXT_SEAL,
    )
    auth = owner._make_root_account_window_auth(
        credential,
        writer,
        invocation,
        "th01-window:" + invocation,
        clock.now_ms - 60_000,
    )
    attempt_ledger = wrapper.RootForceOrdersAttemptLedgerV1(auth)
    force_reader = owner.FixedForceOrdersGetV1(auth, attempt_ledger)
    callback_api = (
        force_module,
        wrapper._module_binding_snapshot(force_module, mutable_globals=frozenset()),
        owner.capture_force_orders_callback_bindings,
        wrapper._function_binding_shape(owner.capture_force_orders_callback_bindings),
        owner.verify_force_orders_callback_bindings,
        wrapper._function_binding_shape(owner.verify_force_orders_callback_bindings),
    )
    action = r2.root_th01_read_action(
        auth,
        external_ref="th01-r2-fake:" + invocation,
        config_snapshot_id="fake-logger-config-v1",
    )
    hook = wrapper.RootSnapshotBackendHookV1(
        owner=owner,
        adapter=r2,
        force_module=force_module,
        force_reader=force_reader,
        auth=auth,
        force_attempt_ledger=attempt_ledger,
        force_callback_bindings=callback_bindings,
        force_callback_api_snapshot=callback_api,
        action=action,
        writer=writer,
    )
    return Fixture(owner, wrapper, force_module, hook, writer, auth, action, clock)


def _catalog_bodies(*, unknown_contract=False, cross_family_symbol=False):
    fapi_contract = "EXOTIC" if unknown_contract else "PERPETUAL"
    fapi = {
        "serverTime": int(time.time() * 1000),
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "contractType": fapi_contract,
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "marginAsset": "USDT",
            }
        ],
    }
    dapi_symbol = "BTCUSDT" if cross_family_symbol else "BTCUSD_PERP"
    dapi = {
        "serverTime": int(time.time() * 1000),
        "symbols": [
            {
                "symbol": dapi_symbol,
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT" if cross_family_symbol else "USD",
                "marginAsset": "BTC",
            }
        ],
    }
    if unknown_contract:
        dapi["symbols"][0]["contractType"] = "NEW_UNKNOWN"
    return {
        ("demo-fapi.binance.com", "/fapi/v1/exchangeInfo"): json.dumps(fapi).encode(),
        ("demo-dapi.binance.com", "/dapi/v1/exchangeInfo"): json.dumps(dapi).encode(),
    }


def _install_catalog_http(monkeypatch, bodies):
    calls = []

    class FakeHTTPSConnection:
        def __init__(self, host, *, timeout, context):
            assert 0 < timeout <= r2.CATALOG_TIMEOUT_SECONDS
            assert context.check_hostname is True
            assert context.verify_mode == ssl.CERT_REQUIRED
            self.host = host
            self.closed = False

        def request(self, method, path, *, headers):
            assert method == "GET"
            assert headers == dict(r2.CATALOG_HEADERS)
            assert (self.host, path) in bodies
            calls.append((self.host, method, path, dict(headers)))

        def getresponse(self):
            return FakeResponse(bodies[(self.host, calls[-1][2])])

        def close(self):
            self.closed = True

    monkeypatch.setattr(r2.http.client, "HTTPSConnection", FakeHTTPSConnection)
    return calls


def _install_fake_signed_get(monkeypatch, owner, body=b"[]"):
    context = FakeSpawnContext()

    class FakeHTTPSConnection:
        def __init__(self, host, *, timeout, context=None):
            assert host == owner.FIXED_HOST
            assert 0 < timeout <= owner.FIXED_REQUEST_TIMEOUT_SECONDS
            assert context == "synthetic-tls-context"
            self.sock = FakeSock()
            self.closed = False

        def connect(self):
            return None

        def request(self, method, path, *, headers):
            assert method == "GET"
            assert path.startswith("/fapi/v1/forceOrders?")
            assert "X-MBX-APIKEY" in headers
            # Do not retain or report credential-bearing query/header contents.

        def getresponse(self):
            return FakeResponse(body)

        def close(self):
            self.closed = True

    monkeypatch.setattr(owner.multiprocessing, "get_context", lambda name: context)
    monkeypatch.setattr(
        owner,
        "wait_for_connections",
        lambda connections, timeout: list(connections)
        if context.pipe_states and context.pipe_states[-1].writer_closed
        else [],
    )
    monkeypatch.setattr(owner.http.client, "HTTPSConnection", FakeHTTPSConnection)
    monkeypatch.setattr(owner.ssl, "create_default_context", lambda: "synthetic-tls-context")
    return context


def _mint_empty_force_page(fixture: Fixture, phase: str, start_ms: int, end_ms: int):
    hook = fixture.hook
    ledger = hook._force_attempt_ledger
    hook._force_attempt_snapshot[0] = ledger.set_phase(phase)
    prior_snapshot = hook._force_attempt_snapshot[0]
    ticket = ledger.reserve(fixture.auth, start_ms, end_ms)
    assert ledger.verify_transition(prior_snapshot, ticket, "reserved") is True
    reserved_snapshot = ledger.snapshot()
    page = hook.force_reader.force_orders(start_ms, end_ms, root_attempt=ticket)
    assert ledger.verify_transition(reserved_snapshot, ticket, "dispatching") is True
    ledger.finish(ticket, "page_received")
    assert ledger.verify_transition(prior_snapshot, ticket, "terminal", "page_received") is True
    hook._force_attempt_snapshot[0] = ledger.snapshot()
    hook._force_page_ticket_bindings.append((page, ticket))
    hook._force_page_ticket_snapshot[0] = tuple(hook._force_page_ticket_bindings)
    return page, ticket


def _later_phase_inputs(fixture: Fixture, producer, phase: str, *, balance="1000"):
    clock = fixture.clock
    phase_start_ms = clock.now_ms
    cutoff = phase_start_ms - 2_000
    current = fixture.current_pages(phase_start_ms, balance=balance)
    clock.advance(10)
    anchor = producer._baseline
    assert anchor is not None
    history_start = anchor.t0_ms - 1
    all_orders = fixture.history_page(
        r1.ALL_ORDERS_RESOURCE,
        [],
        start_ms=history_start,
        cutoff_ms=cutoff,
        started_ms=clock.now_ms,
        row_limit=r1.PAGE_LIMIT,
    )
    clock.advance(2)
    force_page, ticket = _mint_empty_force_page(fixture, phase, history_start, cutoff)
    clock.advance(2)
    income = fixture.history_page(
        r1.INCOME_RESOURCE,
        [],
        start_ms=history_start,
        cutoff_ms=cutoff,
        started_ms=clock.now_ms,
        row_limit=r1.PAGE_LIMIT,
    )
    pages = (force_page,)
    shared = {
        "current_pages": current,
        "all_orders_pages": (all_orders,),
        "income_pages": (income,),
        "force_order_pages": pages,
        "phase_cutoff_ms": cutoff,
    }
    return shared


def test_catalog_capture_and_baseline_produce_scoped_candidate(monkeypatch):
    fixture = _fixture(monkeypatch)
    calls = _install_catalog_http(monkeypatch, _catalog_bodies())
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    assert catalog.usable is True
    assert len(calls) == 2
    assert [(item[0], item[1], item[2]) for item in calls] == [
        (host, "GET", path) for _family, host, path in r2.CATALOG_ROUTES
    ]
    assert all("X-MBX-APIKEY" not in call[3] for call in calls)

    producer = r2.create_root_snapshot_producer_v2(fixture.hook, catalog)
    fixture.clock.advance(2_000)
    pages = fixture.current_pages(fixture.clock.now_ms - 1_000)
    result = producer.collect_baseline(fixture.action, current_pages=pages)
    assert result.status == "READY_SCOPED_CANDIDATE"
    assert result.capture.snapshot.scope == "account_full"
    assert result.capture.snapshot.complete is True
    assert result.capture.snapshot.pagination_complete is True
    public = r2.snapshot_public_document_v2(result)
    assert public["formal_case_pass"] is False
    assert public["scope"] == "binance_demo_usd_m_perpetual"
    assert public["catalog_usd_m_instrument_count"] == 1
    assert public["catalog_coin_m_excluded_instrument_count"] == 1


def test_unknown_catalog_contract_blocks_producer_before_account_snapshot(monkeypatch):
    fixture = _fixture(monkeypatch)
    _install_catalog_http(monkeypatch, _catalog_bodies(unknown_contract=True))
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    assert "catalog_contract_type_unknown" in catalog.blocker_codes
    with pytest.raises(r2.AccountSnapshotR2Blocked, match="instrument_catalog_metadata_unusable"):
        r2.create_root_snapshot_producer_v2(fixture.hook, catalog)


def test_cross_family_catalog_symbol_collision_blocks_producer(monkeypatch):
    fixture = _fixture(monkeypatch)
    _install_catalog_http(monkeypatch, _catalog_bodies(cross_family_symbol=True))
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    assert catalog.usable is False
    assert "catalog_cross_family_symbol_collision" in catalog.blocker_codes
    with pytest.raises(r2.AccountSnapshotR2Blocked, match="instrument_catalog_metadata_unusable"):
        r2.create_root_snapshot_producer_v2(fixture.hook, catalog)


def test_internal_module_global_drift_invalidates_held_producer(monkeypatch):
    fixture = _fixture(monkeypatch)
    _install_catalog_http(monkeypatch, _catalog_bodies())
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    producer = r2.create_root_snapshot_producer_v2(fixture.hook, catalog)
    original = r2._classify_pages_and_snapshot
    try:
        r2._classify_pages_and_snapshot = lambda *_args, **_kwargs: ((), ())
        with pytest.raises(r2.AccountSnapshotR2Blocked) as drift:
            producer._verify_live()
        assert drift.value.code == "r2_producer_api_binding_invalid"
    finally:
        r2._classify_pages_and_snapshot = original
    producer._verify_live()

    getter = type(catalog).usable.fget
    assert getter is not None
    original_code = getter.__code__
    try:
        getter.__code__ = (lambda _catalog: True).__code__
        with pytest.raises(r2.AccountSnapshotR2Blocked) as descriptor_drift:
            producer._verify_live()
        assert descriptor_drift.value.code == "r2_producer_api_binding_invalid"
    finally:
        getter.__code__ = original_code
    producer._verify_live()


def test_coin_m_family_conflict_in_current_state_never_issues_snapshot(monkeypatch):
    fixture = _fixture(monkeypatch)
    _install_catalog_http(monkeypatch, _catalog_bodies())
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    producer = r2.create_root_snapshot_producer_v2(fixture.hook, catalog)
    fixture.clock.advance(2_000)
    pages = fixture.current_pages(
        fixture.clock.now_ms - 1_000,
        positions=[
            {
                "symbol": "BTCUSD_PERP",
                "positionSide": "BOTH",
                "positionAmt": "1",
            }
        ],
    )
    result = producer.collect_baseline(fixture.action, current_pages=pages)
    assert result.status == "BLOCKED_ACCOUNT_SNAPSHOT"
    assert result.capture is None
    document = r2.snapshot_public_document_v2(result)
    assert document["formal_case_pass"] is False
    assert document["account_full_snapshot_issued"] is False
    assert document["product_family_conflict_row_count"] > 0


def _capture_three_phase_candidate(
    monkeypatch,
    *,
    after_balance="1000",
    positive_history=False,
    test_ticket_guards=False,
    test_callback_drift=False,
    test_pagination=False,
):
    fixture = _fixture(monkeypatch)
    _install_catalog_http(monkeypatch, _catalog_bodies())
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    producer = r2.create_root_snapshot_producer_v2(fixture.hook, catalog)
    _install_fake_signed_get(monkeypatch, fixture.owner)
    if test_callback_drift:
        original = fixture.force_module.verify_force_orders_callback_bindings
        fixture.force_module.verify_force_orders_callback_bindings = lambda *_args: True
        with pytest.raises(r2.AccountSnapshotR2Blocked) as drift:
            producer._verify_live()
        assert drift.value.code in {
            "r9_extension_binding_invalid",
            "root_snapshot_hook_binding_invalid",
        }
        fixture.force_module.verify_force_orders_callback_bindings = original
        producer._verify_live()

    fixture.clock.advance(2_000)
    baseline_pages = fixture.current_pages(fixture.clock.now_ms - 1_000)
    baseline_capture = r2.collect_account_snapshot(
        fixture.auth,
        fixture.action,
        "baseline",
        current_pages=baseline_pages,
        all_orders_pages=(),
        income_pages=(),
        force_order_pages=(),
        user_trades_by_symbol={},
        baseline=None,
        prior_snapshot=None,
        phase_cutoff_ms=None,
        force_extension=fixture.owner,
    )
    assert type(baseline_capture) is r2.SnapshotCaptureV1
    fixture.hook._phase_index += 1

    for phase in ("before_cleanup", "after_cleanup"):
        fixture.clock.advance(5_000)
        inputs = _later_phase_inputs(
            fixture, producer, phase, balance=after_balance if phase == "after_cleanup" else "1000"
        )
        anchor = producer._baseline
        assert anchor is not None
        prior = producer._prior_snapshot
        assert prior is not None
        common = {
            **inputs,
            "baseline": anchor,
            "prior_snapshot": prior,
            "force_extension": fixture.owner,
        }
        if test_ticket_guards and phase == "before_cleanup":
            saved = fixture.hook._force_page_ticket_bindings[-1]
            fixture.hook._force_page_ticket_bindings[-1] = (saved[0], object())
            with pytest.raises(
                r2.AccountSnapshotR2Blocked, match="force_orders_page_ticket_invalid"
            ):
                r2.required_user_trade_symbols(
                    fixture.auth,
                    fixture.action,
                    phase,
                    **common,
                )
            fixture.hook._force_page_ticket_bindings[-1] = saved
            fixture.hook._force_page_ticket_bindings.append(saved)
            with pytest.raises(
                r2.AccountSnapshotR2Blocked, match="force_orders_ticket_coverage_missing"
            ):
                r2.required_user_trade_symbols(
                    fixture.auth,
                    fixture.action,
                    phase,
                    **common,
                )
            fixture.hook._force_page_ticket_bindings.pop()
            fixture.hook._force_page_ticket_snapshot[0] = tuple(
                fixture.hook._force_page_ticket_bindings
            )

        if test_pagination and phase == "before_cleanup":
            anchor = producer._baseline
            assert anchor is not None
            saturated_rows = [
                {
                    "symbol": "BTCUSDT",
                    "orderId": index + 1,
                    "time": anchor.t0_ms + 10,
                }
                for index in range(r1.PAGE_LIMIT)
            ]
            current_last = max(
                page.response_completed_at_ms for page in inputs["current_pages"].values()
            )
            saturated = fixture.history_page(
                r1.ALL_ORDERS_RESOURCE,
                saturated_rows,
                start_ms=anchor.t0_ms - 1,
                cutoff_ms=inputs["phase_cutoff_ms"],
                started_ms=current_last + 2,
                row_limit=r1.PAGE_LIMIT,
                terminal="unknown",
                has_more=True,
            )
            incomplete = dict(common)
            incomplete["all_orders_pages"] = (saturated,)
            with pytest.raises(r1.AccountSnapshotBlocked, match="all_orders_bisection_gap"):
                r2.required_user_trade_symbols(
                    fixture.auth,
                    fixture.action,
                    phase,
                    **incomplete,
                )

        if positive_history:
            order_time = anchor.t0_ms + 20
            order_page = fixture.history_page(
                r1.ALL_ORDERS_RESOURCE,
                [{"symbol": "BTCUSDT", "orderId": 7, "time": order_time}],
                start_ms=anchor.t0_ms - 1,
                cutoff_ms=inputs["phase_cutoff_ms"],
                started_ms=fixture.clock.now_ms,
                row_limit=r1.PAGE_LIMIT,
            )
            inputs["all_orders_pages"] = (order_page,)
            common["all_orders_pages"] = (order_page,)

        symbols = r2.required_user_trade_symbols(
            fixture.auth,
            fixture.action,
            phase,
            **common,
        )
        assert symbols == (("BTCUSDT",) if positive_history else ())
        user_trades_by_symbol = {}
        if positive_history:
            order_time = anchor.t0_ms + 20
            trade_page = fixture.history_page(
                r1.USER_TRADES_RESOURCE,
                [
                    {
                        "symbol": "BTCUSDT",
                        "id": 3,
                        "time": order_time,
                        "orderId": 7,
                        "side": "BUY",
                        "buyer": True,
                        "maker": False,
                        "positionSide": "BOTH",
                        "qty": "1",
                        "price": "100",
                        "quoteQty": "100",
                        "commission": "0.1",
                        "commissionAsset": "USDT",
                        "realizedPnl": "0",
                    }
                ],
                start_ms=anchor.t0_ms - 1,
                cutoff_ms=inputs["phase_cutoff_ms"],
                started_ms=fixture.clock.now_ms + 2,
                row_limit=r1.PAGE_LIMIT,
            )
            user_trades_by_symbol = {"BTCUSDT": (trade_page,)}
        try:
            capture = r2.collect_account_snapshot(
                fixture.auth,
                fixture.action,
                phase,
                **common,
                user_trades_by_symbol=user_trades_by_symbol,
            )
        except r2.AccountSnapshotR2Blocked as exc:
            if not (phase == "after_cleanup" and after_balance != "1000"):
                raise
            assert exc.code == "observe_only_account_state_changed"
            break
        assert type(capture) is r2.SnapshotCaptureV1
        fixture.hook._phase_index += 1

    result = r2.account_snapshot_candidate_for_hook_v2(fixture.hook)
    return fixture, result


def test_root_callback_chain_issues_three_reconciled_snapshots_with_r9_tickets(monkeypatch):
    fixture, candidate = _capture_three_phase_candidate(
        monkeypatch,
        test_ticket_guards=True,
        test_callback_drift=True,
        test_pagination=True,
    )
    assert candidate.status == "READY_SCOPED_CANDIDATE"
    assert candidate.capture.snapshot.scope == "account_full"
    assert candidate.capture.snapshot.phase == "after_cleanup"
    assert len(candidate._root_hook._captures) == 0  # full Root session integration is unmodified
    document = r2.snapshot_public_document_v2(candidate)
    assert document["account_full_snapshot_issued"] is True
    assert document["formal_case_pass"] is False
    assert fixture.owner._ACTIVE_ROOT_FIXED_WORKERS == []


def test_stable_nonempty_window_history_reconciles_between_later_phases(monkeypatch):
    _fixture_value, candidate = _capture_three_phase_candidate(
        monkeypatch,
        positive_history=True,
    )
    assert candidate.status == "READY_SCOPED_CANDIDATE"
    assert candidate.capture.snapshot.phase == "after_cleanup"
    assert len(candidate.capture.snapshot.fills) == 1
    assert candidate.capture.snapshot.scope == "account_full"
    assert r2.snapshot_public_document_v2(candidate)["formal_case_pass"] is False


def test_truncated_current_page_cannot_enter_a_baseline_snapshot(monkeypatch):
    fixture = _fixture(monkeypatch)
    _install_catalog_http(monkeypatch, _catalog_bodies())
    catalog = r2.capture_instrument_catalog_v2(fixture.hook)
    producer = r2.create_root_snapshot_producer_v2(fixture.hook, catalog)
    fixture.clock.advance(2_000)
    current = fixture.current_pages(fixture.clock.now_ms - 1_000)
    first = current[r1.CURRENT_ROUTES[0]]
    current[r1.CURRENT_ROUTES[0]] = replace(first, truncated=True)
    with pytest.raises(r1.AccountSnapshotBlocked, match="provider_page_binding_invalid"):
        producer.collect_baseline(fixture.action, current_pages=current)


def test_after_cleanup_balance_delta_fails_closed_as_not_account_full(monkeypatch):
    _fixture_value, candidate = _capture_three_phase_candidate(monkeypatch, after_balance="999")
    assert candidate.status == "BLOCKED_ACCOUNT_SNAPSHOT"
    assert candidate.capture is None
    assert "observe_only_account_state_changed" in candidate.blocker_codes
    document = r2.snapshot_public_document_v2(candidate)
    assert document["account_full_snapshot_issued"] is False
    assert document["complete"] is False
    assert document["formal_case_pass"] is False
