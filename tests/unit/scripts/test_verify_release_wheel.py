"""Synthetic checks for the release wheel's source identity audit."""

import base64
import ast
import builtins
import csv
import hashlib
import importlib.util
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "verify_release_wheel.py"
SPEC = importlib.util.spec_from_file_location("verify_release_wheel", SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)

VERSION = "1.4.0"
DIST_INFO = "back_trader_python-1.4.0.dist-info/"
RESOURCE = "backtrader/configs/account_config_example.yaml"


def _fixture_files():
    files = {
        "backtrader/__init__.py": b"__version__ = '1.4.0'\n",
        "backtrader/cerebro.py": b"class Cerebro: pass\n",
        "backtrader/_cerebro/__init__.py": b"\n",
    }
    files.update(
        {
            "backtrader/_cerebro/module_{0}.py".format(index): "VALUE = {0}\n".format(
                index
            ).encode()
            for index in range(8)
        }
    )
    return files


def _record_contents(archive_files, record_name):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name, contents in archive_files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode("ascii")
        writer.writerow((name, "sha256=" + digest.rstrip("="), str(len(contents))))
    writer.writerow((record_name, "", ""))
    return output.getvalue().encode("utf-8")


def _tamper_record(archive_files, record_name, field):
    rows = list(
        csv.reader(io.StringIO(_record_contents(archive_files, record_name).decode("utf-8")))
    )
    row = next(row for row in rows if row[0] == "backtrader/cerebro.py")
    if field == "digest":
        row[1] = row[1][:-1] + ("A" if row[1][-1] != "A" else "B")
    else:
        row[2] = str(int(row[2]) + 1)
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue().encode("utf-8")


def _write_fixture(
    tmp_path,
    wheel_changes=None,
    duplicate_members=(),
    omit_wheel_members=(),
    include_record=True,
    record_tamper=None,
):
    source_root = tmp_path / "source"
    install_root = tmp_path / "install"
    source_root.mkdir()
    install_root.mkdir()
    source_files = _fixture_files()
    resource_files = {RESOURCE: b"account: synthetic\n"}
    package_files = {**source_files, **resource_files}
    license_bytes = b"Synthetic license fixture\n"
    (source_root / "LICENSE").write_bytes(license_bytes)
    for name, contents in package_files.items():
        for root in (source_root, install_root):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)

    wheel = tmp_path / "back_trader_python-1.4.0-py3-none-any.whl"
    archive_files = {
        **source_files,
        **resource_files,
        DIST_INFO
        + "METADATA": b"Metadata-Version: 2.1\nName: back-trader-python\nVersion: 1.4.0\n",
        DIST_INFO + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        DIST_INFO + "LICENSE": license_bytes,
        DIST_INFO + "top_level.txt": b"backtrader\n",
    }
    archive_files.update(wheel_changes or {})
    for name in omit_wheel_members:
        archive_files.pop(name, None)
    record_name = DIST_INFO + "RECORD"
    if include_record:
        if record_tamper:
            archive_files[record_name] = _tamper_record(archive_files, record_name, record_tamper)
        else:
            archive_files[record_name] = _record_contents(archive_files, record_name)
    with zipfile.ZipFile(wheel, "w") as package:
        for name, contents in archive_files.items():
            package.writestr(name, contents)
        for name, contents in duplicate_members:
            package.writestr(name, contents)
    return wheel, source_root, install_root, source_files, resource_files


def _rewrite_zip_member_name(wheel, current_name, malformed_name):
    current = current_name.encode("utf-8")
    malformed = malformed_name.encode("utf-8")
    assert len(current) == len(malformed)
    contents = wheel.read_bytes()
    assert contents.count(current) == 2
    wheel.write_bytes(contents.replace(current, malformed))


def test_current_wheel_layout_compares_all_backtrader_python_sources(tmp_path):
    wheel, source_root, install_root, source_files, resource_files = _write_fixture(tmp_path)

    assert not (source_root / "backtrader_runtime").exists()
    assert VERIFIER.SOURCE_PACKAGES == ("backtrader/",)
    checked, checked_resources, private = VERIFIER._verify_wheel_source_identity(
        wheel, source_root, install_root, VERSION
    )

    assert set(checked) == set(source_files)
    assert checked_resources == {
        name: hashlib.sha256(contents).hexdigest() for name, contents in resource_files.items()
    }
    assert private == {name for name in source_files if name.startswith("backtrader/_cerebro/")}
    with zipfile.ZipFile(wheel) as package:
        assert not any(name.startswith("backtrader_runtime/") for name in package.namelist())


def test_rejects_removed_runtime_package_in_wheel(tmp_path):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {"backtrader_runtime/legacy.py": b"LEGACY = True\n"},
    )

    with pytest.raises(AssertionError, match="Non-library files in wheel"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


@pytest.mark.parametrize(
    "member_name",
    [
        "../backtrader/escape.py",
        "backtrader//escape.py",
        "backtrader/./escape.py",
        "/backtrader/escape.py",
        "C:/backtrader/escape.py",
    ],
)
def test_rejects_noncanonical_member_paths_before_reading(tmp_path, member_name):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {member_name: b"ESCAPE = True\n"},
    )
    if "\\" in member_name:
        _rewrite_zip_member_name(wheel, member_name.replace("\\", "/"), member_name)

    with pytest.raises(AssertionError, match="(Noncanonical|Absolute) ZIP member path"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


def test_rejects_duplicate_archive_members_before_reading(tmp_path):
    with pytest.warns(UserWarning, match="Duplicate name"):
        wheel, source_root, install_root, _, _ = _write_fixture(
            tmp_path,
            duplicate_members=[("backtrader/cerebro.py", b"class OtherCerebro: pass\n")],
        )

    with pytest.raises(AssertionError, match="Duplicate ZIP member names"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


def test_requires_one_expected_dist_info_directory(tmp_path):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {"legacy-1.4.0.dist-info/METADATA": b"Name: legacy\nVersion: 1.4.0\n"},
    )

    with pytest.raises(AssertionError, match="Expected one .* directory"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


@pytest.mark.parametrize(
    "metadata",
    [
        b"Metadata-Version: 2.1\nName: backtrader\nVersion: 1.4.0\n",
        b"Metadata-Version: 2.1\nName: back-trader-python\nVersion: 9.9.9\n",
    ],
)
def test_checks_metadata_distribution_name_and_version(tmp_path, metadata):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {DIST_INFO + "METADATA": metadata},
    )

    with pytest.raises(AssertionError, match="Unexpected distribution (Name|Version)"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


def test_requires_metadata_wheel_and_record_files(tmp_path):
    wheel, source_root, install_root, _, _ = _write_fixture(tmp_path, include_record=False)

    with pytest.raises(AssertionError, match="missing .*RECORD"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


@pytest.mark.parametrize("field", ["digest", "size"])
def test_checks_record_hashes_and_sizes(tmp_path, field):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        record_tamper=field,
    )

    with pytest.raises(
        AssertionError,
        match=r"Wheel RECORD digest or size mismatch: backtrader/cerebro\.py",
    ):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


def test_rejects_missing_backtrader_source_member(tmp_path):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        omit_wheel_members=("backtrader/cerebro.py",),
    )

    with pytest.raises(AssertionError, match="Wheel package payload mismatch"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


@pytest.mark.parametrize(
    "member_name",
    ["backtrader/hidden.pyc", "backtrader/native.pyd", "backtrader/extra.bin"],
)
def test_rejects_non_python_package_payloads_outside_resource_allowlist(tmp_path, member_name):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {member_name: b"hidden payload\n"},
    )

    with pytest.raises(AssertionError, match="Wheel package payload mismatch"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


def test_rejects_package_resource_mismatch(tmp_path):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {RESOURCE: b"tampered resource\n"},
    )

    with pytest.raises(AssertionError, match=RESOURCE):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)


def test_resource_allowlist_matches_setup_py_package_data():
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / "setup.py").read_text(encoding="utf-8"))
    setup_call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setup"
    )
    package_data = ast.literal_eval(
        next(keyword.value for keyword in setup_call.keywords if keyword.arg == "package_data")
    )
    configured_resources = {
        "{0}/{1}".format(package, name) for package, names in package_data.items() for name in names
    }

    assert set(VERIFIER.PACKAGE_RESOURCES) == configured_resources


def test_archive_audit_precedes_backtrader_import(monkeypatch, tmp_path):
    audit_event = []

    def record_audit(*_args):
        audit_event.append("audit")
        return {}, {}, set()

    class ImportReached(Exception):
        pass

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "backtrader":
            audit_event.append("import")
            raise ImportReached
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(VERIFIER, "_verify_wheel_source_identity", record_audit)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(ImportReached):
        VERIFIER.verify(tmp_path / "wheel.whl", tmp_path, tmp_path, VERSION)
    assert audit_event == ["audit", "import"]


def test_refuses_optimized_python():
    command = "import runpy; runpy.run_path({!r})".format(str(SCRIPT))
    result = subprocess.run(
        [sys.executable, "-O", "-c", command],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Release wheel verification refuses optimized Python" in result.stderr


def test_rejects_backtrader_source_mismatch(tmp_path):
    wheel, source_root, install_root, _, _ = _write_fixture(
        tmp_path,
        {"backtrader/cerebro.py": b"class OtherCerebro: pass\n"},
    )

    with pytest.raises(AssertionError, match="backtrader/cerebro.py"):
        VERIFIER._verify_wheel_source_identity(wheel, source_root, install_root, VERSION)
