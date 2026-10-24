"""Focused checks for the public Iteration 50 wheel consumer fixture."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
import zipfile

import pytest


_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "iteration50_installed_fixture.py"


def _load_fixture(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    spec = importlib.util.spec_from_file_location(
        "iteration50_installed_fixture_test", _FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _hash_field(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode("ascii")
    return "sha256=" + encoded.rstrip("=")


class _Distribution:
    def __init__(self, root: Path) -> None:
        self.root = root

    def locate_file(self, path: object) -> Path:
        return self.root / str(path)


def _write_record(root: Path, rows: list[tuple[str, bytes]], record_name: str) -> str:
    record_path = root / record_name
    record_path.parent.mkdir(parents=True, exist_ok=True)
    contents = []
    for name, payload in rows:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        contents.append("%s,%s,%d" % (name, _hash_field(payload), len(payload)))
    contents.append(record_name + ",,")
    record_text = "\n".join(contents) + "\n"
    record_path.write_text(record_text, encoding="utf-8", newline="")
    return record_text


def test_record_verifier_checks_payloads_and_allows_installed_script_scheme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    record_name = "back_trader_python-1.0.dist-info/RECORD"
    source_name = "backtrader/research/live.py"
    script_name = "../../Scripts/bt-runtime.exe"
    record_text = _write_record(
        site_packages,
        [
            (source_name, b"public production module\n"),
            (script_name, b"generated launcher\n"),
        ],
        record_name,
    )

    verified, record_sha256 = fixture._verify_record(
        record_text,
        _Distribution(site_packages),
        site_packages,
        (venv,),
    )

    assert verified[source_name] == hashlib.sha256(b"public production module\n").hexdigest()
    assert verified[script_name] == hashlib.sha256(b"generated launcher\n").hexdigest()
    assert record_sha256 == hashlib.sha256(record_text.encode("utf-8")).hexdigest()

    (venv / "Scripts" / "bt-runtime.exe").write_bytes(b"tampered launcher\n")
    with pytest.raises(ValueError, match="differs from wheel RECORD"):
        fixture._verify_record(
            record_text,
            _Distribution(site_packages),
            site_packages,
            (venv,),
        )


def test_record_verifier_rejects_duplicate_and_escaping_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    record_name = "back_trader_python-1.0.dist-info/RECORD"
    source_name = "backtrader/__init__.py"
    source = b"source\n"
    record_text = _write_record(site_packages, [(source_name, source)], record_name)
    duplicate = record_text.replace(
        record_name + ",,\n",
        "%s,%s,%d\n%s,,\n" % (source_name, _hash_field(source), len(source), record_name),
    )
    with pytest.raises(ValueError, match="duplicate path"):
        fixture._verify_record(duplicate, _Distribution(site_packages), site_packages, (venv,))

    outside = tmp_path.parent / "escape.bin"
    outside.write_bytes(b"outside\n")
    escaped_name = "../../../../escape.bin"
    escaped_text = _write_record(
        site_packages,
        [(escaped_name, b"outside\n")],
        record_name,
    )
    with pytest.raises(ValueError, match="escapes recognized install roots"):
        fixture._verify_record(escaped_text, _Distribution(site_packages), site_packages, (venv,))


def test_module_origin_must_be_recorded_inside_installed_distribution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    root = tmp_path / "site-packages"
    module_path = root / "backtrader" / "research" / "live.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_bytes(b"installed source\n")
    digest = hashlib.sha256(module_path.read_bytes()).hexdigest()
    module = ModuleType("installed_live")
    module.__file__ = str(module_path)

    assert (
        fixture._verified_module_origin(module, root, {"backtrader/research/live.py": digest})[
            "sha256"
        ]
        == digest
    )
    with pytest.raises(ValueError, match="absent from the installed RECORD"):
        fixture._verified_module_origin(module, root, {})

    module.__file__ = str(tmp_path / "checkout" / "backtrader" / "research" / "live.py")
    with pytest.raises(ValueError, match="did not load from the installed distribution"):
        fixture._verified_module_origin(module, root, {"backtrader/research/live.py": digest})


def test_nonexplicit_module_tamper_and_rewritten_record_are_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    root = tmp_path / "site-packages"
    module_name = "backtrader._cerebro.registry"
    relative_path = "backtrader/_cerebro/registry.py"
    module_path = root / relative_path
    module_path.parent.mkdir(parents=True)
    original = b"registry source from pinned wheel\n"
    tampered = b"registry source changed after install\n"
    module_path.write_bytes(original)
    init_path = root / "backtrader" / "__init__.py"
    init_path.parent.mkdir(parents=True, exist_ok=True)
    init_path.write_bytes(b"package root\n")
    module = ModuleType(module_name)
    module.__file__ = str(module_path)
    init_name = "backtrader/__init__.py"
    init_hash = hashlib.sha256(init_path.read_bytes()).hexdigest()
    wheel_hashes = {
        relative_path: hashlib.sha256(original).hexdigest(),
        init_name: init_hash,
    }
    original_record = {
        relative_path: hashlib.sha256(original).hexdigest(),
        init_name: init_hash,
    }
    assert (
        fixture._verify_installed_package_payloads(
            _Distribution(root),
            root,
            original_record,
            wheel_hashes,
        )
        == 2
    )
    before = fixture._snapshot_loaded_package_modules(
        root,
        original_record,
        wheel_hashes,
        modules={module_name: module},
    )

    module_path.write_bytes(tampered)
    rewritten_record = {
        relative_path: hashlib.sha256(tampered).hexdigest(),
        init_name: init_hash,
    }

    with pytest.raises(ValueError, match="loaded Backtrader module differs from the pinned wheel"):
        fixture._snapshot_loaded_package_modules(
            root,
            rewritten_record,
            wheel_hashes,
            previous=before,
            modules={module_name: module},
        )
    with pytest.raises(
        ValueError, match="installed Backtrader package payload differs from the pinned wheel"
    ):
        fixture._verify_installed_package_payloads(
            _Distribution(root),
            root,
            rewritten_record,
            wheel_hashes,
        )


def test_wheel_archive_hash_metadata_and_record_are_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    wheel_path = tmp_path / "back_trader_python-1.0.0-py3-none-any.whl"
    record_name = "back_trader_python-1.0.0.dist-info/RECORD"
    payloads = {
        "backtrader/__init__.py": b"wheel module\n",
        "back_trader_python-1.0.0.dist-info/METADATA": (
            b"Metadata-Version: 2.1\nName: back-trader-python\nVersion: 1.0.0\n\n"
        ),
        "back_trader_python-1.0.0.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n" b"Tag: py3-none-any\n"
        ),
    }
    rows = [
        "%s,%s,%d" % (name, _hash_field(payload), len(payload))
        for name, payload in payloads.items()
    ]
    payloads[record_name] = ("\n".join(rows + [record_name + ",,"]) + "\n").encode("utf-8")
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    expected_sha256 = hashlib.sha256(wheel_path.read_bytes()).hexdigest()

    identity = fixture._verify_wheel_archive(wheel_path, expected_sha256)

    assert identity["sha256"] == expected_sha256
    assert identity["name"] == "back-trader-python"
    assert identity["version"] == "1.0.0"
    assert identity["record_entries_verified"] == len(payloads) - 1
    assert (
        identity["payload_hashes"]["backtrader/__init__.py"]
        == hashlib.sha256(payloads["backtrader/__init__.py"]).hexdigest()
    )

    tampered = tmp_path / "tampered.whl"
    with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            if name == "backtrader/__init__.py":
                payload = b"changed module\n"
            archive.writestr(name, payload)
    with pytest.raises(ValueError, match="differs from RECORD"):
        fixture._verify_wheel_archive(tampered, hashlib.sha256(tampered.read_bytes()).hexdigest())


def test_fixture_cli_rejects_unimplemented_profiles_and_factor_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture(monkeypatch)
    with pytest.raises(SystemExit) as profile_error:
        fixture.main(
            ["--wheel", "candidate.whl", "--wheel-sha256", "0" * 64, "--profile", "execution"]
        )
    assert profile_error.value.code == 2

    with pytest.raises(SystemExit) as mode_error:
        fixture.main(
            ["--wheel", "candidate.whl", "--wheel-sha256", "0" * 64, "--factor-mode", "unknown"]
        )
    assert mode_error.value.code == 2

    with pytest.raises(SystemExit) as missing_artifact:
        fixture.main([])
    assert missing_artifact.value.code == 2


def test_fixture_process_rejects_ambient_pythonpath_before_importing_package(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(_FIXTURE_PATH.parents[1])
    completed = subprocess.run(
        [sys.executable, str(_FIXTURE_PATH), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "installed fixture requires PYTHONPATH to be unset" in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr


def test_read_only_fixture_uses_production_strategy_broker_and_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture(monkeypatch)
    native = fixture._run_read_only_mode("native")
    build = fixture._run_read_only_mode("build")

    assert native["batch_complete"] is True
    assert build["batch_complete"] is True
    assert native["readiness"] == build["readiness"] == "LIVE_READY"
    assert native["target_count"] == build["target_count"] == len(fixture._TARGETS)
    assert native["order_callbacks"] == build["order_callbacks"] == 0
    for target in fixture._TARGETS:
        assert native["values"][target] == pytest.approx(
            build["values"][target], rel=1e-9, abs=1e-12
        )
