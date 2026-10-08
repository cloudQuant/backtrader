"""Source-fake contracts for the bounded TH01 account-window candidate.

No protected credential read, provider call, Win32 API, native API, OS pipe,
or process spawn is permitted in this module. The accepted transport is
exercised through its pure route-shape contract; Root owns the real Pipe and
spawn checks.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import pickle
from pathlib import Path
import socket
import sys
import time
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
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
CANDIDATE_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_account_window_candidate_r2.py"
)
DRIVER_PATH = ROOT / "scripts" / "iteration41_binance_th01_account_window_candidate_r2.py"


def _load_candidate() -> ModuleType:
    name = "_test_iteration41_th01_account_window_candidate_r2"
    spec = importlib.util.spec_from_file_location(name, CANDIDATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.__th01_verified_candidate_source_sha256__ = hashlib.sha256(
        CANDIDATE_PATH.read_bytes()
    ).hexdigest()
    return module


candidate = _load_candidate()


def _load_exact_owner_sourcefake(monkeypatch):
    owner = ModuleType("__main__")
    owner.__file__ = str(OWNER_PATH)
    monkeypatch.setitem(sys.modules, "__main__", owner)
    owner_bytes = OWNER_PATH.read_bytes()
    exec(compile(owner_bytes, str(OWNER_PATH), "exec", dont_inherit=True), owner.__dict__)
    owner.__file__ = str(DRIVER_PATH)
    owner.__th01_verified_owner_source_sha256__ = candidate.OWNER_SHA256
    owner.__th01_verified_owner_source_path__ = str(OWNER_PATH)
    return owner


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("network access is forbidden in this source-fake suite")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _page(resource: str, rows, *, invocation: str = "a" * 32, window: str = "th01-window:" + "a" * 32,
          account: str = "b" * 64, request: str | None = None, response: str | None = None):
    rows = tuple(rows)
    if resource in {"account_configuration", "account_v2"}:
        body = json.dumps(rows[0], sort_keys=True, separators=(",", ":")).encode("ascii")
    else:
        body = json.dumps(list(rows), sort_keys=True, separators=(",", ":")).encode("ascii")
    token = uuid4().hex
    return candidate.CandidatePageV1(
        resource=resource,
        request_ref=request or token,
        response_ref=response or uuid4().hex,
        rows=rows,
        response_body=body,
        request_started_at_ms=10_000,
        response_completed_at_ms=10_001,
        row_count=len(rows),
        page_limit=0 if resource in candidate.CURRENT_ROUTES else candidate.PAGE_LIMIT,
        query={},
        _invocation_id=invocation,
        _evidence_window_id=window,
        _account_binding_ref=account,
        _seal=candidate._READ_SESSION_SEAL,
    )


def _order(symbol="BTCUSDT", order_id=1, when=1_500, executed="0"):
    return {
        "symbol": symbol,
        "orderId": order_id,
        "time": when,
        "status": "FILLED",
        "side": "BUY",
        "type": "LIMIT",
        "origQty": "1",
        "executedQty": executed,
    }


def _trade(symbol: str, trade_id: int, when: int):
    return {
        "symbol": symbol,
        "id": trade_id,
        "orderId": trade_id + 100,
        "time": when,
        "side": "BUY",
        "positionSide": "BOTH",
        "qty": "0.1",
        "price": "10.25",
        "commission": "0.0001",
        "commissionAsset": "USDT",
        "realizedPnl": "0",
    }


class _EmptyReader:
    _account_binding_ref = "b" * 64

    def __init__(self):
        self.current_calls = []
        self.order_queries = []
        self.income_queries = []
        self.trade_queries = []

    def current(self, resource):
        self.current_calls.append(resource)
        if resource == "account_configuration":
            rows = ({"canTrade": True, "dualSidePosition": False, "multiAssetsMargin": False},)
        elif resource == "account_v2":
            rows = ({"assets": [{"asset": "USDT", "walletBalance": "50.00"}], "positions": []},)
        else:
            rows = ()
        return _page(resource, rows)

    def all_orders(self, start_ms, end_ms):
        self.order_queries.append((start_ms, end_ms))
        return _page("all_orders_in_window", ())

    def income(self, start_ms, end_ms, page_number):
        self.income_queries.append((start_ms, end_ms, page_number))
        return _page("income_in_window", ())

    def user_trades(self, symbol, start_ms, end_ms, from_id=None):
        self.trade_queries.append((symbol, start_ms, end_ms, from_id))
        return _page("user_trades_in_window", ())


def test_verified_helper_loader_compiles_exact_tracked_bytes_without_loading_winapi(monkeypatch, tmp_path):
    owner = _load_exact_owner_sourcefake(monkeypatch)
    verified = candidate.load_verified_read_sources(owner)

    assert set(verified.source_hashes) == {
        "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py",
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        "backtrader_runtime/certification_roundtrip_private.py",
    }
    assert verified.owner is owner
    assert verified.private.PrivateArtifactDirectory.__module__ == verified.private.__name__
    assert sys.modules[verified.private.__name__] is verified.private
    assert verified.private._API is None
    assert "backtrader_runtime" not in {name.split(".", 1)[0] for name in sys.modules if name == "backtrader_runtime"}
    assert "api_key" not in repr(verified)
    assert "secret" not in repr(verified)

    class FakeOSLeaves:
        def __init__(self, helper):
            self.helper = helper
            self.created = []

        @contextmanager
        def opened(self, path, *, directory, access=None):
            target = Path(path)
            assert target.exists()
            assert target.is_dir() is directory
            yield str(target)

        def info(self, handle, *, directory):
            target = Path(handle)
            assert target.is_dir() is directory
            details = target.stat()
            return details.st_dev, details.st_ino

        def current_sid(self):
            return "S-1-5-21-424242-424242-424242-1001"

        def verify_acl(self, _handle, sid, *, directory=False, inherited=False):
            assert sid == self.current_sid()
            assert inherited is False

        @contextmanager
        def descriptor(self, _sid, *, directory):
            yield self.helper._SA()

        def CreateDirectoryW(self, path, _attributes):
            target = Path(path)
            target.mkdir()
            self.created.append(target)
            return True

        def CreateFileW(self, path, *_args):
            target = Path(path)
            with target.open("xb"):
                pass
            self.created.append(target)
            return str(target)

        def WriteFile(self, handle, chunk, length, count_pointer, _overlapped):
            assert length == len(chunk)
            with Path(handle).open("ab") as stream:
                count = stream.write(chunk)
            count_pointer._obj.value = count
            return True

        def FlushFileBuffers(self, _handle):
            return True

        def CloseHandle(self, _handle):
            return True

    if candidate.os.name == "nt":
        fake_os = FakeOSLeaves(verified.private)
        monkeypatch.setattr(verified.private, "_API", fake_os)
        private_path = tmp_path / ("th01-helper-sourcefake-" + uuid4().hex)
        artifact_dir = verified.private.create_private_directory(private_path)
        digest = artifact_dir.write_json("page.json", {"sourcefake": True, "count": 1})
        artifact_dir.verify()
        assert fake_os.created == [private_path, private_path / "page.json"]
        assert (private_path / "page.json").read_text(encoding="utf-8") == '{"count": 1, "sourcefake": true}\n'
        assert digest == hashlib.sha256((private_path / "page.json").read_bytes()).hexdigest()


def test_loader_rejects_unpinned_owner_namespace_and_bad_module_names(monkeypatch):
    with pytest.raises(candidate.AccountWindowBlocked):
        candidate.load_verified_read_sources({"owner": "fake"})
    with pytest.raises(candidate.AccountWindowBlocked):
        candidate._compile_verified_module("backtrader_runtime.sneaky", OWNER_PATH, b"pass")

    failed_name = "_iteration41_th01_private_helper_r2_" + "0" * 32
    with pytest.raises(candidate.AccountWindowBlocked, match="source_module_load_failed"):
        candidate._compile_verified_module(failed_name, OWNER_PATH, b"raise RuntimeError()")
    assert failed_name not in sys.modules

    collision_name = "_iteration41_th01_private_helper_r2_" + "1" * 32
    collision = ModuleType(collision_name)
    monkeypatch.setitem(sys.modules, collision_name, collision)
    with pytest.raises(candidate.AccountWindowBlocked, match="source_module_input_invalid"):
        candidate._compile_verified_module(collision_name, OWNER_PATH, b"pass")
    assert sys.modules[collision_name] is collision

    current_owner = _load_exact_owner_sourcefake(monkeypatch)
    assert candidate._verify_owner_namespace(current_owner) is current_owner
    detached_owner = ModuleType("__main__")
    detached_owner.__dict__.update(current_owner.__dict__)
    with pytest.raises(candidate.AccountWindowBlocked, match="owner_transport_source_binding_invalid"):
        candidate._verify_owner_namespace(detached_owner)
    assert list(inspect.signature(candidate.create_root_read_candidate).parameters) == [
        "history_start_ms",
        "phase_cutoff_ms",
    ]


def test_bounded_source_rejects_reparse_ancestor_before_read(tmp_path, monkeypatch):
    root = tmp_path / "source-root"
    ancestor = root / "package"
    ancestor.mkdir(parents=True)
    source = ancestor / "module.py"
    raw = b"approved source bytes"
    source.write_bytes(raw)
    monkeypatch.setattr(candidate, "ROOT", root)
    original_lstat = Path.lstat

    def reparse_lstat(path):
        result = original_lstat(path)
        if path == ancestor:
            fields = {
                name: getattr(result, name)
                for name in (
                    "st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"
                )
            }
            fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0) | 0x400
            return SimpleNamespace(**fields)
        return result

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    with pytest.raises(candidate.AccountWindowBlocked, match="source_ancestor_shape_invalid"):
        candidate._bounded_source(source, hashlib.sha256(raw).hexdigest(), 100)


def test_bounded_source_rejects_path_identity_change_after_read(tmp_path, monkeypatch):
    root = tmp_path / "source-root"
    root.mkdir()
    source = root / "module.py"
    raw = b"approved source bytes"
    source.write_bytes(raw)
    monkeypatch.setattr(candidate, "ROOT", root)
    original_lstat = Path.lstat
    source_lstats = {"count": 0}

    def changed_lstat(path):
        result = original_lstat(path)
        if path == source:
            source_lstats["count"] += 1
            if source_lstats["count"] == 2:
                fields = {
                    name: getattr(result, name)
                    for name in (
                        "st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"
                    )
                }
                fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0)
                fields["st_mtime_ns"] += 1
                return SimpleNamespace(**fields)
        return result

    monkeypatch.setattr(Path, "lstat", changed_lstat)
    with pytest.raises(candidate.AccountWindowBlocked, match="source_changed_during_read"):
        candidate._bounded_source(source, hashlib.sha256(raw).hexdigest(), 100)


def test_bounded_source_rechecks_ancestor_reparse_state_after_read(tmp_path, monkeypatch):
    root = tmp_path / "source-root"
    ancestor = root / "package"
    ancestor.mkdir(parents=True)
    source = ancestor / "module.py"
    raw = b"approved source bytes"
    source.write_bytes(raw)
    monkeypatch.setattr(candidate, "ROOT", root)
    original_lstat = Path.lstat
    ancestor_lstats = {"count": 0}

    def reparse_after_read(path):
        result = original_lstat(path)
        if path == ancestor:
            ancestor_lstats["count"] += 1
            if ancestor_lstats["count"] == 2:
                fields = {
                    name: getattr(result, name)
                    for name in (
                        "st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink"
                    )
                }
                fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0) | 0x400
                return SimpleNamespace(**fields)
        return result

    monkeypatch.setattr(Path, "lstat", reparse_after_read)
    with pytest.raises(candidate.AccountWindowBlocked, match="source_ancestor_shape_invalid"):
        candidate._bounded_source(source, hashlib.sha256(raw).hexdigest(), 100)


def test_source_postflight_blocks_changed_candidate_or_dependency_pin(monkeypatch):
    first = candidate._verify_candidate_source_binding()
    source_hashes = candidate.source_preflight()
    monkeypatch.setattr(candidate, "_verify_candidate_source_binding", lambda: "0" * 64)
    with pytest.raises(candidate.AccountWindowBlocked, match="source_pin_mismatch"):
        candidate._verify_postflight_sources(first, source_hashes)


def test_source_postflight_blocks_changed_dependency_digest(monkeypatch):
    first = candidate._verify_candidate_source_binding()
    source_hashes = candidate.source_preflight()
    changed = dict(source_hashes)
    changed["backtrader_runtime/certification_roundtrip_private.py"] = "0" * 64
    monkeypatch.setattr(candidate, "source_preflight", lambda _root=candidate.ROOT: changed)
    with pytest.raises(candidate.AccountWindowBlocked, match="source_pin_mismatch"):
        candidate._verify_postflight_sources(first, source_hashes)


def test_oversized_response_metadata_is_recorded_without_archiving_body():
    class FakeWriter:
        def __init__(self):
            self.documents = []

        def append(self, document):
            self.documents.append(document)
            return uuid4().hex

    class FakeOwner:
        def _fixed_request_path(self, resource, query, _history_start, _now):
            return candidate.ROUTE_PATHS[resource], dict(query), False

        def _run_root_fixed_signed_get(self, *_args):
            return SimpleNamespace(
                body=b"x" * (candidate.MAX_PAGE_BYTES + 1),
                status=200,
                complete=True,
                reason=None,
                worker_exit_code=0,
                pipe_eof=True,
                forced_shutdown=False,
                started_at_ms=1_000,
                completed_at_ms=1_001,
            )

    writer = FakeWriter()
    auth = candidate.RootFixedGetAuthorizationV1(
        invocation_id="a" * 32,
        evidence_window_id="th01-window:" + "a" * 32,
        history_start_ms=1,
        phase_cutoff_ms=2,
        account_binding_ref="b" * 64,
        _credential_box=["synthetic-key-value", "synthetic-secret-value"],
        _writer=writer,
        _sources=SimpleNamespace(owner=FakeOwner(), source_hashes={}),
        _started_monotonic=time.monotonic(),
        _request_count=[0],
        _row_count=[0],
        _body_bytes=[0],
        _route_entries={},
        _route_completed={},
        _active_stage=["root_preflight"],
        _seal=candidate._READ_AUTH_SEAL,
    )
    reader = candidate.FixedGetReaderV1(auth, candidate._READ_SESSION_SEAL)

    with pytest.raises(candidate.AccountWindowBlocked, match="fixed_get_provider_response_unproven"):
        reader.current("account_configuration")

    assert len(writer.documents) == 1
    assert writer.documents[0]["response_body_b64"] == ""


def test_fixed_get_reader_full_candidate_flow_is_typed_but_not_account_full(monkeypatch):
    owner = _load_exact_owner_sourcefake(monkeypatch)
    verified = candidate.load_verified_read_sources(owner)
    writer_documents = []

    class FakeWriter:
        def append(self, document):
            writer_documents.append(document)
            return uuid4().hex

    bodies = {
        "account_configuration": {
            "canTrade": True,
            "dualSidePosition": False,
            "multiAssetsMargin": False,
        },
        "account_v2": {
            "assets": [{"asset": "USDT", "walletBalance": "50.00"}],
            "positions": [
                {"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": "0.1"}
            ],
        },
        "standard_open_orders": [],
        "algo_open_orders": [],
        "all_orders_in_window": [],
        "income_in_window": [],
        "user_trades_in_window": [],
    }
    transport_calls = []

    def fake_get(resource, query, *_args):
        transport_calls.append((resource, dict(query)))
        body = json.dumps(bodies[resource], sort_keys=True, separators=(",", ":")).encode("ascii")
        now_ms = int(time.time() * 1000)
        return SimpleNamespace(
            body=body,
            status=200,
            complete=True,
            reason=None,
            worker_exit_code=0,
            pipe_eof=True,
            forced_shutdown=False,
            started_at_ms=now_ms,
            completed_at_ms=now_ms + 1,
        )

    # Keep the accepted owner's real fixed query validator and replace only the
    # network leaf after exact source loading.
    owner._run_root_fixed_signed_get = fake_get
    invocation = uuid4().hex
    evidence_window = "th01-window:" + invocation
    start_ms = 1_000
    cutoff_ms = 1_200
    auth = candidate.RootFixedGetAuthorizationV1(
        invocation_id=invocation,
        evidence_window_id=evidence_window,
        history_start_ms=start_ms,
        phase_cutoff_ms=cutoff_ms,
        account_binding_ref="b" * 64,
        _credential_box=["synthetic-key-value", "synthetic-secret-value"],
        _writer=FakeWriter(),
        _sources=verified,
        _started_monotonic=time.monotonic(),
        _request_count=[0],
        _row_count=[0],
        _body_bytes=[0],
        _route_entries={},
        _route_completed={},
        _active_stage=["root_preflight"],
        _seal=candidate._READ_AUTH_SEAL,
    )
    reader = candidate.FixedGetReaderV1(auth, candidate._READ_SESSION_SEAL)
    result = candidate.collect_account_window_candidate(
        reader,
        invocation_ref=invocation,
        evidence_window_ref=evidence_window,
        history_start_ms=start_ms,
        phase_cutoff_ms=cutoff_ms,
    )
    public = result.public_document()

    assert [name for name, _query in transport_calls] == [
        "account_configuration",
        "account_v2",
        "standard_open_orders",
        "algo_open_orders",
        "all_orders_in_window",
        "income_in_window",
        "user_trades_in_window",
    ]
    assert transport_calls[-1][1] == {
        "symbol": "BTCUSDT",
        "startTime": start_ms - 1,
        "endTime": cutoff_ms,
        "limit": candidate.PAGE_LIMIT,
    }
    assert all(document["method"] == "GET" for document in writer_documents)
    assert public["status"] == "CANDIDATE_ONLY"
    assert public["user_trades_universe_closed"] is False
    assert public["account_full_snapshot_issued"] is False
    assert public["formal_case_pass"] is False
    assert public["candidate_symbol_user_trades_short_page_terminal_observed"] is True
    assert "50.00" not in json.dumps(public)
    assert "BTCUSDT" not in json.dumps(public)
    candidate._clear_root_credentials(auth, None)


def test_all_orders_time_bisection_splits_full_page_and_deduplicates_overlap():
    records = [_order(order_id=index + 1, when=1_000 + index) for index in range(1_000)]

    class Reader:
        def __init__(self):
            self.queries = []

        def all_orders(self, start_ms, end_ms):
            self.queries.append((start_ms, end_ms))
            return _page(
                "all_orders_in_window",
                [row for row in records if start_ms <= row["time"] <= end_ms],
            )

    reader = Reader()
    pages, selected = candidate._read_all_orders_bisected(reader, 1_000, 2_000)

    assert reader.queries == [(999, 2_000), (999, 1_500), (1_499, 2_000)]
    assert len(pages) == 3
    assert len(selected) == 1_000
    assert len({(row["symbol"], row["orderId"]) for row in selected}) == 1_000


def test_all_orders_saturated_one_millisecond_window_blocks():
    class Reader:
        def all_orders(self, _start_ms, _end_ms):
            return _page(
                "all_orders_in_window",
                [_order(order_id=index + 1, when=500) for index in range(candidate.PAGE_LIMIT)],
            )

    with pytest.raises(candidate.AccountWindowBlocked, match="all_orders_one_ms_saturated"):
        candidate._read_all_orders_bisected(Reader(), 500, 501)


def test_all_orders_changed_duplicate_across_padded_boundary_blocks():
    parent_rows = [_order(order_id=index + 10, when=1_000 + index) for index in range(1_000)]

    class Reader:
        def all_orders(self, start_ms, end_ms):
            if start_ms == 999 and end_ms == 2_000:
                return _page("all_orders_in_window", parent_rows)
            if start_ms == 999:
                return _page("all_orders_in_window", [_order(order_id=42, when=1_500, executed="0")])
            return _page("all_orders_in_window", [_order(order_id=42, when=1_500, executed="0.5")])

    with pytest.raises(candidate.AccountWindowBlocked, match="all_orders_conflicting_duplicate"):
        candidate._read_all_orders_bisected(Reader(), 1_000, 2_000)


def test_income_page_sequence_requires_short_terminal_page():
    first = [
        {
            "time": 1_100,
            "incomeType": "FUNDING_FEE",
            "tranId": index + 1,
            "asset": "USDT",
            "income": "0.001",
            "symbol": "",
        }
        for index in range(candidate.PAGE_LIMIT)
    ]

    class Reader:
        def __init__(self):
            self.pages = []

        def income(self, start, end, page_number):
            self.pages.append((start, end, page_number))
            terminal = [dict(first[0], tranId=1_001), dict(first[0], tranId=1_002)]
            return _page("income_in_window", first if page_number == 1 else terminal)

    reader = Reader()
    pages, rows = candidate._read_income_pages(reader, 1_000, 1_200)
    assert reader.pages == [(1_000, 1_199, 1), (1_000, 1_199, 2)]
    assert len(pages) == 2
    assert len(rows) == 1_002


def test_user_trades_uses_time_bounds_then_fromid_only_and_blocks_post_cutoff_row():
    first = [_trade("BTCUSDT", trade_id, 1_100) for trade_id in range(1, candidate.PAGE_LIMIT + 1)]
    continuation = [_trade("BTCUSDT", 1_001, 1_199)]

    class Reader:
        def __init__(self, final_rows):
            self.calls = []
            self.final_rows = final_rows

        def user_trades(self, symbol, start, end, from_id=None):
            self.calls.append((symbol, start, end, from_id))
            return _page("user_trades_in_window", first if from_id is None else self.final_rows)

    reader = Reader(continuation)
    pages, rows = candidate._read_user_trade_pages(reader, "BTCUSDT", 1_000, 1_200)
    assert reader.calls == [("BTCUSDT", 999, 1_200, None), ("BTCUSDT", 0, 0, 1_001)]
    assert len(pages) == 2 and len(rows) == 1_001

    late_reader = Reader([_trade("BTCUSDT", 1_001, 1_201)])
    with pytest.raises(candidate.AccountWindowBlocked, match="user_trades_row_outside_window"):
        candidate._read_user_trade_pages(late_reader, "BTCUSDT", 1_000, 1_200)
    assert late_reader.calls[1][1:] == (0, 0, 1_001)

    regressed_reader = Reader([_trade("BTCUSDT", 999, 1_199)])
    with pytest.raises(candidate.AccountWindowBlocked, match="user_trades_cursor_regressed"):
        candidate._read_user_trade_pages(regressed_reader, "BTCUSDT", 1_000, 1_200)


def test_candidate_projection_is_opaque_and_never_issues_account_full_or_pass():
    reader = _EmptyReader()
    result = candidate.collect_account_window_candidate(
        reader,
        invocation_ref="a" * 32,
        evidence_window_ref="th01-window:" + "a" * 32,
        history_start_ms=1_000,
        phase_cutoff_ms=1_200,
    )
    public = result.public_document()

    assert public["status"] == "CANDIDATE_ONLY"
    assert public["completed_route_observations"] == {
        "account_configuration": True,
        "account_v2": True,
        "standard_open_orders": True,
        "algo_open_orders": True,
        "all_orders_in_window": True,
        "user_trades_in_window": False,
        "income_in_window": True,
    }
    assert public["account_full_snapshot_issued"] is False
    assert public["formal_case_pass"] is False
    assert public["all_orders_time_partition_scan_completed"] is True
    assert public["income_short_page_terminal_observed"] is True
    assert public["user_trades_universe_closed"] is False
    assert "b" * 64 not in json.dumps(public)
    assert "BTCUSDT" not in json.dumps(public)
    assert "50.00" not in json.dumps(public)
    assert not hasattr(candidate, "attest_trade_universe")
    assert not hasattr(candidate, "_RootTradeUniverseCoverageV1")
    with pytest.raises(candidate.AccountWindowBlocked, match="account_full_attestation_unproven"):
        candidate.account_full_attestation(result, {"complete": True, "covered_symbols": []})


def test_cross_invocation_or_duplicate_page_refs_cannot_make_candidate():
    reader = _EmptyReader()
    original = reader.current

    def cross_invocation(resource):
        page = original(resource)
        if resource == "account_v2":
            page = _page(
                resource,
                page.rows,
                invocation="c" * 32,
                window="th01-window:" + "c" * 32,
            )
        return page

    reader.current = cross_invocation
    with pytest.raises(candidate.AccountWindowBlocked, match="account_window_page_binding_invalid"):
        candidate.collect_account_window_candidate(
            reader,
            invocation_ref="a" * 32,
            evidence_window_ref="th01-window:" + "a" * 32,
            history_start_ms=1_000,
            phase_cutoff_ms=1_200,
        )


def test_duplicate_request_response_refs_cannot_make_candidate():
    reader = _EmptyReader()
    original = reader.current

    def duplicate_refs(resource):
        page = original(resource)
        if resource in {"account_configuration", "account_v2"}:
            page = _page(resource, page.rows, request="c" * 32, response="d" * 32)
        return page

    reader.current = duplicate_refs
    with pytest.raises(candidate.AccountWindowBlocked, match="account_window_page_binding_invalid"):
        candidate.collect_account_window_candidate(
            reader,
            invocation_ref="a" * 32,
            evidence_window_ref="th01-window:" + "a" * 32,
            history_start_ms=1_000,
            phase_cutoff_ms=1_200,
        )


def test_retained_auth_reader_and_candidate_reprs_do_not_expose_credentials():
    auth = candidate.RootFixedGetAuthorizationV1(
        invocation_id="a" * 32,
        evidence_window_id="th01-window:" + "a" * 32,
        history_start_ms=1,
        phase_cutoff_ms=2,
        account_binding_ref="b" * 64,
        _credential_box=["synthetic-key-value", "synthetic-secret-value"],
        _writer=None,
        _sources=None,
        _started_monotonic=0.0,
        _request_count=[0],
        _row_count=[0],
        _body_bytes=[0],
        _route_entries={},
        _route_completed={},
        _active_stage=["root_preflight"],
        _seal=candidate._READ_AUTH_SEAL,
    )
    retained_credentials = {"api_key": "synthetic-key-value", "secret": "synthetic-secret-value"}
    reader = candidate.FixedGetReaderV1(auth, candidate._READ_SESSION_SEAL)
    candidate._clear_root_credentials(auth, retained_credentials)

    assert auth._credential_box == ["", ""]
    assert retained_credentials == {}
    assert "synthetic" not in repr(auth)
    assert "synthetic" not in repr(reader)
    projection = candidate._blocked_public_projection(
        "account_window_blocked", auth, account_read_started=True
    )
    assert "synthetic" not in json.dumps(projection)


def test_launcher_child_source_reexecution_resolves_fixed_worker_without_spawn(monkeypatch):
    source_bytes = DRIVER_PATH.read_bytes()
    child = ModuleType("__mp_main__")
    child.__file__ = str(DRIVER_PATH)
    child.__package__ = ""
    monkeypatch.setitem(sys.modules, "__mp_main__", child)
    monkeypatch.setitem(sys.modules, "__main__", child)

    exec(compile(source_bytes, str(DRIVER_PATH), "exec", dont_inherit=True), child.__dict__)

    worker = child.__dict__["_root_fixed_signed_get_worker"]
    assert worker.__module__ == "__mp_main__"
    assert Path(worker.__code__.co_filename).resolve() == OWNER_PATH.resolve()
    assert pickle.loads(pickle.dumps(worker)) is worker
    assert child.__dict__["__th01_verified_owner_source_sha256__"] == candidate.OWNER_SHA256
    assert child.__dict__["_CANDIDATE_MODULE"].__file__ == str(CANDIDATE_PATH)
    assert child.__dict__["_CANDIDATE_MODULE"].__th01_verified_candidate_source_sha256__ == hashlib.sha256(
        CANDIDATE_PATH.read_bytes()
    ).hexdigest()

