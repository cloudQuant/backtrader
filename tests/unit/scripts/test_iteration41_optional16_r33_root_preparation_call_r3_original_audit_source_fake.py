"""Focused fake regression for the R3 caller under Root's original audit.

This loads public V3, V4, and Call R3 source and exercises its same-scope
binding before the production-only preparation guard. The source-scope reads
use the existing fake file-handle fixture; software and credential inputs are
not accessed.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
CALL_R2_PATH = REPO_ROOT / "scripts/iteration41_optional16_r33_root_preparation_call_r2.py"
CALL_R3_PATH = REPO_ROOT / "scripts/iteration41_optional16_r33_root_preparation_call_r3.py"
PREPARATION_PATH = REPO_ROOT / "scripts/iteration41_optional16_r33_root_preparation_r1.py"
V3_PATH = REPO_ROOT / "scripts/iteration41_root_held_source_scope_v3.py"
V4_PATH = REPO_ROOT / "scripts/iteration41_root_held_source_scope_v4.py"
ROOT_RUNNER = REPO_ROOT / ".codex-tmp/optional16_root_preparation_actual_20261009.py"
R2_SCOPE_TEST = REPO_ROOT / (
    "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r2_source_fake.py"
)

V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"
PREPARATION_SHA256 = "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4"
V3_MODULE_NAME = "_iteration41_root_held_source_scope_v3_pinned_for_v4"
V4_MODULE_NAME = "_iteration41_optional16_r33_entry_v4"


def _read_public(path: Path) -> bytes:
    raw = path.read_bytes()
    assert type(raw) is bytes and raw
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_plain_module(name: str, path: Path, raw: bytes, digest: str):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = digest
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module


def _root_namespace_without_run(raw: bytes):
    """Load the exact audit function without executing Root's actual runner."""
    tree = ast.parse(raw.decode("utf-8", "strict"))
    filtered = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PREP_RESULT"
            for target in node.targets
        ):
            continue
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not PREP_RESULT['host_exit_permitted']":
            continue
        filtered.append(node)
    tree.body = filtered
    ast.fix_missing_locations(tree)
    module = types.ModuleType("__main__")
    exec(compile(tree, str(ROOT_RUNNER), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    return module.__dict__


def _r2_fake_scope_helpers():
    spec = importlib.util.spec_from_file_location("_optional16_r2_scope_fake_helpers", R2_SCOPE_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_original_audit_case():
    call_r2_raw = _read_public(CALL_R2_PATH)
    call_r3_raw = _read_public(CALL_R3_PATH)
    prep_raw = _read_public(PREPARATION_PATH)
    v3_raw = _read_public(V3_PATH)
    v4_raw = _read_public(V4_PATH)
    root_raw = _read_public(ROOT_RUNNER)
    assert _sha(v3_raw) == V3_SHA256
    assert _sha(v4_raw) == V4_SHA256
    assert _sha(prep_raw) == PREPARATION_SHA256

    # Use the existing fake OS/file-handle implementation with the unchanged
    # production V3/V4 scope code. It contains no account or software payload.
    scope_helpers = _r2_fake_scope_helpers()
    call_r2 = _load_plain_module("_r3_audit_regression_r2", CALL_R2_PATH, call_r2_raw, _sha(call_r2_raw))
    v3_actual = call_r2._make_module(V3_MODULE_NAME, call_r2.V3_REL, v3_raw, V3_SHA256)
    prior_alias = sys.modules.get(V3_MODULE_NAME)
    sys.modules[V3_MODULE_NAME] = v3_actual
    try:
        v4_actual = call_r2._make_module(V4_MODULE_NAME, call_r2.V4_REL, v4_raw, V4_SHA256)
        assert v4_actual._V3_MODULE is v3_actual
        assert sys.modules[V3_MODULE_NAME] is v3_actual
        scope, fake_api = scope_helpers._sourcefake_v4_scope(v4_actual, v3_raw, v4_raw)

        root_namespace = _root_namespace_without_run(root_raw)
        expected = root_namespace["PREP_CODES"]
        for path, raw in (
            (CALL_R3_PATH, call_r3_raw),
            (PREPARATION_PATH, prep_raw),
            (V3_PATH, v3_raw),
            (V4_PATH, v4_raw),
        ):
            origin = str(path.resolve())
            expected[origin] = compile(raw, origin, "exec", dont_inherit=True)
        original_result = {"status": "BLOCKED", "formal_optional16_pass_count": 0}
        root_namespace["PREP_RESULT"] = original_result
        sys.addaudithook(root_namespace["audit"])

        # The frozen R2 transform changes V4's code object under its pinned
        # filename; the original Root audit rejects it before source release.
        v3_reference = call_r2._make_module(V3_MODULE_NAME, call_r2.V3_REL, v3_raw, V3_SHA256)
        with pytest.raises(call_r2.RootPreparationCallError, match="v4_reference_compile_failed"):
            call_r2._v4_reference(v3_reference, v4_raw)
        assert sys.modules[V3_MODULE_NAME] is v3_actual

        # Load Call R3 after the original audit is installed, as the Root
        # runner does for pinned source. Its nested V3 reference is compiled
        # independently, while V4 is executed from exact unchanged source.
        call_r3 = _load_plain_module(
            "_iteration41_optional16_r33_root_preparation_call_r3_pinned",
            CALL_R3_PATH,
            call_r3_raw,
            _sha(call_r3_raw),
        )
        # Force the isolated loader to fail after the alias swap. This is a
        # fake leaf failure used to prove the exact original alias is restored
        # before the normal sourcefake composition continues.
        reference_v3 = call_r3._make_module(
            V3_MODULE_NAME, call_r3.V3_REL, v3_raw, V3_SHA256
        )
        load_module = call_r3._make_module

        def fail_reference_load(*_args, **_kwargs):
            raise RuntimeError("synthetic reference-load failure")

        call_r3._make_module = fail_reference_load
        try:
            with pytest.raises(call_r3.RootPreparationCallError, match="v4_reference_compile_failed"):
                call_r3._v4_reference(reference_v3, v4_raw, v3_actual)
        finally:
            call_r3._make_module = load_module
        assert sys.modules[V3_MODULE_NAME] is v3_actual

        result = call_r3.prepare_root_source_verification(
            scope,
            v4_actual,
            b"{}",
            {"v3": v3_raw, "v4": v4_raw},
            prep_raw,
            requested=True,
        )

        assert result["status"] == "BLOCKED_RETAINED"
        assert result["reason_code"] == "source_binding_or_preparation_failed"
        assert result["diagnostic_phase"] == "scope_reread"
        assert result["diagnostic_category"] == "source_contract"
        assert result["diagnostic_code"] == "scope_reread_rejected"
        assert scope.test_only is True and scope.state == "OPEN"
        assert scope in v3_actual._RETAINED_SCOPES
        assert v4_actual._V3_MODULE is v3_actual
        assert sys.modules[V3_MODULE_NAME] is v3_actual
        assert root_namespace["PREP_RESULT"] is original_result
        assert fake_api.read_count > 0
        assert str(V3_PATH.resolve()) in root_namespace["PREP_EXEC"]
        assert str(V4_PATH.resolve()) in root_namespace["PREP_EXEC"]
        assert str(PREPARATION_PATH.resolve()) not in root_namespace["PREP_EXEC"]
        assert call_r3._RETAINED and call_r3._RETAINED[-1][0] is scope
        assert result["authority"] == "NONE"
        assert result["activation"] == result["control"] == result["child"] == "NOT_ENTERED"
        assert "installer" not in result and "worker" not in result
    finally:
        if "scope" in locals() and scope.state == "OPEN":
            assert scope.release(0, True) is True
        if prior_alias is None:
            sys.modules.pop(V3_MODULE_NAME, None)
        else:
            sys.modules[V3_MODULE_NAME] = prior_alias


def test_call_r3_uses_exact_v4_source_under_original_root_audit():
    """Run the irreversible audit hook in a fresh child process."""
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--original-audit-child"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (
        f"audit child failed: stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )


if __name__ == "__main__" and sys.argv[1:] == ["--original-audit-child"]:
    _run_original_audit_case()
