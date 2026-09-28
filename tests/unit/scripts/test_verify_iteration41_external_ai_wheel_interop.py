"""Unit coverage for the local, review-only external AI wheel verifier."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_iteration41_external_ai_wheel_interop.py"


def _verifier_module():
    name = "iteration41_external_ai_wheel_interop_test_module"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _record_value(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode("ascii")
    return "sha256=" + encoded.rstrip("=")


def test_replay_config_uses_the_sealed_package_fixture() -> None:
    verifier = _verifier_module()

    config = verifier._load_replay_config(REPOSITORY_ROOT)

    assert config["mode"] == "simulation"
    assert config["preset"] == "replay"
    assert config["strategy_id"] == "example.013_3.sa_midfreq_simnow"
    assert len(config["config_digest"]) == 64
    assert len(config["artifact_sha256"]) == 64


def test_record_digest_rejects_invalid_values() -> None:
    verifier = _verifier_module()
    payload = b"deployment-evidence"

    assert verifier._record_digest(_record_value(payload)) == hashlib.sha256(payload).hexdigest()
    with pytest.raises(verifier.InteropError, match="unsupported"):
        verifier._record_digest("md5=abc")
    with pytest.raises(verifier.InteropError, match="invalid"):
        verifier._record_digest("sha256=!")


def test_wheel_member_verification_binds_metadata_and_record(tmp_path: Path) -> None:
    verifier = _verifier_module()
    member = "backtrader_agent/deployment_evidence.py"
    payload = b"VALUE = 'read-only'\n"
    record = "{0},{1},{2}\n".format(member, _record_value(payload), len(payload))
    wheel = tmp_path / "backtrader_agent-0.2.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(member, payload)
        archive.writestr(
            "backtrader_agent-0.2.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: backtrader-agent\nVersion: 0.2.0\n",
        )
        archive.writestr("backtrader_agent-0.2.0.dist-info/RECORD", record)

    result = verifier._verify_wheel_member(wheel, "backtrader-agent", member)

    assert result["record_verified"] is True
    assert result["version"] == "0.2.0"
    assert result["wheel_sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()


def test_source_wheel_build_cannot_use_an_index_or_build_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = _verifier_module()
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    source_roots = {}
    for label, distribution, _package, _member in verifier._PRODUCTS:
        source = tmp_path / label
        source.mkdir()
        (source / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
        source_roots[label] = source
        (wheel_dir / (distribution.replace("-", "_") + "-0.2.0-py3-none-any.whl")).write_bytes(
            b"wheel"
        )

    commands = []

    def fake_run(command, cwd, environment=None):
        commands.append((tuple(command), environment))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(verifier, "_run", fake_run)
    wheels = verifier._build_wheels(sys.executable, source_roots, wheel_dir, tmp_path)

    assert set(wheels) == {"agent", "skills", "mcp"}
    assert len(commands) == 3
    for command, environment in commands:
        assert "--no-index" in command
        assert "--no-deps" in command
        assert "--no-build-isolation" in command
        assert environment["SOURCE_DATE_EPOCH"] == verifier._BUILD_SOURCE_DATE_EPOCH

    commands.clear()
    wheelhouse = tmp_path / "approved-wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "hatchling-1.25.0-py3-none-any.whl").write_bytes(b"offline-backend")
    verifier._build_wheels(
        sys.executable,
        source_roots,
        wheel_dir,
        tmp_path,
        build_wheelhouse=wheelhouse,
    )
    assert len(commands) == 3
    for command, environment in commands:
        assert "--no-index" in command
        assert "--no-deps" in command
        assert "--no-build-isolation" not in command
        assert command[command.index("--find-links") + 1] == str(wheelhouse)
        assert environment["SOURCE_DATE_EPOCH"] == verifier._BUILD_SOURCE_DATE_EPOCH
