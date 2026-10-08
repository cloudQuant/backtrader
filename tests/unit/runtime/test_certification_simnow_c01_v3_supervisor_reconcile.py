"""Focused fake-only contracts for the V3 C01 worker Job reconciliation."""

from __future__ import annotations

import hashlib
import io
import json
import ast
import importlib.util
import re
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from backtrader_runtime import certification_simnow_c01_v3_supervisor as supervisor
from backtrader_runtime.certification_simnow_c01_v2_protocol import C01PairBinding


_SOURCE = b"# inert source used by the fake supervisor test\n"
_SOURCE_SHA256 = hashlib.sha256(_SOURCE).hexdigest()
_TD_FRONT = "tcp://127.0.0.1:12345"
_PAIR = C01PairBinding(
    selected_index=0,
    selection_sha256="c" * 64,
    md_front_sha256="d" * 64,
    td_front_sha256=hashlib.sha256(_TD_FRONT.encode("utf-8")).hexdigest(),
    td_front=_TD_FRONT,
    selected_at_utc="2026-10-08T00:00:00Z",
)


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration
        time.sleep(0)


class _CapturingWriter(io.BytesIO):
    def __init__(self) -> None:
        super().__init__()
        self.captured = b""

    def close(self) -> None:
        self.captured = self.getvalue()
        super().close()


class _FakePipes:
    def __init__(self) -> None:
        self.stdin_parent = _CapturingWriter()
        self.stdout_parent = io.BytesIO(b"")
        self.stderr_parent = io.BytesIO(b"")
        self.child_handles = (101, 102, 103)
        self.child_fds = ()
        self.child_closed = False
        self.parent_closed = False

    @property
    def handles_closed(self) -> bool:
        return self.child_closed and self.parent_closed

    def close_child_ends(self) -> bool:
        self.child_closed = True
        return True

    def close_parent_ends(self) -> bool:
        for stream in (self.stdin_parent, self.stdout_parent, self.stderr_parent):
            try:
                stream.close()
            except Exception:
                pass
        self.parent_closed = True
        return True


class _FakeSession:
    process_created = True
    job_assignment_observed = True

    def __init__(
        self,
        events: list[str],
        *,
        clock: _Clock,
        exit_code: int = 2,
        hang_until_terminated: bool = False,
        advance_on_first_poll: float = 0.0,
    ) -> None:
        self.events = events
        self.clock = clock
        self.exit_code = exit_code
        self.hang_until_terminated = hang_until_terminated
        self.advance_on_first_poll = advance_on_first_poll
        self.poll_count = 0
        self.terminated = False
        self.released = False
        self._process_handle = 99
        self._kernel32 = object()

    def resume_launcher(self) -> bool:
        self.events.append("resume")
        return True

    def poll_launcher_exit_code(self) -> Optional[int]:
        self.poll_count += 1
        if self.poll_count == 1:
            self.clock.now += self.advance_on_first_poll
        if self.hang_until_terminated:
            return 0xEE13 if self.terminated else None
        return self.exit_code

    def terminate_job(self) -> bool:
        self.events.append("terminate_job")
        self.terminated = True
        return True

    def terminate_launcher_process(self) -> bool:
        self.events.append("terminate_process")
        self.terminated = True
        return True

    def release_controls(self) -> bool:
        self.events.append("release")
        self.released = True
        return True


class _FakeBackend:
    def __init__(self, session: _FakeSession, events: list[str]) -> None:
        self.session = session
        self.events = events
        self.retained = False

    def create_suspended_in_job(self, command, *, deadline_monotonic: float):
        self.events.append("create_suspended_in_job")
        assert deadline_monotonic > 0
        return self.session

    def retain_controls(self, _session: _FakeSession) -> str:
        self.events.append("retain_controls")
        self.retained = True
        return "opaque-retention-token"


def _run_fake(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    clock: _Clock,
    job_count,
    cleanup_seconds: float,
    timeout_seconds: float = 0.2,
    hang_until_terminated: bool = False,
    advance_on_first_poll: float = 0.0,
):
    worker = tmp_path / "worker.py"
    worker.write_bytes(_SOURCE)
    events: list[str] = []
    session = _FakeSession(
        events,
        clock=clock,
        hang_until_terminated=hang_until_terminated,
        advance_on_first_poll=advance_on_first_poll,
    )
    backend = _FakeBackend(session, events)
    pipes = _FakePipes()
    monkeypatch.setattr(supervisor, "time", SimpleNamespace(
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    ))
    monkeypatch.setattr(supervisor, "_verified_interpreter_path", lambda: tmp_path / "python.exe")
    monkeypatch.setattr(supervisor, "_minimal_environment", lambda: {"SYSTEMROOT": "fake"})
    monkeypatch.setattr(supervisor, "_create_stdio_pipes", lambda: pipes)
    monkeypatch.setattr(supervisor, "_backend_for_handles", lambda _handles: backend)
    monkeypatch.setattr(supervisor, "_worker_pid", lambda _session: 7319)
    monkeypatch.setattr(supervisor, "_job_active_count", job_count)
    monkeypatch.setattr(supervisor.secrets, "token_hex", lambda _count: "a" * 32)
    result = supervisor.run_fixed_c01_worker(
        worker_path=worker,
        source_root=tmp_path,
        expected_worker_source_sha256=_SOURCE_SHA256,
        pair_binding=_PAIR,
        account_scope_sha256="4" * 64,
        credential_binding_sha256="5" * 64,
        credential_packet=b"fake-public-test-packet",
        timeout_seconds=timeout_seconds,
        cleanup_seconds=cleanup_seconds,
    )
    return result, backend, pipes, events


def test_nonzero_exit_reconciles_transient_job_count_before_termination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = _Clock()
    observations = iter((1, 0))

    def job_count(_session):
        return next(observations, 0)

    result, backend, pipes, events = _run_fake(
        monkeypatch,
        tmp_path,
        clock=clock,
        job_count=job_count,
        cleanup_seconds=0.1,
    )

    assert result.status == "BLOCKED"
    assert result.reason == "worker_exit_nonzero"
    assert result.worker_receipt is None
    assert result.process_lifecycle.process_exit_code == 2
    assert result.process_lifecycle.job_active_count == 0
    assert result.process_lifecycle.forced_kill is False
    assert result.process_lifecycle.stdout_eof is True
    assert result.process_lifecycle.stderr_eof is True
    assert result.process_lifecycle.handles_closed is True
    assert "terminate_job" not in events
    assert backend.session.released is True
    assert backend.retained is False
    assert pipes.handles_closed is True
    assert clock.now <= 100.1


def test_nonzero_exit_persistent_job_is_terminated_and_reaped_within_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = _Clock()

    def job_count(session):
        return 0 if session.terminated else 1

    result, backend, pipes, events = _run_fake(
        monkeypatch,
        tmp_path,
        clock=clock,
        job_count=job_count,
        cleanup_seconds=5.0,
    )

    assert result.status == "BLOCKED"
    assert result.reason == "worker_exit_nonzero"
    assert result.worker_receipt is None
    assert result.process_lifecycle.process_exit_code == 2
    assert result.process_lifecycle.job_active_count == 0
    assert result.process_lifecycle.forced_kill is True
    assert result.process_lifecycle.stdout_eof is True
    assert result.process_lifecycle.stderr_eof is True
    assert result.process_lifecycle.handles_closed is True
    assert events.index("terminate_job") < events.index("release")
    assert backend.retained is False
    assert pipes.handles_closed is True
    assert clock.now <= 105.0


def test_unknown_job_count_terminates_then_retains_when_zero_cannot_be_proven(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = _Clock()

    def job_count(_session):
        return None

    result, backend, pipes, events = _run_fake(
        monkeypatch,
        tmp_path,
        clock=clock,
        job_count=job_count,
        cleanup_seconds=5.0,
        timeout_seconds=0.05,
        advance_on_first_poll=0.075,
    )

    absolute_cleanup_deadline = 100.05 + 5.0
    assert result.status == "BLOCKED"
    assert result.reason == "native_close_unknown"
    assert result.worker_receipt is None
    assert result.process_lifecycle.job_active_count is None
    assert result.process_lifecycle.forced_kill is True
    assert result.process_lifecycle.handles_closed is False
    assert "terminate_job" in events
    assert backend.retained is True
    assert backend.session.released is False
    assert pipes.handles_closed is True
    assert clock.now <= absolute_cleanup_deadline + 1e-9


def test_existing_timeout_cleanup_still_kills_and_reaps_without_deadline_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = _Clock()

    def job_count(session):
        return 0 if session.terminated else 1

    result, backend, pipes, events = _run_fake(
        monkeypatch,
        tmp_path,
        clock=clock,
        job_count=job_count,
        cleanup_seconds=0.1,
        timeout_seconds=0.03,
        hang_until_terminated=True,
    )

    assert result.status == "BLOCKED"
    assert result.reason == "native_close_unknown"
    assert result.worker_receipt is None
    assert result.process_lifecycle.timed_out is True
    assert result.process_lifecycle.forced_kill is True
    assert result.process_lifecycle.job_active_count == 0
    assert result.process_lifecycle.handles_closed is True
    assert "terminate_job" in events
    assert backend.retained is False
    assert pipes.handles_closed is True
    assert clock.now <= 100.13


def test_v12_source_manifest_and_root_wrapper_bind_the_v3_supervisor():
    root = Path(__file__).resolve().parents[3]
    manifest_path = root / "backtrader_runtime/certification_simnow_c01_native_td_read_v12.sources.json"
    issuer_path = root / "backtrader_runtime/certification_simnow_c01_native_td_read_v12.py"
    schema_path = root / "backtrader_runtime/certification_simnow_c01_native_td_read_v12.admission.schema.json"
    owner_path = root / "backtrader_runtime/certification_simnow_c01_v4_owner.py"
    supervisor_path = root / "backtrader_runtime/certification_simnow_c01_v3_supervisor.py"
    runner_path = root / "examples/000_live_certification/simnow_penetration/cases/C01/run_v12.py"
    wrapper_path = root / "scripts/run_simnow_c01_native_td_read_v12_root_activation_r1.py"

    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("ascii"))
    assert manifest["profile_id"] == "C01_NATIVE_TD_READ_V12"
    assert manifest["admission_bound_files"] == [
        "backtrader_runtime/certification_simnow_c01_native_td_read_v12.py",
        "examples/000_live_certification/simnow_penetration/cases/C01/run_v12.py",
    ]
    source_files = manifest["source_files"]
    assert len(source_files) == 19
    for relative, expected in source_files.items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected

    issuer = issuer_path.read_text(encoding="utf-8")
    owner = owner_path.read_text(encoding="utf-8")
    wrapper = wrapper_path.read_text(encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    supervisor_sha = hashlib.sha256(supervisor_path.read_bytes()).hexdigest()
    owner_sha = hashlib.sha256(owner_path.read_bytes()).hexdigest()
    issuer_sha = hashlib.sha256(issuer_path.read_bytes()).hexdigest()
    schema_sha = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    runner_sha = hashlib.sha256(runner_path.read_bytes()).hexdigest()

    def literal(source: str, name: str) -> str:
        match = re.search(rf'^{re.escape(name)}\s*=\s*"([0-9a-f]{{64}})"$', source, re.MULTILINE)
        assert match is not None
        return match.group(1)

    assert literal(issuer, "_SOURCE_MANIFEST_SHA256") == manifest_sha
    assert literal(issuer, "_OWNER_SHA256") == owner_sha
    assert literal(issuer, "_SUPERVISOR_SHA256") == supervisor_sha
    assert literal(issuer, "_ADMISSION_SCHEMA_SHA256") == schema_sha
    assert source_files["backtrader_runtime/certification_simnow_c01_v4_owner.py"] == owner_sha
    assert source_files["backtrader_runtime/certification_simnow_c01_v3_supervisor.py"] == supervisor_sha
    assert '"backtrader_runtime/certification_simnow_c01_v3_supervisor.py"' in owner
    assert f'"{supervisor_sha}"' in owner
    assert literal(wrapper, "_V12_SHA256") == issuer_sha
    assert literal(wrapper, "_V12_MANIFEST_SHA256") == manifest_sha
    assert literal(wrapper, "_V12_SCHEMA_SHA256") == schema_sha
    assert literal(wrapper, "_CASE_RUNNER_SHA256") == runner_sha


def test_v12_root_front_loader_opens_exact_v12_bundle_and_runner_contract():
    root = Path(__file__).resolve().parents[3]
    wrapper_path = root / "scripts/run_simnow_c01_native_td_read_v12_root_activation_r1.py"
    runner_path = root / "examples/000_live_certification/simnow_penetration/cases/C01/run_v12.py"
    front_path = root / "backtrader_runtime/certification_simnow_c01_front_transport_v7.py"
    issuer_path = root / "backtrader_runtime/certification_simnow_c01_native_td_read_v12.py"
    wrapper_raw = wrapper_path.read_bytes()
    runner_raw = runner_path.read_bytes()
    front_raw = front_path.read_bytes()
    issuer_sha = hashlib.sha256(issuer_path.read_bytes()).hexdigest()

    wrapper_name = "_v12_public_root_wrapper_source_check"
    spec = importlib.util.spec_from_file_location(wrapper_name, wrapper_path)
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    sys.modules[wrapper_name] = wrapper
    try:
        spec.loader.exec_module(wrapper)
        assert wrapper.REPO_ROOT.resolve(strict=True) == root.resolve(strict=True)
        assert wrapper._V12_SHA256 == issuer_sha
        assert wrapper._FRONT_TRANSPORT_RELATIVE == (
            "backtrader_runtime/certification_simnow_c01_front_transport_v7.py"
        )
        assert wrapper._FRONT_TRANSPORT_SHA256 == hashlib.sha256(front_raw).hexdigest()
        assert wrapper._FRONT_MODULE_NAME not in sys.modules

        with wrapper._verified_v12_sources(root) as (bundle, policy, pinned_runner):
            front_module = sys.modules[wrapper._FRONT_MODULE_NAME]
            assert type(bundle) is front_module.VerifiedC01V12SourceBundle
            assert bundle._active is True
            assert bundle.issuer.PROFILE_ID == "C01_NATIVE_TD_READ_V12"
            assert bundle.issuer.__c01_source_sha256__ == issuer_sha
            assert policy == wrapper._EXPECTED_SOURCE_POLICY
            assert pinned_runner == runner_raw
            assert set(bundle.helpers) == front_module._EXPECTED_HELPERS | {"owner_now_utc"}
            assert (
                bundle.owner._SOURCE_PINS["scripts/ctp_000_paired_front_selector.py"]
                == "08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb"
            )

        runner_tree = ast.parse(runner_raw.decode("utf-8"))
        issuer_assignments = [
            node
            for node in runner_tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "ISSUER_SHA256" for target in node.targets)
        ]
        assert len(issuer_assignments) == 1
        assert isinstance(issuer_assignments[0].value, ast.Constant)
        assert issuer_assignments[0].value.value == issuer_sha
        assert wrapper._CASE_RUNNER_SHA256 == hashlib.sha256(runner_raw).hexdigest()
    finally:
        sys.modules.pop(wrapper_name, None)
