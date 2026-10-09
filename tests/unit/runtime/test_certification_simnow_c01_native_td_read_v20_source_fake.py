"""Source-fake checks for the controlled C01 V20 pipeline boundary."""

from __future__ import annotations

import ast
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER_PATH = REPO_ROOT / "scripts" / "run_simnow_c01_native_td_read_v20_root_activation_r1.py"
DRIVER_PATH = REPO_ROOT / "scripts" / "iteration41_simnow_c01_v20_root_actual_driver_r1.py"
ISSUER_PATH = REPO_ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v20.py"
RUNNER_PATH = (
    REPO_ROOT
    / "examples"
    / "000_live_certification"
    / "simnow_penetration"
    / "cases"
    / "C01"
    / "run_v20.py"
)


def _load_wrapper() -> ModuleType:
    raw = WRAPPER_PATH.read_bytes()
    module = ModuleType("scripts.run_simnow_c01_native_td_read_v20_root_activation_r1")
    module.__file__ = str(WRAPPER_PATH)
    module.__package__ = "scripts"
    module.__c01_source_sha256__ = hashlib.sha256(raw).hexdigest()
    exec(compile(raw, str(WRAPPER_PATH), "exec", dont_inherit=True), module.__dict__)
    return module


def _load_driver() -> ModuleType:
    raw = DRIVER_PATH.read_bytes()
    module = ModuleType("_c01_v20_root_actual_driver")
    module.__file__ = str(DRIVER_PATH)
    module.__package__ = ""
    exec(compile(raw, str(DRIVER_PATH), "exec", dont_inherit=True), module.__dict__)
    return module


def _root_scope_module() -> tuple[ModuleType, object]:
    root = ModuleType("backtrader_runtime.certification_simnow_c01_root_v17")
    scope_type = type("C01RootInvocationScope", (), {})
    root.C01RootInvocationScope = scope_type
    scope = scope_type()
    scope.root_module = root
    scope.active = True
    scope.consumed = False
    scope.issuer_returned = False
    scope.stage_count = 0
    scope.root_content_stage = None
    scope.pending = None
    scope.root_content_seal = None
    return root, scope


def test_candidate_projection_is_fixed_blocked_and_parent_facts_stay_null():
    wrapper = _load_wrapper()
    projection = wrapper._child_projection(
        reason="candidate_root_handoff_written",
        receipt_verified=True,
        source_closure_verified=True,
        root_postverify_verified=True,
        counts={
            "request_count": 8,
            "query_callback_count": 6,
            "snapshot_count": 2,
            "write_invocation_count": 0,
        },
    )

    assert wrapper._validate_candidate_projection(projection, require_success=True)
    assert projection["certification"] == "BLOCKED"
    assert projection["write_policy"] == "NO_WRITE"
    assert projection["writes"] == 0
    assert all(projection[key] is None for key in wrapper._PARENT_ONLY_KEYS)

    promoted = dict(projection, certification="PASS")
    assert not wrapper._validate_candidate_projection(promoted, require_success=False)
    preclaimed = dict(projection, stdout_eof=True)
    assert not wrapper._validate_candidate_projection(preclaimed, require_success=False)

    raw = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert wrapper._canonical_projection(raw) == projection
    assert wrapper._canonical_projection(raw + b"\n") is None


def test_parent_call_receipt_binds_the_candidate_to_exact_process_and_frame():
    wrapper = _load_wrapper()
    driver = _load_driver()
    root_path = Path("D:/source_code/backtrader")
    handoff_raw = wrapper._read_public_source(
        root_path,
        wrapper._HANDOFF_PATH,
        expected_sha256=wrapper._ROOT_STATIC_SOURCE_PINS[wrapper._HANDOFF_PATH],
    )
    handoff = wrapper._load_module_from_bytes(
        root_path,
        wrapper._HANDOFF_PATH,
        "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1",
        handoff_raw,
        register_for_exec=True,
    )
    projection = wrapper._child_projection(
        reason="candidate_root_handoff_written",
        receipt_verified=True,
        source_closure_verified=True,
        root_postverify_verified=True,
        counts={
            "request_count": 8,
            "query_callback_count": 6,
            "snapshot_count": 2,
            "write_invocation_count": 0,
        },
    )
    projection_raw = json.dumps(
        projection,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    frame = handoff.RootContentFrame(b"source-fake-frame", handoff._FRAME_FACTORY)
    parent_receipt = driver.create_c01_v20_parent_process_receipt(
        frame=frame,
        handoff_module=handoff,
        call_nonce=object(),
        stdout_raw=projection_raw,
        stderr_raw=b"",
        child_pid=42,
        exit_code=0,
        launch_count=1,
        job_assigned_before_resume=True,
        job_empty=True,
        stdout_eof=True,
        stderr_eof=True,
        frame_eof=True,
        job_handles_closed=True,
        reader_threads_joined=True,
        overflow_observed=False,
        reader_failed=False,
        forced_termination=False,
    )
    parent_objects = driver.capture_c01_v20_driver_objects(driver)
    receipt = wrapper.create_c01_v20_wrapper_call_receipt(
        projection_raw,
        frame,
        parent_receipt,
        parent_driver_module=driver,
        parent_driver_objects=parent_objects,
    )

    assert wrapper.validate_c01_v20_wrapper_call_receipt(receipt) is True
    assert receipt.frame is frame
    assert receipt.parent_process_receipt is parent_receipt
    assert receipt.projection_raw is projection_raw
    object.__setattr__(receipt, "call_nonce", object())
    assert wrapper.validate_c01_v20_wrapper_call_receipt(receipt) is False


def test_frame_channel_requires_root_stage_and_is_one_use_without_real_pipe():
    wrapper = _load_wrapper()
    _root, scope = _root_scope_module()

    with tempfile.TemporaryFile(mode="w+b") as file_obj:
        stream = file_obj.raw
        receipt = wrapper.C01V20FrameChannelReceipt(
            scope,
            stream,
            _factory=wrapper._C01_V20_FRAME_CHANNEL_FACTORY,
        )

        with pytest.raises(wrapper.C01V20ChildActivationError):
            receipt.consume_root_frame_writer(scope)
        assert receipt.used is False

        scope.issuer_returned = True
        scope.stage_count = 1
        scope.root_content_stage = object()
        scope.pending = object()
        scope.root_content_seal = object()
        assert receipt.consume_root_frame_writer(scope) is stream
        assert receipt.used is True
        with pytest.raises(wrapper.C01V20ChildActivationError):
            receipt.consume_root_frame_writer(scope)


def test_fixed_child_loader_builds_the_exact_23_member_held_scope():
    wrapper = _load_wrapper()
    root_path = Path("D:/source_code/backtrader")
    front_raw = wrapper._read_public_source(
        root_path,
        wrapper._FRONT_PATH,
        expected_sha256=wrapper._ROOT_STATIC_SOURCE_PINS[wrapper._FRONT_PATH],
    )
    front_module = wrapper._load_module_from_bytes(
        root_path,
        wrapper._FRONT_PATH,
        wrapper._FRONT_MODULE_NAME,
        front_raw,
    )
    runner_raw = wrapper._read_public_source(
        root_path,
        wrapper._RUNNER_PATH,
        maximum=wrapper._MAX_SMALL_SOURCE_BYTES,
        expected_sha256=wrapper._ROOT_STATIC_SOURCE_PINS[wrapper._RUNNER_PATH],
    )
    runner_module = wrapper._load_module_from_bytes(
        root_path,
        wrapper._RUNNER_PATH,
        wrapper._RUNNER_MODULE_NAME,
        runner_raw,
    )
    bundle_context = front_module.verified_c01_v20_sources(root_path)
    bundle = bundle_context.__enter__()
    scope = None
    try:
        helper_sources = bundle.owner._read_source_bundle(root_path)
        scope = wrapper._fixed_root_scope(
            root=root_path,
            wrapper_module=wrapper,
            wrapper_raw=WRAPPER_PATH.read_bytes(),
            front_module=front_module,
            front_raw=front_raw,
            runner_module=runner_module,
            runner_raw=runner_raw,
            bundle=bundle,
            helpers_source=helper_sources,
        )
        expected_paths = set(scope.source_pins)
        assert len(expected_paths) == 23
        assert expected_paths == set(scope.verified_source_modules)
        assert expected_paths == set(scope.verified_source_objects)
        assert expected_paths == set(scope.held_source_bytes)
        assert scope.verified_source_modules[wrapper._FRONT_PATH] is front_module
        assert scope.verified_source_modules[wrapper._RUNNER_PATH] is runner_module
        assert scope.verified_source_modules[wrapper._ISSUER_PATH] is bundle.issuer
        assert scope.verified_source_modules[wrapper._OWNER_PATH] is bundle.owner
        assert scope.verified_source_modules[wrapper._WRAPPER_PATH] is wrapper
        assert (
            scope.verified_source_objects[wrapper._RUNNER_PATH]["invoke_v20_issuer.__globals__"]
            is runner_module.__dict__
        )
        assert (
            scope.root_module.verify_namespace_freshness_receipt(
                scope, scope.namespace_freshness_receipt
            )
            is True
        )

    finally:
        if scope is not None and scope.active is True:
            scope.root_module.close_c01_root_invocation_scope(scope)
        bundle_context.__exit__(None, None, None)


def test_loaded_issuer_stages_and_root_seals_synthetic_worker_without_spawn_or_network(
    tmp_path, monkeypatch
):
    """Exercise the production candidate/stage/custody/seal chain with fake leaves.

    Admission, ignored config/.env reads, native SDK execution, process creation,
    and network probing are outside this source-fake.  The real V20 candidate
    function and all source-pinned Root validators still execute over synthetic
    V4/V3 receipts and synthetic snapshot bytes.
    """

    wrapper = _load_wrapper()
    root_path = Path("D:/source_code/backtrader")
    front_raw = wrapper._read_public_source(
        root_path,
        wrapper._FRONT_PATH,
        expected_sha256=wrapper._ROOT_STATIC_SOURCE_PINS[wrapper._FRONT_PATH],
    )
    front_module = wrapper._load_module_from_bytes(
        root_path,
        wrapper._FRONT_PATH,
        wrapper._FRONT_MODULE_NAME,
        front_raw,
    )
    runner_raw = wrapper._read_public_source(
        root_path,
        wrapper._RUNNER_PATH,
        maximum=wrapper._MAX_SMALL_SOURCE_BYTES,
        expected_sha256=wrapper._ROOT_STATIC_SOURCE_PINS[wrapper._RUNNER_PATH],
    )
    runner_module = wrapper._load_module_from_bytes(
        root_path,
        wrapper._RUNNER_PATH,
        wrapper._RUNNER_MODULE_NAME,
        runner_raw,
    )
    bundle_context = front_module.verified_c01_v20_sources(root_path)
    bundle = bundle_context.__enter__()
    scope = None
    frame_file = tempfile.TemporaryFile(mode="w+b")
    patched: dict[tuple[ModuleType, str], Any] = {}

    def install(module: ModuleType, name: str, value: Any) -> None:
        key = (module, name)
        if key not in patched:
            patched[key] = module.__dict__[name]
        module.__dict__[name] = value

    def restore_patches() -> None:
        for (module, name), original in reversed(tuple(patched.items())):
            module.__dict__[name] = original
        patched.clear()

    try:
        issuer = bundle.issuer
        owner = bundle.owner
        helpers = bundle.helpers
        helpers_source = owner._read_source_bundle(root_path)
        scope = wrapper._fixed_root_scope(
            root=root_path,
            wrapper_module=wrapper,
            wrapper_raw=WRAPPER_PATH.read_bytes(),
            front_module=front_module,
            front_raw=front_raw,
            runner_module=runner_module,
            runner_raw=runner_raw,
            bundle=bundle,
            helpers_source=helpers_source,
        )
        protocol = helpers["protocol"]
        supervisor = helpers["supervisor"]
        ledger_fixture_path = (
            REPO_ROOT
            / "tests"
            / "unit"
            / "live_certification"
            / "test_simnow_c01_root_ledger_v1.py"
        )
        fixture_name = "_c01_v20_loaded_chain_ledger_fixture"
        fixture_spec = importlib.util.spec_from_file_location(fixture_name, ledger_fixture_path)
        assert fixture_spec is not None and fixture_spec.loader is not None
        fixture_module = importlib.util.module_from_spec(fixture_spec)
        sys.modules[fixture_name] = fixture_module
        try:
            fixture_spec.loader.exec_module(fixture_module)
            fixture_module.ACCOUNT_SCOPE = protocol.compute_account_scope_sha256(
                fixture_module.BROKER_ID, fixture_module.USER_ID
            )
            evidence = fixture_module._source_produced_bundle()
        finally:
            sys.modules.pop(fixture_name, None)

        front_pairs = (
            {
                "md_front": "tcp://127.0.0.1:31001",
                "td_front": "tcp://127.0.0.1:31002",
            },
        )
        selection_sha256 = hashlib.sha256(b"source-fake-current-selection").hexdigest()
        pair_binding = protocol.C01PairBinding(
            selected_index=0,
            selection_sha256=selection_sha256,
            md_front_sha256=hashlib.sha256(front_pairs[0]["md_front"].encode("utf-8")).hexdigest(),
            td_front_sha256=hashlib.sha256(front_pairs[0]["td_front"].encode("utf-8")).hexdigest(),
            td_front=front_pairs[0]["td_front"],
            selected_at_utc=owner._now_utc(),
        )
        worker_payload = dict(evidence["worker"])
        worker_payload["pair_binding"] = pair_binding.to_dict()
        worker_receipt = protocol.parse_worker_frame(protocol.encode_worker_frame(worker_payload))
        lifecycle = protocol.C01ProcessLifecycleReceipt(
            run_nonce=worker_receipt.run_nonce,
            parent_pid=worker_receipt.parent_pid,
            worker_pid=worker_receipt.worker_pid,
            worker_source_sha256=worker_receipt.worker_source_sha256,
            assigned_before_resume=True,
            stdin_fully_sent=True,
            stdout_eof=True,
            stderr_eof=True,
            process_exit_observed=True,
            process_exit_code=0,
            job_active_count=0,
            handles_closed=True,
            timed_out=False,
            forced_kill=False,
            containment="windows_job",
            reason="source_fake_worker_complete",
        )
        process = supervisor.C01SupervisorResult(
            status="BLOCKED",
            reason="source_fake_worker_complete",
            worker_receipt=worker_receipt,
            process_lifecycle=lifecycle,
        )
        account_scope = fixture_module.ACCOUNT_SCOPE
        credential_binding = fixture_module.CREDENTIAL_BINDING
        config_digest = hashlib.sha256(b"synthetic public-test config").hexdigest()
        now = datetime.now(timezone.utc)
        admission = issuer._C01V20Admission(
            admission_id="a" * 32,
            not_before_utc=now - timedelta(seconds=1),
            expires_at_utc=now + timedelta(minutes=5),
            bindings={
                "account_scope_sha256": account_scope,
                "credential_binding_sha256": credential_binding,
                "config_source_sha256": config_digest,
            },
            configured_front_pair_count=1,
            admission_sha256="1" * 64,
            claim_sha256="2" * 64,
            consumed_sha256="3" * 64,
        )
        private_paths = owner._PrivateRun(
            root=SimpleNamespace(path=tmp_path / "synthetic-private-run"),
            native_flow=None,
            evidence=None,
        )
        credentials = owner._Credentials(
            broker_id=fixture_module.BROKER_ID,
            user_id=fixture_module.USER_ID,
            password="source-fake-password",
            app_id="source-fake-app",
            auth_code="source-fake-auth",
            product_info=owner._PRODUCT_INFO,
            md_front=front_pairs[0]["md_front"],
            td_front=front_pairs[0]["td_front"],
        )
        audits: list[dict[str, Any]] = []

        @contextmanager
        def fake_pair_config(_root, _helpers):
            yield front_pairs, config_digest, lambda: None

        @contextmanager
        def fake_credentials(*_args, **_kwargs):
            yield credentials

        @contextmanager
        def fake_private_run(_helpers):
            yield private_paths

        def fake_select(_helpers, _pairs, *, deadline, audit_sink, **_kwargs):
            assert deadline > issuer.time.monotonic()
            audit_sink["fresh_pair_selection"] = issuer._fresh_pair_selection_value(
                False, pair_binding.selection_sha256
            )
            return pair_binding

        def fake_worker(*_args, **_kwargs):
            return process

        def fake_persist(_paths, _helpers, document):
            assert type(document) is dict
            audits.append(document)
            return hashlib.sha256(b"source-fake-audit").hexdigest()

        issuer_original_stage = issuer._stage_root_content_candidate

        def stage_trampoline(**kwargs):
            restore_patches()
            stage = issuer_original_stage(**kwargs)
            install(issuer, "_persist_private_audit", fake_persist)
            return stage

        install(issuer, "_private_pair_config_lease", fake_pair_config)
        install(issuer, "_credential_lease", fake_credentials)
        install(owner, "_private_run", fake_private_run)
        install(issuer, "_select_current_pair", fake_select)
        install(
            issuer,
            "_read_worker_progress",
            lambda *_args: {
                "status": "verified",
                "last_stage": "worker_receipt",
                "last_event": "end",
            },
        )
        install(issuer, "_read_worker_failure_diagnostic", lambda *_args, **_kwargs: None)
        install(issuer, "_project_worker_observation", lambda *_args, **_kwargs: None)
        install(issuer, "_persist_private_audit", fake_persist)
        install(supervisor, "run_fixed_c01_worker", fake_worker)
        install(
            owner,
            "_private_input_packet",
            lambda *_args: (b"source-fake-private-input-packet", account_scope, credential_binding),
        )
        install(owner, "_worker_process_complete", lambda *_args: True)
        install(owner, "_worker_receipt_matches", lambda *_args: True)
        install(owner, "_verify_tree", lambda *_args, **_kwargs: None)
        install(owner, "_read_snapshot_artifacts", lambda *_args: dict(evidence["artifacts"]))
        install(issuer, "_stage_root_content_candidate", stage_trampoline)

        def forbidden_leaf(*_args, **_kwargs):
            raise AssertionError("source-fake candidate attempted process or network access")

        monkeypatch.setattr(subprocess, "Popen", forbidden_leaf)
        monkeypatch.setattr(socket, "socket", forbidden_leaf)
        monkeypatch.setattr(socket, "create_connection", forbidden_leaf)

        reason = issuer._run_candidate(
            owner,
            helpers,
            deadline=issuer.time.monotonic() + issuer.MAX_PROFILE_SECONDS,
            admission=admission,
            root_scope=scope,
            worker_observation_sink={"value": None},
            post_worker_failure_sink={"stage": "none", "code": "none"},
        )
        restore_patches()
        assert reason == "read_only_candidate_complete"
        assert scope.stage_count == 1
        stage = scope.root_content_stage
        assert stage.candidate_refs[0] is admission
        assert stage.candidate_refs[1] is pair_binding
        assert stage.candidate_refs[2] is process
        assert (
            stage.candidate_refs[4]["snapshots/baseline.json"]
            is evidence["artifacts"]["snapshots/baseline.json"]
        )
        assert len(audits) == 1
        assert audits[0]["write_counters"] == {"ReqOrderInsert": 0, "ReqOrderAction": 0}

        issuer_result = issuer.C01NativeTdReadV20Result(
            "PASS",
            "read_only_candidate_complete",
            _factory=issuer._RESULT_FACTORY,
        )
        pending = scope.root_module.issue_c01_candidate_pending_result(scope, issuer_result)
        custody = scope.root_custody_module
        custody_receipt = custody.issue_c01_root_content_custody_receipt(
            scope, pending, stage, process
        )
        assert (
            custody.validate_c01_root_content_custody_receipt(
                custody_receipt, scope, pending, stage
            )
            is True
        )
        handoff = scope.verified_source_modules[wrapper._HANDOFF_PATH]
        seal = handoff.mint_c01_root_content_seal(
            root_module=scope.root_module,
            custody_module=custody,
            stage=stage,
            pending=pending,
            custody_receipt=custody_receipt,
        )
        stream = frame_file.raw
        channel = wrapper.C01V20FrameChannelReceipt(
            scope,
            stream,
            _factory=wrapper._C01_V20_FRAME_CHANNEL_FACTORY,
        )
        writer = scope.root_module.create_c01_root_content_frame_writer(scope, channel)
        handoff.write_c01_root_content_frame(seal, writer)
        stream.flush()
        assert stream.tell() == len(seal._frame)
        assert len(seal._frame) <= wrapper._MAX_FRAME_BYTES
        frame_file.seek(0)
        captured_frame = frame_file.read()
        assert captured_frame == seal._frame
        assert scope.content_frame_sent is True
        assert scope.consumed is True
        assert writer._used is True
        assert channel.used is True
        stream.close()
        scope.root_module.close_c01_root_invocation_scope(scope)
        assert scope.active is False
        assert (
            scope.root_module.verify_namespace_freshness_receipt(
                scope, scope.namespace_freshness_receipt
            )
            is True
        )
        # SOURCE_FAKE_ONLY: production-loaded Root V17 receipt factory through
        # the one-use completion adapter, with synthetic process and CUv2
        # leaves. Any PASS/count below is local test data and never updates an
        # official or account tally.
        driver_raw = DRIVER_PATH.read_bytes()
        driver_module = ModuleType("_c01_v20_root_actual_driver")
        driver_module.__file__ = str(DRIVER_PATH)
        driver_module.__package__ = ""
        driver_module.__c01_source_sha256__ = hashlib.sha256(driver_raw).hexdigest()
        exec(compile(driver_raw, str(DRIVER_PATH), "exec", dont_inherit=True), driver_module.__dict__)

        adjudicator_path = (
            REPO_ROOT
            / "backtrader_runtime"
            / "certification_simnow_c01_root_formal_adjudicator_v1.py"
        )
        adjudicator_raw = adjudicator_path.read_bytes()
        adjudicator_module = ModuleType(
            "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1"
        )
        adjudicator_module.__file__ = str(adjudicator_path)
        adjudicator_module.__package__ = "backtrader_runtime"
        adjudicator_module.__c01_source_sha256__ = hashlib.sha256(adjudicator_raw).hexdigest()
        exec(
            compile(adjudicator_raw, str(adjudicator_path), "exec", dont_inherit=True),
            adjudicator_module.__dict__,
        )

        completion_path = (
            REPO_ROOT
            / "examples"
            / "000_live_certification"
            / "simnow_penetration"
            / "common"
            / "c01_root_completion_v1.py"
        )
        completion_raw = completion_path.read_bytes()
        completion_module = ModuleType("common.c01_root_completion_v1")
        completion_module.__file__ = str(completion_path)
        completion_module.__package__ = "common"
        completion_module.__c01_source_sha256__ = hashlib.sha256(completion_raw).hexdigest()
        exec(
            compile(completion_raw, str(completion_path), "exec", dont_inherit=True),
            completion_module.__dict__,
        )

        cuv2_raw = (
            b"from contextlib import contextmanager\n"
            b"@contextmanager\n"
            b"def held_public_sources(public, software):\n"
            b"    try:\n"
            b"        yield (PRIVATE, CLI, RAW_MAP)\n"
            b"    finally:\n"
            b"        CLOSES.append('closed')\n"
        )
        cuv2_path = "D:/fake/c01-formal-composition-cuv2.py"
        cuv2_sha = hashlib.sha256(cuv2_raw).hexdigest()
        monkeypatch.setattr(driver_module, "CUV2_SOURCE_PATH", cuv2_path)
        monkeypatch.setattr(driver_module, "CUV2_SOURCE_SHA256", cuv2_sha)
        monkeypatch.setattr(driver_module, "CUV2_SOURCE_BYTES", len(cuv2_raw))
        exe_raw = b"synthetic-python-executable"
        dll_raw = b"synthetic-python-dll"
        monkeypatch.setattr(
            driver_module, "_PYTHON_EXE_SHA256", hashlib.sha256(exe_raw).hexdigest()
        )
        monkeypatch.setattr(
            driver_module, "_PYTHON_DLL_SHA256", hashlib.sha256(dll_raw).hexdigest()
        )

        modules = dict(scope.verified_source_modules)
        modules[driver_module._DRIVER_PATH] = driver_module
        modules[driver_module._ADJUDICATOR_PATH] = adjudicator_module
        modules[driver_module._COMPLETION_PATH] = completion_module
        held_bytes = dict(scope.held_source_bytes)
        held_bytes[driver_module._DRIVER_PATH] = driver_raw
        held_bytes[driver_module._ADJUDICATOR_PATH] = adjudicator_raw
        held_bytes[driver_module._COMPLETION_PATH] = completion_raw
        pins = {path: hashlib.sha256(raw).hexdigest() for path, raw in held_bytes.items()}
        objects = {
            path: driver_module._capture_source_module_objects(module)
            for path, module in modules.items()
        }
        driver_objects = driver_module.capture_c01_v20_driver_objects(driver_module)
        objects[driver_module._DRIVER_PATH] = driver_objects
        module_map = MappingProxyType(modules)
        object_map = MappingProxyType(objects)
        pin_map = MappingProxyType(pins)
        held_byte_map = MappingProxyType(held_bytes)
        assert len(scope.root_module._REQUIRED_ROOT_SCOPE_PATHS) == 23
        assert len(scope.root_module._REQUIRED_PARENT_MODULE_PATHS) == 26

        frame = handoff.read_c01_root_content_frame(io.BytesIO(captured_frame))
        projection = wrapper._child_projection(
            reason="candidate_root_handoff_written",
            receipt_verified=True,
            source_closure_verified=True,
            root_postverify_verified=True,
            counts={
                "request_count": 8,
                "query_callback_count": stage.validated_content.query_callback_count,
                "snapshot_count": 2,
                "write_invocation_count": 0,
            },
        )
        projection_raw = json.dumps(
            projection, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        assert driver_module._validate_driver_projection(
            driver_module._parse_canonical_projection(projection_raw)
        ) is True
        assert type(frame) is handoff.RootContentFrame
        assert frame._factory is handoff._FRAME_FACTORY
        assert type(frame._raw) is bytes
        assert handoff.__name__ == (
            "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1"
        )
        parent_receipt = driver_module.create_c01_v20_parent_process_receipt(
            frame=frame,
            handoff_module=handoff,
            call_nonce=object(),
            stdout_raw=projection_raw,
            stderr_raw=b"",
            child_pid=42,
            exit_code=0,
            launch_count=1,
            job_assigned_before_resume=True,
            job_empty=True,
            stdout_eof=True,
            stderr_eof=True,
            frame_eof=True,
            job_handles_closed=True,
            reader_threads_joined=True,
            overflow_observed=False,
            reader_failed=False,
            forced_termination=False,
        )
        wrapper_receipt = wrapper.create_c01_v20_wrapper_call_receipt(
            projection_raw,
            frame,
            parent_receipt,
            parent_driver_module=driver_module,
            parent_driver_objects=driver_objects,
        )

        cuv2 = ModuleType("_fake_c01_formal_cuv2")
        cuv2.__file__ = cuv2_path
        cuv2.__c01_source_sha256__ = cuv2_sha
        cuv2.__dict__.update(
            PRIVATE=ModuleType("_root_public_custody_private"),
            CLI=ModuleType("_root_public_custody_cli"),
            RAW_MAP={},
            CLOSES=[],
        )
        exec(compile(cuv2_raw, cuv2_path, "exec", dont_inherit=True), cuv2.__dict__)
        software_bytes = {
            cuv2_path: cuv2_raw,
            driver_module._PYTHON_EXE_PATH: exe_raw,
            driver_module._PYTHON_DLL_PATH: dll_raw,
        }
        software_pins = {
            path: hashlib.sha256(raw).hexdigest() for path, raw in software_bytes.items()
        }
        raw_map = {
            driver_module._absolute_public_path(
                driver_module._source_root_for_driver(), path
            ): raw
            for path, raw in held_bytes.items()
        }
        raw_map.update(
            {
                driver_module._normalize_absolute_path(path): raw
                for path, raw in software_bytes.items()
            }
        )
        cuv2.RAW_MAP.update(raw_map)
        source_lease = driver_module.enter_c01_v20_outer_source_lease(
            cuv2_module=cuv2,
            cuv2_source_bytes=cuv2_raw,
            public_source_pins=pin_map,
            software_source_pins=software_pins,
        )
        snapshot_failures = []
        for relative, module in module_map.items():
            current = driver_module._capture_source_module_objects(module)
            expected = object_map[relative]
            raw = held_byte_map[relative]
            if module.__dict__.get("__c01_source_sha256__") != pin_map[relative]:
                snapshot_failures.append((relative, "module_pin"))
            elif hashlib.sha256(raw).hexdigest() != pin_map[relative]:
                snapshot_failures.append((relative, "held_bytes_pin"))
            elif not driver_module._source_path_matches(module.__dict__.get("__file__"), relative):
                snapshot_failures.append((relative, "module_path"))
            elif set(current) != set(expected):
                snapshot_failures.append(
                    (relative, "object_keys", tuple(sorted(set(current) ^ set(expected))))
                )
            elif any(current[name] is not expected[name] for name in current):
                snapshot_failures.append((relative, "object_identity"))
        assert not snapshot_failures, snapshot_failures
        driver_module.bind_c01_v20_outer_source_modules(
            source_lease,
            source_modules=module_map,
            source_objects=object_map,
            source_pins=pin_map,
            held_source_bytes=held_byte_map,
        )
        outer_close = driver_module.create_c01_v20_outer_close_receipt(
            lease=source_lease,
            parent_process_receipt=parent_receipt,
        )
        prior_receipt_count = len(scope.root_module._RETAINED_ROOT_INVOCATION_RECEIPTS)
        try:
            formal_result = driver_module.complete_c01_v20_formal_result(
                frame=frame,
                parent_process_receipt=parent_receipt,
                wrapper_call_receipt=wrapper_receipt,
                outer_close_receipt=outer_close,
            )
        except driver_module.RootDriverError as exc:
            cause = exc.__context__
            raise AssertionError(
                (
                    "sourcefake_formal_completion_failed",
                    type(cause).__name__ if cause is not None else None,
                    getattr(cause, "code", None),
                    str(cause) if cause is not None else None,
                )
            ) from None
        result_payload = formal_result.to_dict()
        assert result_payload["certification"] == "PASS"
        assert result_payload["formal_c01_pass"] is True
        assert result_payload["official_c01_pass_count"] == 1
        assert formal_result.official_c01_pass_count == 1
        assert len(scope.root_module._RETAINED_ROOT_INVOCATION_RECEIPTS) == (
            prior_receipt_count + 1
        )
        root_invocation = scope.root_module._RETAINED_ROOT_INVOCATION_RECEIPTS[-1]
        assert len(root_invocation.source_modules) == 26
        assert root_invocation.source_modules[driver_module._COMPLETION_PATH] is completion_module
        assert (
            scope.root_module.validate_c01_root_invocation_receipt(root_invocation) is True
        )
        assert len(root_invocation.frame_source_pin_items) == 23
        assert cuv2.CLOSES == ["closed"]
    finally:
        restore_patches()
        if scope is not None and scope.active is True:
            scope.root_module.close_c01_root_invocation_scope(scope)
        try:
            frame_file.raw.close()
        except Exception:
            pass
        frame_file.close()
        bundle_context.__exit__(None, None, None)


def test_issuer_stages_same_call_content_inside_worker_exit_stack():
    tree = ast.parse(ISSUER_PATH.read_text(encoding="utf-8"))
    run_candidate = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_candidate"
    )
    stack_scope = next(
        node
        for node in ast.walk(run_candidate)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == "ExitStack"
            for item in node.items
        )
    )
    in_stack_calls = [node for node in ast.walk(stack_scope) if isinstance(node, ast.Call)]
    validation = next(
        node
        for node in in_stack_calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "validate_c01_candidate"
    )
    stage = next(
        node
        for node in in_stack_calls
        if isinstance(node.func, ast.Name) and node.func.id == "_stage_root_content_candidate"
    )
    assert stage.lineno > validation.lineno

    stage_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_stage_root_content_candidate"
    )
    stage_call = next(
        node
        for node in ast.walk(stage_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "stage_function"
    )
    assert {keyword.arg for keyword in stage_call.keywords} == {
        "root_module",
        "custody_module",
        "scope",
        "admission",
        "pair_binding",
        "process",
        "validation",
        "artifacts",
        "validator_module",
        "protocol_module",
        "worker_module",
    }


def test_standalone_v20_runner_remains_blocked(capsys):
    source = RUNNER_PATH.read_bytes()
    module = ModuleType("_c01_v20_standalone_runner_source_fake")
    module.__file__ = str(RUNNER_PATH)
    module.__package__ = ""
    exec(compile(source, str(RUNNER_PATH), "exec", dont_inherit=True), module.__dict__)

    assert module.main(["--live", "--profile", module.PROFILE_ID]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["certification"] == "BLOCKED"
    assert output["reason"] == "root_owned_invocation_required"
    assert output["write_policy"] == "NO_WRITE"
    assert output["writes"] == 0
