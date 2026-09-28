"""Safety tests for the explicit AI wheel review-interop verifier."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "run_iteration41_ai_wheel_interop.py"


def _verifier_module():
    name = "iteration41_ai_wheel_interop_test_module"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _arguments(tmp_path: Path) -> Namespace:
    wheels = []
    for name in ("agent", "skills", "mcp"):
        wheel = tmp_path / (name + ".whl")
        wheel.write_bytes((name + " wheel").encode("ascii"))
        wheels.append(wheel)
    return Namespace(agent_wheel=wheels[0], skills_wheel=wheels[1], mcp_wheel=wheels[2])


def test_wheel_input_validation_requires_three_distinct_regular_wheels(tmp_path: Path) -> None:
    verifier = _verifier_module()
    arguments = _arguments(tmp_path)

    values = verifier._wheel_inputs(arguments)

    assert [item[0] for item in values] == [
        "backtrader-agent",
        "backtrader-skills",
        "backtrader-mcp",
    ]
    arguments.mcp_wheel = arguments.agent_wheel
    with pytest.raises(verifier.AiWheelInteropError, match="distinct"):
        verifier._wheel_inputs(arguments)


def test_wheel_input_validation_rejects_non_wheel_and_missing_files(tmp_path: Path) -> None:
    verifier = _verifier_module()
    arguments = _arguments(tmp_path)
    arguments.skills_wheel = tmp_path / "skills.txt"
    arguments.skills_wheel.write_text("not a wheel", encoding="utf-8")

    with pytest.raises(verifier.AiWheelInteropError, match=".whl"):
        verifier._wheel_inputs(arguments)

    arguments.skills_wheel = tmp_path / "missing.whl"
    with pytest.raises(verifier.AiWheelInteropError, match="unavailable"):
        verifier._wheel_inputs(arguments)


def test_verifier_uses_a_no_index_no_deps_install_and_isolated_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _verifier_module()
    arguments = _arguments(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(tuple(command))
        if "-c" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "status": "AI_WHEEL_REVIEW_INTEROP_PASS",
                        "evidence_sha256": "a" * 64,
                    }
                ),
                "",
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)
    result = verifier.verify_wheel_interop(
        verifier._wheel_inputs(arguments), python_executable=Path(sys.executable)
    )

    install, child = calls
    assert "--no-index" in install
    assert "--no-deps" in install
    assert "--target" in install
    assert "-I" in child
    assert "-S" in child
    assert result["status"] == "LOCAL_WHEEL_REVIEW_INTEROP_PASS"
    assert result["authority"] == "review_only"
