"""Focused checks for the public Iteration 50 wheel consumer fixture."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import py_compile
import subprocess
import sys
from types import ModuleType, SimpleNamespace
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


def _append_unhashed_record_row(
    root: Path, record_name: str, record_text: str, relative_name: str
) -> str:
    updated = record_text.replace(
        record_name + ",,\n",
        relative_name + ",,\n" + record_name + ",,\n",
    )
    assert updated != record_text
    (root / record_name).write_text(updated, encoding="utf-8", newline="")
    return updated


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

    verified, record_sha256, generated_pyc_count = fixture._verify_record(
        record_text,
        _Distribution(site_packages),
        site_packages,
        (venv,),
    )

    assert generated_pyc_count == 0
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


def test_record_verifier_accepts_only_unhashed_generated_pyc_auxiliaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    record_name = "back_trader_python-1.0.dist-info/RECORD"
    init_name = "backtrader/__init__.py"
    source_name = "backtrader/research/live.py"
    record_text = _write_record(
        site_packages,
        [(init_name, b"# package root\n"), (source_name, b"# public research module\n")],
        record_name,
    )
    source_path = site_packages / source_name
    cache_name = (
        Path(py_compile.compile(str(source_path), doraise=True))
        .relative_to(site_packages)
        .as_posix()
    )
    record_text = _append_unhashed_record_row(site_packages, record_name, record_text, cache_name)

    verified, record_sha256, generated_pyc_count = fixture._verify_record(
        record_text,
        _Distribution(site_packages),
        site_packages,
        (venv,),
    )

    assert generated_pyc_count == 1
    assert cache_name not in verified
    assert set(verified) == {init_name, source_name}
    assert record_sha256 == hashlib.sha256(record_text.encode("utf-8")).hexdigest()
    assert (
        fixture._verify_installed_package_payloads(
            _Distribution(site_packages),
            site_packages,
            verified,
            verified,
        )
        == 2
    )


@pytest.mark.parametrize(
    "relative_name,payload",
    [
        ("backtrader/research/unhashed.py", b"unhashed source\n"),
        ("backtrader/data/manifest.json", b"unhashed asset\n"),
    ],
)
def test_record_verifier_rejects_unhashed_non_pyc_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative_name: str,
    payload: bytes,
) -> None:
    fixture = _load_fixture(monkeypatch)
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    record_name = "back_trader_python-1.0.dist-info/RECORD"
    record_text = _write_record(site_packages, [], record_name)
    target = site_packages / relative_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    record_text = _append_unhashed_record_row(
        site_packages, record_name, record_text, relative_name
    )

    with pytest.raises(ValueError, match="unhashed installed RECORD entry is not a generated pyc"):
        fixture._verify_record(
            record_text,
            _Distribution(site_packages),
            site_packages,
            (venv,),
        )


def test_record_verifier_rejects_unmapped_and_outside_generated_pyc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    record_name = "back_trader_python-1.0.dist-info/RECORD"
    record_text = _write_record(site_packages, [], record_name)
    orphan_source = site_packages / "backtrader" / "orphan.py"
    orphan_cache = Path(importlib.util.cache_from_source(str(orphan_source)))
    orphan_cache.parent.mkdir(parents=True, exist_ok=True)
    orphan_cache.write_bytes(b"orphan cache\n")
    orphan_name = orphan_cache.relative_to(site_packages).as_posix()
    orphan_record = _append_unhashed_record_row(
        site_packages, record_name, record_text, orphan_name
    )
    with pytest.raises(
        ValueError, match="generated bytecode cache does not map to an installed source"
    ):
        fixture._verify_record(orphan_record, _Distribution(site_packages), site_packages, (venv,))

    source_name = "backtrader/research/live.py"
    valid_record = _write_record(
        site_packages,
        [(source_name, b"# verified source\n")],
        record_name,
    )
    valid_cache = Path(py_compile.compile(str(site_packages / source_name), doraise=True))
    traversal_name = "../site-packages/" + valid_cache.relative_to(site_packages).as_posix()
    traversal_record = _append_unhashed_record_row(
        site_packages, record_name, valid_record, traversal_name
    )
    with pytest.raises(ValueError, match="generated bytecode cache path uses parent traversal"):
        fixture._verify_record(
            traversal_record,
            _Distribution(site_packages),
            site_packages,
            (venv,),
        )

    outside = tmp_path / "outside"
    outside_source = outside / "outside.py"
    outside_source.parent.mkdir(parents=True)
    outside_source.write_text("# outside source\n", encoding="utf-8")
    outside_cache = Path(py_compile.compile(str(outside_source), doraise=True))
    outside_name = os.path.relpath(outside_cache, site_packages).replace(os.sep, "/")
    outside_record = _write_record(site_packages, [], record_name)
    outside_record = _append_unhashed_record_row(
        site_packages, record_name, outside_record, outside_name
    )
    with pytest.raises(ValueError, match="escapes recognized install roots"):
        fixture._verify_record(
            outside_record,
            _Distribution(site_packages),
            site_packages,
            (venv,),
        )


def test_record_verifier_rejects_tampered_source_for_generated_pyc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    venv = tmp_path / "venv"
    site_packages = venv / "Lib" / "site-packages"
    record_name = "back_trader_python-1.0.dist-info/RECORD"
    source_name = "backtrader/research/live.py"
    source = b"# pinned source\n"
    record_text = _write_record(site_packages, [(source_name, source)], record_name)
    source_path = site_packages / source_name
    cache_name = (
        Path(py_compile.compile(str(source_path), doraise=True))
        .relative_to(site_packages)
        .as_posix()
    )
    record_text = _append_unhashed_record_row(site_packages, record_name, record_text, cache_name)
    source_path.write_bytes(b"# tampered source\n")

    with pytest.raises(ValueError, match="installed file differs from wheel RECORD"):
        fixture._verify_record(
            record_text,
            _Distribution(site_packages),
            site_packages,
            (venv,),
        )


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


def test_isolated_launcher_uses_external_cwd_and_clears_import_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _load_fixture(monkeypatch)
    ambient_names = tuple(
        sorted(
            set(fixture._AMBIENT_IMPORT_ENVIRONMENT)
            .union(name for name in os.environ if name.upper().startswith("PYTHON"))
            .union({"PYTHONWARNINGS"})
        )
    )
    for name in ambient_names:
        monkeypatch.setenv(name, "poisoned-import-value")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture._run_isolated_entry(
        [
            "--wheel",
            "fixed.whl",
            "--wheel-sha256",
            "a" * 64,
            "--profile",
            "alpha101-stream",
            "--factor-mode",
            "both",
        ]
    )

    assert result == 0
    assert captured["command"][:2] == [sys.executable, "-I"]
    assert captured["command"][2] == str(_FIXTURE_PATH.resolve())
    assert Path(captured["command"][4]).is_absolute()
    assert captured["command"][5:] == [
        "--wheel-sha256",
        "a" * 64,
        "--profile",
        "alpha101-stream",
        "--factor-mode",
        "both",
    ]
    assert Path(captured["cwd"]).resolve() != tmp_path.resolve()
    assert not Path(captured["cwd"]).resolve().is_relative_to(fixture._REPOSITORY_ROOT)
    assert all(captured["env"][name] == captured["cwd"] for name in ("TMP", "TEMP", "TMPDIR"))
    assert all(name not in captured["env"] for name in ambient_names)
    assert json.loads(captured["env"][fixture._PARENT_CLEARED_ENVIRONMENT_MARKER]) == list(
        ambient_names
    )


def test_alpha101_profile_requires_same_stream_native_and_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = _load_fixture(monkeypatch)
    with pytest.raises(SystemExit) as profile_error:
        fixture.main(
            [
                "--wheel",
                "candidate.whl",
                "--wheel-sha256",
                "0" * 64,
                "--profile",
                "alpha101-stream",
                "--factor-mode",
                "native",
            ]
        )

    assert profile_error.value.code == 2
    assert "requires --factor-mode both" in capsys.readouterr().err


def test_alpha101_bindings_and_stream_comparison_keep_exact_reasons_and_finite_tolerance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture(monkeypatch)

    class _Indicator:
        formula_fields = ("vwap", "dollar_volume", "adv20", "sector")

    bindings = fixture._alpha101_field_bindings(_Indicator)
    assert bindings == {
        "vwap": "feed:target:vwap",
        "dollar_volume": "feed:target:dollar_volume",
        "adv20": {"derive": "adv", "source": "dollar_volume", "window": 20},
        "sector": "feed:target:sector",
    }
    policies = fixture._alpha101_field_policies(_Indicator)
    assert set(policies) == set(bindings)
    assert policies["vwap"].unit == fixture._FIELD_PIT_UNITS["vwap"]
    assert policies["dollar_volume"].unit == fixture._FIELD_PIT_UNITS["dollar_volume"]
    assert policies["adv20"].unit == "USD"
    assert policies["sector"].unit == fixture._FIELD_PIT_UNITS["sector"]
    assert fixture._same_stream_value(float("nan"), float("nan"))
    assert not fixture._same_stream_value(float("inf"), float("inf"))
    assert not fixture._same_stream_value(float("inf"), float("-inf"))
    assert not fixture._same_stream_value(1.0, float("inf"))
    assert fixture._same_stream_value(1.0, 1.0 + 5e-11)
    assert not fixture._same_stream_value(1.0, 1.0 + 2e-10)


def test_alpha101_stream_fixture_and_factor_selection_cover_all_fixed_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture(monkeypatch)
    bars, calendar = fixture._fixture_bars(
        5,
        include_extra_fields=True,
        varied_stream=True,
    )

    assert len(calendar.slots) == 5
    assert set(bars) == set(fixture._TARGETS)
    for target, rows in bars.items():
        assert len(rows) == 5
        for row in rows:
            assert set(fixture._EXTRA_FIELDS).issubset(row)
            assert all(math.isfinite(float(row[field])) for field in fixture._EXTRA_FIELDS)
            assert set(row["field_observations"]) == set(fixture._FIELD_PIT_UNITS)
            for field_name, observation in row["field_observations"].items():
                assert observation.source_ref == fixture._alpha101_source_ref(target, field_name)
                assert observation.unit == fixture._FIELD_PIT_UNITS[field_name]
                assert observation.effective_at < observation.available_at
                assert observation.valid_until > observation.available_at
            assert row["vwap"] != (row["open"] + row["high"] + row["low"] + row["close"]) / 4.0
            assert not math.isclose(
                row["dollar_volume"],
                row["vwap"] * row["volume"],
                rel_tol=1e-9,
                abs_tol=1e-9,
            )

    factors = fixture._alpha101_factor_specs()
    assert len(factors) == 202
    for alpha_id in range(1, 102):
        native = factors["alpha%d_native" % alpha_id]
        build = factors["alpha%d_build" % alpha_id]
        assert native.indicator is build.indicator is fixture.get_alpha(alpha_id)
        assert native.mode == "native"
        assert build.mode == "build"
        assert set(native.field_bindings) == set(native.indicator.formula_fields)
        assert set(native.field_policies) == set(native.indicator.formula_fields)
        assert set(build.field_policies) == set(build.indicator.formula_fields)


def _valid_alpha101_witness_fixture(fixture):
    expected_points = 9
    expected_evaluation_points = 6
    factor_pairs = {
        str(alpha_id): {
            "output_available_witnesses": 1,
            "finite_witnesses": 1,
            "evaluation_available_finite_witnesses": 1,
            "pit_qualified_evaluation_points": expected_evaluation_points,
        }
        for alpha_id in fixture._ALPHA101_REQUIRED_OUTPUT_WITNESS_IDS
    }
    extra_fields = {
        field_name: {
            "values_checked": expected_points,
            "finite_witnesses": expected_points,
            "pit_qualified_witnesses": expected_evaluation_points,
            "unit": fixture._FIELD_PIT_UNITS[field_name],
            "source_refs": sorted(
                fixture._alpha101_source_ref(target, field_name) for target in fixture._TARGETS
            ),
            "first_effective_at": "2025-01-02T09:30:59+00:00",
            "first_available_at": "2025-01-02T09:31:00+00:00",
            "first_valid_until": "2025-01-02T09:36:00+00:00",
            "first_evaluated_at": "2025-01-02T09:31:00+00:00",
            "last_effective_at": "2025-01-02T09:39:59+00:00",
            "last_available_at": "2025-01-02T09:40:00+00:00",
            "last_valid_until": "2025-01-02T09:45:00+00:00",
            "last_evaluated_at": "2025-01-02T09:40:00+00:00",
            "distinct_from_ohlc_witnesses": expected_points,
        }
        for field_name in fixture._ALPHA101_EXTRA_WITNESS_FACTORS
    }
    return factor_pairs, extra_fields, expected_points, expected_evaluation_points


def test_alpha101_stream_witness_gate_requires_real_available_finite_and_pit_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture(monkeypatch)
    factor_pairs, extra_fields, expected_points, expected_eval = _valid_alpha101_witness_fixture(
        fixture
    )

    fixture._validate_alpha101_stream_witnesses(
        factor_pairs, extra_fields, expected_points, expected_eval
    )

    unavailable = {key: dict(value) for key, value in factor_pairs.items()}
    unavailable["3"]["output_available_witnesses"] = 0
    with pytest.raises(RuntimeError, match="no finite OUTPUT_AVAILABLE witness"):
        fixture._validate_alpha101_stream_witnesses(
            unavailable, extra_fields, expected_points, expected_eval
        )

    early_only = {key: dict(value) for key, value in factor_pairs.items()}
    early_only["3"]["evaluation_available_finite_witnesses"] = 0
    with pytest.raises(RuntimeError, match="no evaluation OUTPUT_AVAILABLE witness"):
        fixture._validate_alpha101_stream_witnesses(
            early_only, extra_fields, expected_points, expected_eval
        )

    missing_pit = {key: dict(value) for key, value in extra_fields.items()}
    missing_pit["subindustry"]["pit_qualified_witnesses"] = 0
    with pytest.raises(RuntimeError, match="PIT provenance witnesses"):
        fixture._validate_alpha101_stream_witnesses(
            factor_pairs, missing_pit, expected_points, expected_eval
        )


def test_alpha101_field_provenance_gate_requires_qualified_unit_source_and_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _load_fixture(monkeypatch)
    expected_evaluation_points = 6
    provenance = {
        field_name: {
            "row_count": 12,
            "pit_qualified_rows": expected_evaluation_points,
            "unit_counts": {unit: 12},
            "source_refs": sorted(
                fixture._alpha101_source_ref(target, field_name) for target in fixture._TARGETS
            ),
            "first_effective_at": "2025-01-02T09:30:59+00:00",
            "last_effective_at": "2025-01-02T09:39:59+00:00",
            "first_available_at": "2025-01-02T09:31:00+00:00",
            "last_available_at": "2025-01-02T09:40:00+00:00",
            "first_valid_until": "2025-01-02T09:36:00+00:00",
            "last_valid_until": "2025-01-02T09:45:00+00:00",
            "first_evaluated_at": "2025-01-02T09:31:00+00:00",
            "last_evaluated_at": "2025-01-02T09:40:00+00:00",
        }
        for field_name, unit in fixture._FIELD_PIT_UNITS.items()
    }
    fixture._validate_alpha101_field_provenance(provenance, expected_evaluation_points)

    unavailable = {key: dict(value) for key, value in provenance.items()}
    unavailable["vwap"]["pit_qualified_rows"] = 0
    with pytest.raises(RuntimeError, match="lacks source, unit, or PIT time witnesses"):
        fixture._validate_alpha101_field_provenance(unavailable, expected_evaluation_points)

    missing_availability = {key: dict(value) for key, value in provenance.items()}
    missing_availability["cap"]["last_available_at"] = None
    with pytest.raises(RuntimeError, match="lacks source, unit, or PIT time witnesses"):
        fixture._validate_alpha101_field_provenance(
            missing_availability, expected_evaluation_points
        )


def _fake_backtrader_package_source(sentinel: str) -> bytes:
    source = (
        "import os\n"
        "import sys\n"
        "import types\n"
        "\n"
        'SOURCE_SENTINEL = "__MARKER__"\n'
        "CACHE_PREFIX_AT_IMPORT = sys.pycache_prefix\n"
        "CACHE_PREFIX_EXISTS_AT_IMPORT = bool(\n"
        "    CACHE_PREFIX_AT_IMPORT and os.path.isdir(CACHE_PREFIX_AT_IMPORT)\n"
        ")\n"
        '__version__ = "1.4.0"\n'
        'Strategy = type("Strategy", (), {})\n'
        "\n"
        "def _install(name, names=(), package=False):\n"
        "    module = types.ModuleType(name)\n"
        "    if package:\n"
        "        module.__path__ = []\n"
        "    sys.modules[name] = module\n"
        '    parent_name, separator, child_name = name.rpartition(".")\n'
        "    if separator:\n"
        "        setattr(sys.modules[parent_name], child_name, module)\n"
        "    for item in names:\n"
        '        if item == "get_alpha":\n'
        "            value = lambda *args, **kwargs: None\n"
        "        else:\n"
        "            value = type(item, (), {})\n"
        "        setattr(module, item, value)\n"
        "\n"
        'for package_name in ("backtrader.brokers", "backtrader.feeds", "backtrader.research", "backtrader.stores"):\n'
        "    _install(package_name, package=True)\n"
        '_install("backtrader.brokers.btapibroker", ("BtApiBroker",))\n'
        '_install("backtrader.feeds.btapifeed", ("BtApiFeed",))\n'
        '_install("backtrader.research", ("FactorSpec", "FieldPITPolicy", "LiveFactorPlan", "LiveFactorSet"), package=True)\n'
        '_install("backtrader.research.alpha101", ("get_alpha",))\n'
        '_install("backtrader.research.live_cohort", ("LiveBarCohort", "LiveCalendarMemberSession", "LiveCalendarSlot", "LiveCohortCalendar", "LiveFieldContract", "LiveFieldObservation"))\n'
        '_install("backtrader.stores.btapistore", ("BtApiStore",))\n'
    )
    return source.replace("__MARKER__", sentinel).encode("utf-8")


def test_fixture_entrypoint_ignores_poisoned_timestamp_valid_bytecode(
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "installed"
    package_dir = package_root / "backtrader"
    package_dir.mkdir(parents=True)
    source_path = package_dir / "__init__.py"
    pinned_source = _fake_backtrader_package_source("pinned-source")
    poisoned_source = _fake_backtrader_package_source("poison-source")
    assert len(pinned_source) == len(poisoned_source)
    source_path.write_bytes(pinned_source)

    poisoned_source_path = tmp_path / "poisoned_source.py"
    poisoned_source_path.write_bytes(poisoned_source)
    fixed_timestamp = 1_700_000_000_000_000_000
    os.utime(source_path, ns=(fixed_timestamp, fixed_timestamp))
    os.utime(poisoned_source_path, ns=(fixed_timestamp, fixed_timestamp))
    pyc_path = Path(importlib.util.cache_from_source(str(source_path)))
    pyc_path.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(
        str(poisoned_source_path),
        cfile=str(pyc_path),
        dfile=str(source_path),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
    )
    os.utime(source_path, ns=(fixed_timestamp, fixed_timestamp))
    poisoned_cache = pyc_path.read_bytes()

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)

    control_code = (
        "import json,sys; sys.path.insert(0, "
        + repr(str(package_root))
        + "); import backtrader; print('UNISOLATED_CACHE=' + json.dumps("
        "backtrader.SOURCE_SENTINEL))"
    )
    control = subprocess.run(
        [sys.executable, "-S", "-c", control_code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert control.returncode == 0, control.stderr
    assert 'UNISOLATED_CACHE="poison-source"' in control.stdout

    cache_temp = tmp_path / "temp"
    cache_temp.mkdir()
    isolated_environment = dict(environment)
    isolated_environment["TMP"] = str(cache_temp)
    isolated_environment["TEMP"] = str(cache_temp)
    fixture_code = (
        "import json,runpy,sys; sys.path.insert(0, "
        + repr(str(package_root))
        + "); sys.argv=["
        + repr(str(_FIXTURE_PATH))
        + ", '--help']; \n"
        "try: runpy.run_path(" + repr(str(_FIXTURE_PATH)) + ", run_name='__main__')\n"
        "except SystemExit as result:\n"
        "    if result.code != 0: raise\n"
        "module=sys.modules['backtrader']; print('FIXTURE_CACHE=' + json.dumps({"
        "'sentinel': module.SOURCE_SENTINEL, 'prefix': module.CACHE_PREFIX_AT_IMPORT, "
        "'exists': module.CACHE_PREFIX_EXISTS_AT_IMPORT}))"
    )
    isolated = subprocess.run(
        [sys.executable, "-S", "-c", fixture_code],
        cwd=tmp_path,
        env=isolated_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert isolated.returncode == 0, isolated.stderr
    marker = next(
        line[len("FIXTURE_CACHE=") :]
        for line in reversed(isolated.stdout.splitlines())
        if line.startswith("FIXTURE_CACHE=")
    )
    result = json.loads(marker)
    assert result["sentinel"] == "pinned-source"
    assert result["exists"] is True
    assert Path(result["prefix"]).parent == cache_temp.resolve()
    assert Path(result["prefix"]).name.startswith("iteration50-installed-pycache-")
    assert pyc_path.read_bytes() == poisoned_cache


def test_fixture_entrypoint_rejects_preloaded_backtrader_before_cache_setup(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    code = (
        "import runpy,sys,types; sys.modules['backtrader']=types.ModuleType('backtrader'); "
        "sys.argv=[" + repr(str(_FIXTURE_PATH)) + ", '--help']; \n"
        "try: runpy.run_path(" + repr(str(_FIXTURE_PATH)) + ", run_name='__main__')\n"
        "except RuntimeError as error:\n"
        "    if 'unloaded before cache setup' not in str(error): raise\n"
        "    print('EXPECTED_REJECTION')\n"
        "else: raise AssertionError('preloaded Backtrader was accepted')"
    )
    completed = subprocess.run(
        [sys.executable, "-S", "-c", code],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "EXPECTED_REJECTION" in completed.stdout


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
