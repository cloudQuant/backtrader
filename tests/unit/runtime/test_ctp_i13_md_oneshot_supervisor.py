"""Offline contracts for the unregistered I13 MD-only supervisor candidate."""

from __future__ import annotations

import json
import hashlib
import importlib
import py_compile
import sys
import time
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from backtrader_runtime import ctp_i13_md_oneshot_supervisor as i13
from backtrader_runtime import ctp_i13_source_identity as i13_source
from backtrader_runtime.ctp_artifact_provenance import (
    CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS,
)
from backtrader_runtime.ctp_i12_td_only_readonly import I12FrontPrecheckBinding
from backtrader_runtime import ctp_i12_td_only_readonly as i12
from backtrader_runtime import ctp_i11_oneshot_md_diagnostic as i11
from backtrader_runtime import ctp_simnow_operator as simnow_operator
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontPairSelection,
)
from backtrader_runtime.ctp_readonly_job_supervisor import (
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
)
from backtrader_runtime.errors import RuntimeConfigError


@contextmanager
def _without_cached_capability_modules():
    cached = {
        name: module
        for name, module in sys.modules.items()
        if isinstance(name, str) and name.split(".", 1)[0].startswith("bt_api_")
    }
    for name in cached:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in tuple(sys.modules):
            if isinstance(name, str) and name.split(".", 1)[0].startswith("bt_api_"):
                sys.modules.pop(name, None)
        sys.modules.update(cached)


def _success_receipt(config_index: int = 1) -> dict[str, object]:
    return {
        "adapter_ack_tick_order": "ack_before_all_ticks",
        "adapter_acknowledgement_state": "acknowledged",
        "adapter_accepted_tick_count": "one",
        "adapter_evidence_integrity": "valid",
        "adapter_login_identity_state": "verified",
        "adapter_native_join_state": "completed",
        "adapter_primary_probe_reason": "matching_tick_observed",
        "adapter_same_trading_day_observed": True,
        "adapter_tick_arrival_count": "one",
        "adapter_tick_classification": "tick_accepted",
        "client_stop_returned": True,
        "close_state": "verified_closed",
        "credential_resolver_invoked": True,
        "diagnostic_id": "i13_oneshot_md_diagnostic",
        "native_join_pending": False,
        "order_submission_authorized": False,
        "parent_precheck_binding_match": True,
        "probe_session_closed": True,
        "reason": "matching_tick_observed",
        "sdk_broker_id_shape": "exact_match",
        "sdk_evidence_integrity": "valid",
        "sdk_first_tick_pending": False,
        "sdk_first_tick_received": True,
        "sdk_imported": True,
        "source_identity_verified": True,
        "sdk_login_callback_count": "one",
        "sdk_login_disposition": "accepted",
        "sdk_native_broker_id_shape": "nonempty_terminated",
        "sdk_native_user_id_shape": "nonempty_terminated",
        "sdk_receipt_observed": True,
        "sdk_receipt_terminal_state": "complete",
        "sdk_request_id_relation": "zero",
        "sdk_response_error_status": "zero",
        "sdk_subscription_acknowledged": True,
        "sdk_subscription_error_status": "zero",
        "sdk_subscription_submitted": True,
        "sdk_trading_day_shape": "valid",
        "sdk_user_id_shape": "exact_match",
        "selected_pair_index": f"pair_{config_index}",
        "settlement_writes_zero": True,
        "stage": "market_data",
        "status": "diagnostic_complete",
        "trading_ready": False,
        "trading_writes_zero": True,
    }


def _clean_process_evidence() -> ProcessEvidence:
    return ProcessEvidence(True, True, True, True, 0, False, None, True, "verified")


def _complete_result(config_index: int = 1) -> SupervisedResult:
    return SupervisedResult(
        "child_exited",
        "child_process_exited",
        _success_receipt(config_index),
        _clean_process_evidence(),
    )


def _artifact_result(*, verified: bool = True) -> SupervisedResult:
    evidence = _clean_process_evidence()
    return SupervisedResult(
        "child_exited",
        "child_process_exited",
        {
            "credential_resolver_invoked": False,
            "native_join_pending": False,
            "reason": "artifact_verified" if verified else "artifact_rejected",
            "sdk_imported": False,
            "source_identity_verified": True,
            "status": "verified" if verified else "rejected",
        },
        evidence,
    )


def _fake_source_lease() -> i13_source.I13SourceLease:
    return i13_source.I13SourceLease(
        SimpleNamespace(CloseHandle=lambda _handle: True),
        [],
        i13.I13_SOURCE_MANIFEST_SHA256,
        Path(tempfile.mkdtemp(prefix="fake-i13-pycache-")),
    )


def test_i13_pin_table_matches_the_independently_audited_wheel_identity() -> None:
    base = CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS["bt_api_base"]
    ctp = CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS["bt_api_ctp"]
    assert i13.I13_SDK_SOURCE_COMMIT == "c68bebe8631419801e7a24e13b98c42867df0beb"
    assert (base.version, base.wheel_sha256, base.record_sha256) == (
        "0.15.5",
        "2f413f7e914c4bbd1dcd47b3b95a3fb36e224dda2c4db97bdda35bf61797ad68",
        "6f73003cdba8f15468faa0264eb99c81578e6648c00ebf5de4c7161c676f7113",
    )
    assert (ctp.version, ctp.wheel_sha256, ctp.record_sha256) == (
        "2.0.3+iteration41.i13",
        "c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d",
        "d21876f577927651a585ad7273c5bdcf508d65766f2a05e2f5a06c8a29798217",
    )


def test_i13_source_hash_rejects_source_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "checkout"
    runtime = source_root / "backtrader_runtime"
    runtime.mkdir(parents=True)
    source = runtime / "sample.py"
    source.write_bytes(b"VALUE = 1\n")
    expected = {"backtrader_runtime/sample.py": hashlib.sha256(source.read_bytes()).hexdigest()}

    i13_source._verify_i13_source_files(source_root, expected)
    source.write_bytes(b"VALUE = 2\n")

    with pytest.raises(i13_source.I13SourceIdentityError, match="source_digest_mismatch"):
        i13_source._verify_i13_source_files(source_root, expected)


def test_i13_source_inventory_rejects_unlisted_modules_and_validates_cache_names(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    runtime = source_root / "backtrader_runtime"
    runtime.mkdir(parents=True)
    (runtime / "listed.py").write_text("VALUE = 1\n", encoding="utf-8")
    listed = {"backtrader_runtime/listed.py"}
    i13_source._require_i13_source_inventory(source_root, listed)

    (runtime / "unlisted.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(
        i13_source.I13SourceIdentityError, match="source_manifest_file_set_mismatch"
    ):
        i13_source._require_i13_source_inventory(source_root, listed)
    (runtime / "unlisted.py").unlink()
    cache = runtime / "__pycache__"
    cache.mkdir()
    cache_name = f"listed.{sys.implementation.cache_tag}.pyc"
    expected_cache = cache / cache_name
    py_compile.compile(str(runtime / "listed.py"), cfile=str(expected_cache), doraise=True)
    assert expected_cache.parent == cache
    assert i13_source._verify_runtime_python_caches(source_root) == {expected_cache}

    stale = cache / f"other.cpython-{sys.implementation.cache_tag.split('-', 1)[1]}.pyc"
    stale.write_bytes(b"fake bytecode")
    with pytest.raises(
        i13_source.I13SourceIdentityError, match="source_bytecode_cache_unverifiable"
    ):
        i13_source._verify_runtime_python_caches(source_root)


def test_i13_source_only_loader_never_uses_a_stale_cached_code_object(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    runtime = source_root / "backtrader_runtime"
    runtime.mkdir(parents=True)
    (runtime / "__init__.py").write_text("\n", encoding="utf-8")
    source = runtime / "late_module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    cache_dir = runtime / "__pycache__"
    cache_dir.mkdir()
    py_compile.compile(
        str(source),
        cfile=str(cache_dir / f"late_module.{sys.implementation.cache_tag}.pyc"),
        doraise=True,
    )
    source.write_text("VALUE = 2\n", encoding="utf-8")

    finder = i13_source._I13SourceOnlyFinder(source_root)
    spec = finder.find_spec("backtrader_runtime.late_module")
    assert spec is not None
    assert isinstance(spec.loader, i13_source._I13SourceOnlyLoader)
    loaded = spec.loader.get_code("backtrader_runtime.late_module")
    assert loaded.co_consts == (2, None)


def test_i13_source_inventory_rejects_native_sibling_before_import(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "checkout"
    runtime = source_root / "backtrader_runtime"
    runtime.mkdir(parents=True)
    module_name = "backtrader_runtime.injected_native"
    side_effect = tmp_path / "module-imported"
    (runtime / "injected_native.py").write_text(
        f"from pathlib import Path\nPath({str(side_effect)!r}).touch()\n", encoding="utf-8"
    )
    (runtime / "injected_native.pyd").write_bytes(b"not executable")

    with pytest.raises(
        i13_source.I13SourceIdentityError, match="source_importable_artifact_present"
    ):
        i13_source._verify_runtime_python_caches(source_root)
        importlib.import_module(module_name)

    assert module_name not in sys.modules
    assert not side_effect.exists()


def test_i13_job_bootstrap_verifies_sources_before_local_imports() -> None:
    bootstrap = i13._i13_source_guard_code(Path.cwd())
    compile(bootstrap, "i13-source-guard", "exec")
    assert bootstrap.index("hashlib.sha256(_i13_manifest_raw)") < bootstrap.index(
        "sys.path.insert(0, _i13_root)"
    )
    assert "__pycache__" in bootstrap
    assert ".pyc" in bootstrap
    assert "_i13_actual_names != set(_i13_files) | _i13_expected_names" in bootstrap
    assert "sys.flags.isolated != 1" in bootstrap
    assert "sys.flags.no_site != 1" in bootstrap
    assert "not sys.dont_write_bytecode" in bootstrap
    assert "sys.pycache_prefix" in bootstrap
    assert "_i13_prefix_entries" in bootstrap
    assert "_I13SourceOnlyFinder" in bootstrap
    assert bootstrap.index("sys.meta_path.insert") < bootstrap.index("sys.path.insert")
    assert "'.pyd'" in bootstrap


def test_i13_metadata_verifier_adds_only_the_code_owned_venv_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    system_root = tmp_path / "system-site-packages"
    original_roots = (system_root,)
    provenance = SimpleNamespace(_interpreter_install_roots=lambda: original_roots)
    monkeypatch.setitem(
        sys.modules,
        "backtrader_runtime.ctp_artifact_provenance",
        provenance,
    )
    monkeypatch.setattr(i13, "_I13_RUNTIME_ROOT", venv)
    seen: list[tuple[Path, ...]] = []

    result = i13._verify_i13_at_fixed_install_root(
        lambda: seen.append(provenance._interpreter_install_roots()) or "verified"
    )

    assert result == "verified"
    assert seen == [(site_packages,)]
    assert provenance._interpreter_install_roots() == original_roots


def test_i13_capability_origin_fence_uses_only_the_fixed_venv_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    for module_name in ("bt_api_base", "bt_api_ctp"):
        package = site_packages / module_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(i13, "_I13_RUNTIME_ROOT", venv)
    capability_imports = importlib.import_module("backtrader_runtime.capability_imports")
    original_roots = capability_imports._concrete_interpreter_install_roots

    with _without_cached_capability_modules(), i13._trusted_i13_installed_capability_import_context(
        ("bt_api_base", "bt_api_ctp")
    ):
        finder = next(
            entry
            for entry in sys.meta_path
            if isinstance(entry, capability_imports._CapabilityImportFinder)
        )
        assert finder._resolver.search_roots == (site_packages,)
        assert capability_imports._concrete_interpreter_install_roots is original_roots

    assert capability_imports._concrete_interpreter_install_roots is original_roots


def test_i13_capability_origin_fence_rejects_a_preloaded_ambient_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    for module_name in ("bt_api_base", "bt_api_ctp"):
        package = site_packages / module_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    ambient_package = tmp_path / "ambient" / "bt_api_base"
    ambient_package.mkdir(parents=True)
    ambient_init = ambient_package / "__init__.py"
    ambient_init.write_text("", encoding="utf-8")
    monkeypatch.setattr(i13, "_I13_RUNTIME_ROOT", venv)

    with _without_cached_capability_modules():
        preloaded = ModuleType("bt_api_base")
        preloaded.__file__ = str(ambient_init)
        preloaded.__path__ = [str(ambient_package)]
        sys.modules["bt_api_base"] = preloaded
        with pytest.raises(
            RuntimeConfigError, match="capability_origin_mismatch"
        ), i13._trusted_i13_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            pytest.fail("a preloaded ambient SDK module must fail the origin fence")


def test_i13_capability_origin_fence_rejects_sys_path_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    ambient = tmp_path / "ambient"
    for module_name in ("bt_api_base", "bt_api_ctp"):
        package = ambient / module_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(i13, "_I13_RUNTIME_ROOT", venv)
    monkeypatch.syspath_prepend(str(ambient))

    with pytest.raises(
        RuntimeConfigError, match="capability_origin_unavailable"
    ), i13._trusted_i13_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
        pytest.fail("the exact fixed root must not fall back to ambient sys.path")


def test_child_receipt_parser_rejects_extra_values_and_preserves_i13_identity() -> None:
    receipt = _success_receipt()
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert i13.parse_i13_child_receipt(encoded) == receipt

    tainted = dict(receipt, password="must-not-cross-the-receipt-boundary")
    encoded_tainted = json.dumps(tainted, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert i13.parse_i13_child_receipt(encoded_tainted) is None


@pytest.mark.parametrize(
    "receipt_change,evidence_change,retained",
    [
        ({"adapter_login_identity_state": "identity_unverified"}, None, None),
        ({"adapter_accepted_tick_count": "unknown"}, None, None),
        ({"adapter_same_trading_day_observed": None}, None, None),
        ({"native_join_pending": True}, None, None),
        (None, {"containment": "uncertain"}, None),
        (None, {"job_empty_observed": False}, None),
        (None, None, object()),
    ],
)
def test_parent_rejects_missing_or_uncertain_completion_evidence(
    receipt_change: dict[str, object] | None,
    evidence_change: dict[str, object] | None,
    retained: object,
) -> None:
    good = _complete_result()
    receipt = dict(good.sdk_receipt or {})
    evidence = good.process_evidence
    if receipt_change:
        receipt.update(receipt_change)
    if evidence_change:
        evidence = ProcessEvidence(
            evidence.process_created,
            evidence.job_assignment_observed,
            evidence.process_resumed,
            evidence.process_exit_observed,
            evidence.process_exit_code,
            evidence.job_termination_requested,
            evidence.job_termination_call_succeeded,
            evidence_change.get("job_empty_observed", evidence.job_empty_observed),
            evidence_change.get("containment", evidence.containment),
        )
    candidate = SupervisedResult(good.status, good.reason, receipt, evidence, retained)
    assert i13._parent_confirms_i13_diagnostic(candidate, 1) is False


def test_parent_accepts_only_the_exact_i13_receipt_and_verified_job_cleanup() -> None:
    assert i13._parent_confirms_i13_diagnostic(_complete_result(), 1) is True
    assert i13._parent_confirms_i13_diagnostic(_complete_result(), 2) is False


def test_public_report_separates_sdk_receipt_adapter_events_and_close_evidence() -> None:
    report = i13.I13DiagnosticReport(
        "diagnostic_complete",
        "matching_tick_observed",
        True,
        1,
        True,
        "verified",
        _complete_result(),
    )
    public = report.as_public_dict()
    assert public["diagnostic_id"] == "i13_oneshot_md_diagnostic"
    assert public["scope"] == "unregistered_programmatic_candidate"
    assert public["scope"] == "unregistered_programmatic_candidate"
    assert public["source_identity"] == {
        "bound": False,
        "manifest_sha256": None,
        "status": "current_checkout_source_unsealed",
    }
    assert "sdk_evidence_integrity" in public["diagnostic_receipt"]
    assert not any(key.startswith("adapter_") for key in public["diagnostic_receipt"])
    assert "adapter_accepted_tick_count" in public["adapter_observability"]
    assert "native_join_pending" in public["adapter_close_evidence"]


def test_supervisor_uses_one_deadline_and_only_a_fake_i13_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The injected OS facade lets the fake orchestration test exercise the
    # Windows-only path without creating a real marker or Job process.
    i13_os = SimpleNamespace(name="nt")
    binding = I12FrontPrecheckBinding(1, "a" * 64)
    precheck_deadlines: list[float] = []
    runner_deadlines: list[float] = []
    latch_paths: list[Path] = []
    call_order: list[str] = []
    fake_latch = SimpleNamespace(begin_attempt=lambda: True)
    command = FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})
    monkeypatch.setattr(i13, "verify_i13_runtime_import_origins", lambda _root: None)

    def fake_precheck(deadline: float) -> I12FrontPrecheckBinding:
        assert call_order == ["source_identity"]
        call_order.append("precheck")
        precheck_deadlines.append(deadline)
        return binding

    def fake_source_lease(*_args: object, **_kwargs: object) -> i13_source.I13SourceLease:
        call_order.append("source_identity")
        return _fake_source_lease()

    def fake_latch_factory(path: Path) -> object:
        latch_paths.append(path)
        return fake_latch

    def fake_runner(
        _command: FixedChildCommand, _parser: object, **kwargs: object
    ) -> SupervisedResult:
        deadline = kwargs["deadline_monotonic"]
        assert type(deadline) is float
        runner_deadlines.append(deadline)
        assert _command.env[i13._I13_SOURCE_MANIFEST_ENV] == i13.I13_SOURCE_MANIFEST_SHA256
        cache_prefix = Path(_command.env[i13._I13_PYCACHE_PREFIX_ENV])
        assert cache_prefix.name.startswith("fake-i13-pycache-")
        if kwargs["receipt_schema"] is i13._I13_ARTIFACT_PREFLIGHT_SCHEMA:
            return _artifact_result()
        assert kwargs["fail_closed_latch"] is fake_latch
        assert float(_command.env[i13._I13_DEADLINE_ENV]) == deadline
        return _complete_result()

    previous_os = i13.os
    i13.os = i13_os
    try:
        report = i13._supervise_i13_child(
            precheck=fake_precheck,
            command_builder=lambda _binding: command,
            artifact_command_builder=lambda worker: worker,
            latch_factory=fake_latch_factory,
            runner=fake_runner,
            source_lease_factory=fake_source_lease,
        )
    finally:
        i13.os = previous_os

    assert report.status == "diagnostic_complete", report.reason
    assert report.attempt_reserved is True
    assert len(precheck_deadlines) == 1
    assert runner_deadlines == [precheck_deadlines[0], precheck_deadlines[0]]
    assert call_order == ["source_identity", "precheck"]
    assert latch_paths == [i13.I13_LATCH_PATH]
    assert i13.I13_LATCH_PATH.name == "i13-md-oneshot-supervisor-no-retry.latch"


def test_failed_artifact_preflight_never_reserves_the_i13_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_os = i13.os
    i13.os = SimpleNamespace(name="nt")
    binding = I12FrontPrecheckBinding(1, "b" * 64)
    monkeypatch.setattr(i13, "verify_i13_runtime_import_origins", lambda _root: None)
    latch_paths: list[Path] = []
    command = FixedChildCommand((sys.executable, "-c", "pass"), Path.cwd(), {})

    def fake_runner(
        _command: FixedChildCommand, _parser: object, **kwargs: object
    ) -> SupervisedResult:
        assert kwargs["receipt_schema"] is i13._I13_ARTIFACT_PREFLIGHT_SCHEMA
        return _artifact_result(verified=False)

    try:
        report = i13._supervise_i13_child(
            precheck=lambda _deadline: binding,
            command_builder=lambda _binding: command,
            artifact_command_builder=lambda _worker: command,
            latch_factory=lambda path: latch_paths.append(path),
            runner=fake_runner,
            source_lease_factory=lambda *_args, **_kwargs: _fake_source_lease(),
        )
    finally:
        i13.os = previous_os

    assert report.reason == "sdk_artifact_rejected"
    assert report.attempt_reserved is False
    assert latch_paths == []


def test_event_instrumentation_uses_only_fake_client_callbacks() -> None:
    fake_base = type(
        "OneShotMdDiagnosticClient",
        (),
        {
            "__module__": "bt_api_ctp.ctp.client",
            "__init__": lambda self: setattr(self, "diagnostic_subscription_acknowledged", False),
        },
    )
    events = i13._I13EventRecorder()
    holder: dict[str, object] = {}
    tracked_type = i13._tracked_i13_client_type(fake_base, events, holder)
    client = tracked_type()

    def on_subscribe() -> None:
        client.diagnostic_subscription_acknowledged = True

    client.on_subscribe = on_subscribe
    client.on_subscribe()
    client.on_tick = lambda: None
    client.on_tick()
    assert [event.kind for event in events.snapshot()] == [
        i13.I13EventKind.SUBSCRIPTION_ACKNOWLEDGED,
        i13.I13EventKind.TICK_ARRIVED,
    ]


def test_tick_day_confirmation_is_emitted_only_from_adapter_day_evidence() -> None:
    no_day = i13._I13EventRecorder()
    no_day.tick_arrived()
    no_day.accept_observed_tick(same_trading_day=False)
    assert [event.kind for event in no_day.snapshot()] == [
        i13.I13EventKind.TICK_ARRIVED,
        i13.I13EventKind.TICK_ACCEPTED,
    ]

    same_day = i13._I13EventRecorder()
    same_day.tick_arrived()
    same_day.accept_observed_tick(same_trading_day=True)
    assert [event.kind for event in same_day.snapshot()] == [
        i13.I13EventKind.TICK_ARRIVED,
        i13.I13EventKind.TICK_ACCEPTED,
        i13.I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED,
    ]


def test_child_passes_i12_binding_environment_to_its_single_consumer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    front_pair = {"md_front": "tcp://127.0.0.1:10131", "td_front": "tcp://127.0.0.1:10130"}
    front_pairs = (front_pair,)
    effective = SimpleNamespace(
        effective_digest="a" * 64,
        registration=SimpleNamespace(digest="b" * 64),
    )
    expected = i12._front_binding_digest(
        effective_digest=effective.effective_digest,
        registration_digest=effective.registration.digest,
        config_index=0,
        md_front=front_pair["md_front"],
        td_front=front_pair["td_front"],
    )
    selected_pair = CtpConfiguredFrontPair(
        md_front=front_pair["md_front"], td_front=front_pair["td_front"]
    )
    child_selection = CtpFrontPairSelection(
        pair=selected_pair,
        config_index=0,
        latency_score_ms=0.0,
        evidence=(),
        timeout_seconds=1.0,
        repeated_samples=1,
    )

    class FakeBinding:
        def _route(self, *_args: object, **_kwargs: object) -> tuple[object, object]:
            return (
                SimpleNamespace(
                    td_front=front_pair["td_front"],
                    md_front=front_pair["md_front"],
                    instrument_id="IF2606",
                    exchange_id="CFFEX",
                    hedge_flag="1",
                ),
                object(),
            )

    private = SimpleNamespace(instrument_id="IF2606", exchange_id="CFFEX", hedge_flag="1")
    fake_binding = FakeBinding()
    registry = object()
    monkeypatch.setattr(i13, "_has_supervised_i13_attempt_context", lambda: True)
    monkeypatch.setattr(
        i13,
        "verify_i13_source_identity",
        lambda *_args, **_kwargs: i13.I13_SOURCE_MANIFEST_SHA256,
    )
    monkeypatch.setattr(i13, "verify_i13_runtime_import_origins", lambda *_args: None)
    monkeypatch.setattr(i13, "logging", SimpleNamespace(CRITICAL=50, disable=lambda _level: None))
    monkeypatch.setattr(i13, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(i13, "validate_runtime_config", lambda *_args: effective)
    monkeypatch.setattr(i13, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(
        i11,
        "_require_exact_child_scope",
        lambda *_args: (None, None, fake_binding, private, front_pairs),
    )
    monkeypatch.setattr(i11, "_front_pair", lambda pair: (pair["td_front"], pair["md_front"]))
    monkeypatch.setattr(
        i12,
        "_load_sealed_context",
        lambda: (effective, registry, None, private, front_pairs),
    )
    monkeypatch.setattr(
        simnow_operator,
        "_select_configured_front_pair",
        lambda _pairs: child_selection,
    )

    monkeypatch.setenv(i13._I13_DEADLINE_ENV, repr(time.monotonic() + 60.0))
    monkeypatch.setenv(i13._I13_SOURCE_MANIFEST_ENV, i13.I13_SOURCE_MANIFEST_SHA256)
    monkeypatch.setenv(i13._I12_PRECHECK_INDEX_ENV, "0")
    monkeypatch.setenv(i13._I12_PRECHECK_BINDING_ENV, expected.binding_sha256)
    expiration_checks = 0

    def expire_after_binding(_deadline: float) -> bool:
        nonlocal expiration_checks
        expiration_checks += 1
        return expiration_checks > 2

    monkeypatch.setattr(i13, "_i13_deadline_expired", expire_after_binding)
    assert i13._run_i13_child_impl(()) == 2
    receipt = i13.parse_i13_child_receipt(capsys.readouterr().out.encode())

    assert receipt is not None
    assert receipt["reason"] == "child_deadline_exceeded"
    assert receipt["parent_precheck_binding_match"] is True
    assert i13._I12_PRECHECK_INDEX_ENV not in i13.os.environ
    assert i13._I12_PRECHECK_BINDING_ENV not in i13.os.environ
    assert expiration_checks == 4
