"""Source/fake-only contracts for the R27 finite custody-entry diagnostic."""

from __future__ import annotations

import hashlib
import importlib.machinery
import io
import json
import os
from pathlib import Path
import sys
import time
import types
import zipfile

import pytest


ROOT = Path(r"D:\source_code\backtrader")
WHOLE_PATH = ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py"
INVOKE_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r27.py"
TEST_PATH = ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
R19_DRIVER_PATH = ROOT / "scripts/iteration41_optional16_r33_root_driver_r19.py"
R19_DRIVER_SHA256 = "d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path, name: str):
    raw = path.read_bytes()
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module, raw


def _fixture_flags(whole, whole_raw: bytes, test_raw: bytes, invoke_raw: bytes) -> None:
    whole.ROOT_SELF_SHA256 = _sha(whole_raw)
    whole.ROOT_TEST_SHA256 = _sha(test_raw)
    whole.R27_INVOKE_SHA256 = _sha(invoke_raw)
    whole.R27_TEST_SHA256 = _sha(test_raw)
    whole.ROOT_ACTUAL_ENABLED = True
    whole.ROOT_REVIEW_READY = True
    whole.ROOT_REVIEWED_ACTIVATION = True
    whole.ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED = True
    whole.ROOT_NATIVE_ENABLED = True
    whole.INERT_PUBLIC_PATH_COUNT = 379
    whole.ACTIVE_PUBLIC_PATH_COUNT = 575
    whole.ACTIVE_SOFTWARE_PATH_COUNT = 5
    whole.ACTIVE_PATH_ALIAS_COUNT = 19

    packet_values = {
        "source-bundle.zip": b"sourcefake-r27-source-bundle",
        "source-index.json": b"sourcefake-r27-source-index",
        "source-pins.json": b"sourcefake-r27-source-pins",
        "checkpoint.json": b"sourcefake-r27-checkpoint",
        "README.md": b"sourcefake-r27-readme",
        "qa/qa-summary.json": b"sourcefake-r27-generated-qa",
    }
    whole.ROOT_PACKET_PINS = {name: _sha(raw) for name, raw in packet_values.items() if name != "README.md" and name != "qa/qa-summary.json"}
    whole.ROOT_PACKET_AUX_PINS = {
        name: _sha(raw)
        for name, raw in packet_values.items()
        if name in {"README.md", "qa/qa-summary.json"}
    }
    whole.ROOT_REVIEW_PINS = {
        name: _sha(("sourcefake-r27-review:" + name).encode("ascii"))
        for name in (
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        )
    }


def _fill_public_review_context_fixture(whole) -> dict[str, bytes]:
    """Fill only the outer review slots with explicitly synthetic bytes in memory."""
    names = (
        "review.json",
        "review-bundle.zip",
        "review-index.json",
        "review-checkpoint.json",
        "README.md",
    )
    values = {
        name: ("sourcefake-r27-public-review-context:" + name).encode("ascii")
        for name in names
    }
    whole.ROOT_REVIEW_PINS = {name: _sha(raw) for name, raw in values.items()}
    whole.ROOT_REVIEW_README_SHA256 = whole.ROOT_REVIEW_PINS["README.md"]
    whole.ROOT_ACTUAL_ENABLED = True
    whole.ROOT_REVIEW_READY = True
    whole.ROOT_REVIEWED_ACTIVATION = True
    whole.ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED = True
    whole.ROOT_NATIVE_ENABLED = True
    return {whole.ROOT_REVIEW / name: raw for name, raw in values.items()}


class _FakeScope:
    def __init__(self, held: dict[Path, bytes]):
        self.held = held
        self.exited = False
        self.private = types.SimpleNamespace(create_private_directory=lambda _path: object())
        self.cli = object()

    def __enter__(self):
        return self.private, self.cli, self.held

    def __exit__(self, *_args):
        self.exited = True
        return False


def _run_entry_failure(*, missing_helper: bool):
    invoke, invoke_raw = _load(INVOKE_PATH, "r27_entry_failure_" + str(missing_helper))
    whole, _whole_raw = _load(WHOLE_PATH, "r27_whole_failure_" + str(missing_helper))
    path = Path(r"D:\source_code\backtrader\synthetic-held-source.py")
    held = {} if missing_helper else {path: b"held bytes"}
    expected = {} if missing_helper else {path: _sha(b"expected different bytes")}
    context = {
        "mode": "actual",
        "expected_pins": expected,
        "outer_stdout": io.StringIO(),
        "diagnostic_source_codes": {
            "r12": invoke._literal_source_codes(invoke_raw, frozenset({"_need"}))
        },
    }
    invoke._initialize_phase_diagnostic(context)
    invoke._register_exception_types(context, invoke)
    invoke.ROOT_REVIEW_READY = True
    invoke.ROOT_REVIEWED_ACTIVATION = True
    invoke.ROOT_PACKET_PINS = {
        name: "0" * 64
        for name in (
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        )
    }
    invoke.ROOT_REVIEW_PINS = {
        name: "0" * 64
        for name in (
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        )
    }
    fake_r2 = types.ModuleType("r27_fake_r2")
    scope = invoke._DeferredScope(_FakeScope(held), context, fake_r2)
    context["scope"] = scope
    with pytest.raises(invoke.RootEnvelopeError) as raised:
        scope.__enter__()

    context["safe_exception_diagnostic"] = invoke._diagnostic_payload(context, raised.value)
    invoke._uncertain_summary(context, "root_adapter_exception")
    frame = context["outer_stdout"].getvalue().encode("ascii")
    parsed = whole._parse_r12_frame(frame, 2)
    return invoke, whole, scope, raised.value, parsed, frame


def _valid_exception_frame() -> dict[str, object]:
    application = {
        "schema": "iteration41.optional16.r33.root-application-diagnostic.r12.v1",
        "application_done_event_set": False,
        "application_thread_alive": True,
        "state_error_class": "UNOBSERVED",
        "stdout_overflow": False,
        "stderr_overflow": False,
        "stderr_nonempty": False,
        "application_elapsed_seconds": "UNOBSERVED",
    }
    phase = {
        "schema": "iteration41.optional16.r33.root-invoke-r12.phase-diagnostic.v1",
        "availability": "OBSERVED",
        "phase": "source_custody_entered",
        "transition_ordinal": 3,
        "invocation_elapsed_ms": 100,
        "phase_elapsed_ms": 20,
    }
    return {
        "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
        "status": "ROOT_UNCERTAIN_RETAINED_NO_PARSE",
        "reason_code": "root_adapter_exception",
        "source_scope_released": False,
        "complete_custody_postverified": False,
        "source_custody_state": "HELD",
        "source_scope_references_retained_until_root_process_exit": True,
        "complete_custody_retained_until_root_process_exit": True,
        "late_frame_parsed": False,
        "public_raw_saved": False,
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "r2_application_diagnostic": application,
        "phase_diagnostic": phase,
        "exception_diagnostic": {
            "phase": "source_custody_entered",
            "exception_type": "RootEnvelopeError",
            "source_code": "held_path_missing",
        },
    }


def test_r27_payload_keeps_379_binding_and_new_invoke_review_dirs(monkeypatch):
    whole, whole_raw = _load(WHOLE_PATH, "r27_payload_fixture")
    invoke_raw = INVOKE_PATH.read_bytes()
    test_raw = TEST_PATH.read_bytes()
    assert whole.ROOT_ACTUAL_ENABLED is False
    assert whole.ROOT_REVIEW_READY is False
    assert whole.ROOT_REVIEWED_ACTIVATION is False
    assert whole.ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED is False
    assert whole.ROOT_NATIVE_ENABLED is False
    _fixture_flags(whole, whole_raw, test_raw, invoke_raw)
    monkeypatch.setattr(whole.sys, "platform", "win32")
    monkeypatch.setattr(whole.sys, "version_info", (3, 11, 5))
    monkeypatch.setattr(
        whole.sys,
        "implementation",
        types.SimpleNamespace(name="cpython", cache_tag="cpython-311"),
    )

    assert whole._activation_ready() is True
    payload = json.loads(whole._activation_payload(float(time.monotonic() + 80.0)))
    assert payload["schema"] == "iteration41.optional16.r33.whole-call.r27-child-activation.v1"
    assert payload["counts"] == {
        "inert_public_paths": 379,
        "active_public_paths": 575,
        "software_paths": 5,
        "path_aliases": 19,
    }
    assert payload["invoke"]["path"] == str(whole.R27_INVOKE_SOURCE)
    assert payload["invoke"]["test_path"] == str(whole.R27_TEST)
    assert payload["invoke"]["packet_dir"] == str(whole.R19_PACKET)
    assert payload["invoke"]["packet_pins"] == whole.R19_PACKET_PINS
    assert payload["invoke"]["review_dir"] == str(whole.R19_REVIEW)
    assert payload["invoke"]["review_pins"] == whole.R19_REVIEW_PINS
    assert payload["driver"]["path"] == str(whole.R19_DRIVER_SOURCE)
    assert payload["driver"]["packet_dir"] == str(whole.R19_PACKET)
    assert payload["driver"]["review_dir"] == str(whole.R19_REVIEW)
    assert payload["driver"]["active_path"] == str(whole.R27_DRIVER_ACTIVE_PATH)
    assert payload["fresh_paths"] == whole.R27_FRESH_PATHS
    fixed = whole._fixed_inputs()
    assert 20 <= len(fixed) <= 64
    assert fixed[whole.ROOT_PACKET / "source-bundle.zip"] == whole.ROOT_PACKET_PINS[
        "source-bundle.zip"
    ]
    assert fixed[whole.ROOT_REVIEW / "review.json"] == whole.ROOT_REVIEW_PINS["review.json"]
    assert fixed[whole.R24_PACKET / "source-bundle.zip"] == whole.R24_PACKET_PINS[
        "source-bundle.zip"
    ]
    assert fixed[whole.R24_REVIEW / "review.json"] == whole.R24_REVIEW_PINS["review.json"]
    assert fixed[whole.R25_PACKET / "source-bundle.zip"] == whole.R25_PACKET_PINS[
        "source-bundle.zip"
    ]
    assert fixed[whole.R25_REVIEW / "review.json"] == whole.R25_REVIEW_PINS["review.json"]
    assert fixed[whole.R19_PACKET / "source-bundle.zip"] == whole.R19_PACKET_PINS[
        "source-bundle.zip"
    ]
    assert fixed[whole.R19_REVIEW / "review.json"] == whole.R19_REVIEW_PINS["review.json"]
    assert whole.WHOLE_CALL_SECONDS == 100.0
    assert whole.CLEANUP_SECONDS == 5.0
    assert whole.CHILD_FRAME_LIMIT == 12_288


def test_r27_frozen_r19_driver_namespace_pins_rebind_to_fresh_r27_paths():
    invoke, _invoke_raw = _load(INVOKE_PATH, "r27_r19_namespace_binding")
    r19_raw = R19_DRIVER_PATH.read_bytes()
    assert _sha(r19_raw) == R19_DRIVER_SHA256
    invoke.DRIVER_SHA256 = R19_DRIVER_SHA256
    frozen_r19, _ = _load(R19_DRIVER_PATH, "r27_frozen_r19_namespace")

    assert Path(frozen_r19.CONTROL) == invoke.PINNED_R5_DRIVER_CONTROL
    assert Path(frozen_r19.SCRATCH) == invoke.PINNED_R5_DRIVER_SCRATCH
    assert Path(frozen_r19.PROGRESS_PATH) == invoke.PINNED_R5_DRIVER_PROGRESS_PATH
    assert frozen_r19.PROGRESS_NAME == "r33-r19-progress.frames"

    fresh = invoke._driver_namespace_paths()
    assert fresh == (
        invoke.ROOT_DRIVER_CONTROL,
        invoke.ROOT_DRIVER_SCRATCH,
        invoke.DRIVER_ACTIVE_PATH,
    )
    assert fresh[0] != Path(frozen_r19.CONTROL)
    assert fresh[1] != Path(frozen_r19.SCRATCH)

    # Exercise the real active-source binding before the driver entrypoint.
    active_r19, _ = _load(R19_DRIVER_PATH, "r27_active_r19_source_fake")
    active_r19.__file__ = str(invoke.DRIVER_ACTIVE_PATH)
    context: dict[str, object] = {}
    invoke._initialize_phase_diagnostic(context)
    context["active_driver_raw"] = r19_raw
    context["source_fake_mode"] = True
    context["fake_active_main"] = lambda *_args, **_kwargs: 0
    invoke._active_driver_loaded(active_r19, context)

    assert context["diagnostic_phase"] == "source_contract_validation"
    assert Path(active_r19.CONTROL) == invoke.ROOT_DRIVER_CONTROL
    assert Path(active_r19.SCRATCH) == invoke.ROOT_DRIVER_SCRATCH
    assert Path(active_r19.PROGRESS_PATH) == (
        invoke.ROOT_DRIVER_CONTROL / frozen_r19.PROGRESS_NAME
    )
    assert Path(active_r19.CONTROL) != Path(frozen_r19.CONTROL)
    assert Path(active_r19.SCRATCH) != Path(frozen_r19.SCRATCH)
    assert Path(active_r19.PROGRESS_PATH) != Path(frozen_r19.PROGRESS_PATH)
    assert Path(frozen_r19.CONTROL) == invoke.PINNED_R5_DRIVER_CONTROL
    assert Path(frozen_r19.SCRATCH) == invoke.PINNED_R5_DRIVER_SCRATCH
    assert Path(frozen_r19.PROGRESS_PATH) == invoke.PINNED_R5_DRIVER_PROGRESS_PATH


@pytest.mark.parametrize(
    ("pin_name", "reason"),
    [
        ("PINNED_R5_DRIVER_CONTROL", "driver_r5_control_pin_mismatch"),
        ("PINNED_R5_DRIVER_SCRATCH", "driver_r5_scratch_pin_mismatch"),
    ],
)
def test_r27_frozen_r19_probe_rejects_fresh_paths_as_source_pins(pin_name, reason):
    invoke, _invoke_raw = _load(INVOKE_PATH, "r27_r19_namespace_reject_" + pin_name)
    r19_raw = R19_DRIVER_PATH.read_bytes()
    assert _sha(r19_raw) == R19_DRIVER_SHA256
    invoke.DRIVER_SHA256 = R19_DRIVER_SHA256
    fresh_path = (
        invoke.ROOT_DRIVER_CONTROL
        if pin_name.endswith("CONTROL")
        else invoke.ROOT_DRIVER_SCRATCH
    )
    setattr(invoke, pin_name, fresh_path)
    with pytest.raises(invoke.RootEnvelopeError, match=reason):
        invoke._driver_namespace_paths()


def test_r27_real_fixed_input_closure_verifies_public_packet_and_review_context(monkeypatch):
    whole, whole_raw = _load(WHOLE_PATH, "r27_fixed_closure_fixture")
    invoke_raw = INVOKE_PATH.read_bytes()
    test_raw = TEST_PATH.read_bytes()

    whole.ROOT_SELF_SHA256 = _sha(whole_raw)
    whole.ROOT_TEST_SHA256 = _sha(test_raw)
    whole.R27_INVOKE_SHA256 = _sha(invoke_raw)
    whole.R27_TEST_SHA256 = _sha(test_raw)
    whole.INERT_PUBLIC_PATH_COUNT = 379
    whole.ACTIVE_PUBLIC_PATH_COUNT = 575
    whole.ACTIVE_SOFTWARE_PATH_COUNT = 5
    whole.ACTIVE_PATH_ALIAS_COUNT = 19

    packet_names = (
        "source-bundle.zip",
        "source-index.json",
        "source-pins.json",
        "checkpoint.json",
    )
    aux_names = ("README.md", "qa/qa-summary.json")
    whole.ROOT_PACKET_PINS = {
        name: _sha((whole.ROOT_PACKET / name).read_bytes()) for name in packet_names
    }
    whole.ROOT_PACKET_AUX_PINS = {
        name: _sha((whole.ROOT_PACKET / name).read_bytes()) for name in aux_names
    }
    review_bytes = _fill_public_review_context_fixture(whole)
    assert whole._activation_ready() is True

    index = json.loads((whole.ROOT_PACKET / "source-index.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(whole.ROOT_PACKET / "source-bundle.zip") as archive:
        archive_names = set(archive.namelist())
        indexed = {row["path"]: row for row in index["members"]}
        assert archive_names == set(indexed)
        assert len(archive_names) == index["source_bundle_member_count"] == 3
        for name in sorted(archive_names):
            source = archive.read(name)
            assert _sha(source) == indexed[name]["sha256"]
            assert len(source) == indexed[name]["size_bytes"]
            assert source == (ROOT / name).read_bytes()

    bundle_sha = _sha((whole.ROOT_PACKET / "source-bundle.zip").read_bytes())
    index_sha = _sha((whole.ROOT_PACKET / "source-index.json").read_bytes())
    pins_document = json.loads(
        (whole.ROOT_PACKET / "source-pins.json").read_text(encoding="utf-8")
    )
    qa_sha = _sha((whole.ROOT_PACKET / "qa/qa-summary.json").read_bytes())
    readme_sha = _sha((whole.ROOT_PACKET / "README.md").read_bytes())
    assert pins_document["source_bundle_sha256"] == bundle_sha
    assert pins_document["source_index_sha256"] == index_sha
    assert pins_document["generated_qa_summary_sha256"] == qa_sha
    checkpoint = json.loads(
        (whole.ROOT_PACKET / "checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["source_bundle_sha256"] == bundle_sha
    assert checkpoint["source_index_sha256"] == index_sha
    assert checkpoint["source_pins_sha256"] == _sha(
        (whole.ROOT_PACKET / "source-pins.json").read_bytes()
    )
    assert checkpoint["generated_qa_summary_sha256"] == qa_sha
    assert checkpoint["readme_sha256"] == readme_sha

    assert whole.R24_PACKET_PINS["source-pins.json"] == (
        "3089e9fd9e97d625ee8f7a3015113c5122bf1f8d39fd63818dbf4c610c10f22a"
    )
    real_read_exact = whole._read_exact
    review_by_key = {
        os.path.normcase(os.path.normpath(str(path))): raw
        for path, raw in review_bytes.items()
    }

    def reviewed_context_reader(path: Path, expected: str) -> bytes:
        key = os.path.normcase(os.path.normpath(str(path)))
        raw = review_by_key.get(key)
        if raw is not None:
            assert _sha(raw) == expected == whole.ROOT_REVIEW_PINS[path.name]
            return raw
        return real_read_exact(path, expected)

    monkeypatch.setattr(whole, "_read_exact", reviewed_context_reader)
    fixed = whole._fixed_inputs()
    assert len(fixed) == 62
    verified = whole._verify_pins(fixed)
    assert set(verified) == set(fixed)
    assert all(_sha(verified[path]) == digest for path, digest in fixed.items())
    assert verified[whole.R24_PACKET / "source-pins.json"] == (
        whole.R24_PACKET / "source-pins.json"
    ).read_bytes()
    assert verified[whole.R19_PACKET / "source-bundle.zip"] == (
        whole.R19_PACKET / "source-bundle.zip"
    ).read_bytes()
    assert verified[whole.R25_PACKET / "source-bundle.zip"] == (
        whole.R25_PACKET / "source-bundle.zip"
    ).read_bytes()
    assert verified[whole.R25_REVIEW / "review.json"] == (
        whole.R25_REVIEW / "review.json"
    ).read_bytes()
    assert all(verified[path] == raw for path, raw in review_bytes.items())
    assert whole.ROOT_PACKET != whole.R19_PACKET
    assert whole.R27_INVOKE_SOURCE.read_bytes() == invoke_raw
    old_r25_pin = "3089e9fd9e97d625ee8f7a3015113c5122bf8f1d39fd63818dbf4c610c10f22a"
    regressed = dict(fixed)
    regressed[whole.R24_PACKET / "source-pins.json"] = old_r25_pin
    with pytest.raises(whole.SupervisorBlocked, match="source_pin_mismatch"):
        whole._verify_pins(regressed)


def test_r27_complete_fake_custody_path_still_postverifies_and_releases():
    invoke, invoke_raw = _load(INVOKE_PATH, "r27_complete_scope_fixture")
    path = Path(r"D:\source_code\backtrader\synthetic-good-held-source.py")
    raw = b"synthetic exact bytes"
    fake_scope = _FakeScope({path: raw})
    context = {
        "mode": "precheck",
        "expected_pins": {path: _sha(raw)},
    }
    invoke._initialize_phase_diagnostic(context)
    invoke._register_exception_types(context, invoke)
    scope = invoke._DeferredScope(fake_scope, context, types.ModuleType("r27_fake_r2"))
    context["scope"] = scope

    assert scope.__enter__() == (fake_scope.private, fake_scope.cli, fake_scope.held)
    assert scope.entered is True
    assert context["diagnostic_phase"] == "source_custody_entered"
    assert "safe_exception_diagnostic" not in context
    assert scope.__exit__(None, None, None) is False
    assert context["source_postverified"] is True
    assert context["source_released"] is True
    assert scope.released is True
    assert fake_scope.exited is True
    assert "_SOURCE_CUSTODY_ENTERED_ROOT_CODES" in invoke_raw.decode("utf-8")


@pytest.mark.parametrize(
    ("missing_helper", "expected_code"),
    [
        (True, "held_path_missing"),
        (False, "complete_held_source_mismatch"),
    ],
)
def test_r27_real_deferred_scope_projects_finite_post_entry_codes(
    missing_helper: bool, expected_code: str
):
    invoke, whole, scope, error, parsed, frame = _run_entry_failure(
        missing_helper=missing_helper
    )
    assert type(error) is invoke.RootEnvelopeError
    assert scope.entered is True
    assert parsed["status"] == "ROOT_UNCERTAIN_RETAINED_NO_PARSE"
    assert parsed["child_exception_diagnostic"] == {
        "phase": "source_custody_entered",
        "exception_type": "RootEnvelopeError",
        "source_code": expected_code,
    }
    assert "Traceback" not in frame.decode("ascii")
    assert "synthetic-held-source.py" not in frame.decode("ascii")
    assert (
        whole._valid_child_exception_diagnostic(parsed["child_exception_diagnostic"]) is True
    )


def test_r27_unknown_root_code_and_unknown_exception_stay_unobserved():
    invoke, _raw = _load(INVOKE_PATH, "r27_unknown_diagnostic_fixture")
    context: dict[str, object] = {
        "diagnostic_phase": "source_custody_entered",
    }
    invoke._record_source_custody_entered_failure(
        context, invoke.RootEnvelopeError("synthetic-detail-must-not-leak")
    )
    unknown_code = invoke._diagnostic_payload(
        context, invoke.RootEnvelopeError("synthetic-detail-must-not-leak")
    )
    class UnknownError(RuntimeError):
        pass

    unknown_type = invoke._diagnostic_payload(context, UnknownError("synthetic-detail-must-not-leak"))
    assert unknown_code["source_code"] == "UNOBSERVED"
    assert unknown_type == {
        "phase": "source_custody_entered",
        "exception_type": "UNOBSERVED",
        "source_code": "UNOBSERVED",
    }
    assert "synthetic-detail-must-not-leak" not in json.dumps([unknown_code, unknown_type])


@pytest.mark.parametrize(
    "diagnostic",
    [
        {
            "phase": "source_custody_entered",
            "exception_type": "OSError",
            "source_code": "held_path_missing",
        },
        {
            "phase": "source_custody_enter",
            "exception_type": "RootEnvelopeError",
            "source_code": "held_path_missing",
        },
        {
            "phase": "source_custody_entered",
            "exception_type": "RootEnvelopeError",
            "source_code": "C:\\private\\path",
        },
    ],
)
def test_r27_parser_rejects_wrong_custody_type_phase_or_code(diagnostic):
    whole, _raw = _load(WHOLE_PATH, "r27_parser_reject_fixture")
    assert whole._valid_child_exception_diagnostic(diagnostic) is False
    document = _valid_exception_frame()
    document["exception_diagnostic"] = diagnostic
    frame = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    with pytest.raises(whole.SupervisorBlocked):
        whole._parse_r12_frame(frame, 2)


def test_r27_parser_preserves_unknown_code_only_as_unobserved():
    whole, _raw = _load(WHOLE_PATH, "r27_unknown_parser_fixture")
    invoke, _invoke_raw = _load(INVOKE_PATH, "r27_unknown_parser_invoke_fixture")
    assert whole._R27_SOURCE_CUSTODY_CODES == invoke._SOURCE_CUSTODY_ENTERED_ROOT_CODES
    diagnostic = {
        "phase": "source_custody_entered",
        "exception_type": "RootEnvelopeError",
        "source_code": "UNOBSERVED",
    }
    assert whole._valid_child_exception_diagnostic(diagnostic) is True
    document = _valid_exception_frame()
    document["exception_diagnostic"] = diagnostic
    frame = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    parsed = whole._parse_r12_frame(frame, 2)
    assert parsed["child_exception_diagnostic"] == diagnostic

