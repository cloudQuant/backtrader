"""Verify a release wheel's source identity and isolated consumer behavior.

Run with the wheel installed in a dedicated --install-root, from outside the
source checkout, with PYTHONPATH pointing only to that installation root.
"""

import argparse
import base64
import csv
import hashlib
import importlib
import io
import json
import pathlib
import re
import stat
import zipfile
from email.parser import BytesParser

if not __debug__:
    raise RuntimeError("Release wheel verification refuses optimized Python (-O/-OO)")

SOURCE_PACKAGES = ("backtrader/",)
PACKAGE_RESOURCES = ("backtrader/configs/account_config_example.yaml",)
DISTRIBUTION_NAME = "back-trader-python"
DIST_INFO_REQUIRED_FILES = frozenset(("METADATA", "RECORD", "WHEEL"))
DIST_INFO_OPTIONAL_FILES = frozenset(("LICENSE", "top_level.txt"))


def _dist_info_prefix(expected_version):
    """Return the wheel metadata directory for the configured distribution."""
    wheel_name = DISTRIBUTION_NAME.replace("-", "_").replace(".", "_")
    return f"{wheel_name}-{expected_version}.dist-info/"


def _validate_archive_members(members):
    """Reject ambiguous or unsafe names before reading any wheel member."""
    names = [member.filename for member in members]
    assert len(names) == len(set(names)), "Duplicate ZIP member names"

    canonical_paths = set()
    files = set()
    for member in members:
        name = member.orig_filename
        assert name == member.filename, f"Noncanonical ZIP member path: {name!r}"
        assert name and "\\" not in name, f"Noncanonical ZIP member path: {name!r}"
        assert not name.startswith("/"), f"Absolute ZIP member path: {name!r}"
        assert not any(ord(char) < 32 or ord(char) == 127 for char in name), (
            f"Control character in ZIP member path: {name!r}"
        )

        is_directory = member.is_dir()
        member_type = stat.S_IFMT(member.external_attr >> 16)
        accepted_types = (0, stat.S_IFDIR) if is_directory else (0, stat.S_IFREG)
        assert member_type in accepted_types, f"Unsupported ZIP member type: {name!r}"
        path = name[:-1] if is_directory else name
        parts = path.split("/")
        assert path and all(part not in ("", ".", "..") for part in parts), (
            f"Noncanonical ZIP member path: {name!r}"
        )
        assert all(":" not in part for part in parts), f"Noncanonical ZIP member path: {name!r}"
        canonical_name = "/".join(parts) + ("/" if is_directory else "")
        assert name == canonical_name, f"Noncanonical ZIP member path: {name!r}"
        assert not is_directory or member.file_size == 0, (
            f"Directory ZIP member has content: {name!r}"
        )

        canonical_path = "/".join(parts)
        assert canonical_path not in canonical_paths, (
            f"Conflicting ZIP file/directory paths: {name!r}"
        )
        canonical_paths.add(canonical_path)
        if not is_directory:
            files.add(canonical_path)

    for name in files:
        parts = name.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            assert parent not in files, f"ZIP file is also a parent directory: {parent!r}"
    return names


def _distribution_key(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _verify_dist_info(package, members, expected_root, expected_version, source_root):
    """Validate the distribution metadata files and their RECORD."""
    member_by_name = {member.filename: member for member in members}
    prefix = expected_root + "/"
    dist_info_files = {
        member.filename[len(prefix) :]
        for member in members
        if member.filename.startswith(prefix) and not member.is_dir()
    }
    allowed_files = DIST_INFO_REQUIRED_FILES | DIST_INFO_OPTIONAL_FILES
    assert DIST_INFO_REQUIRED_FILES.issubset(dist_info_files), (
        f"Wheel metadata is missing required files: "
        f"{sorted(DIST_INFO_REQUIRED_FILES - dist_info_files)!r}"
    )
    assert dist_info_files.issubset(allowed_files), (
        f"Unexpected wheel metadata files: {sorted(dist_info_files - allowed_files)!r}"
    )
    metadata_name = expected_root + "/METADATA"
    wheel_name = expected_root + "/WHEEL"
    record_name = expected_root + "/RECORD"
    for required_name in (metadata_name, wheel_name, record_name):
        assert required_name in member_by_name and not member_by_name[required_name].is_dir(), (
            f"Wheel is missing {required_name}"
        )

    metadata = BytesParser().parsebytes(package.read(metadata_name))
    declared_names = metadata.get_all("Name", [])
    declared_versions = metadata.get_all("Version", [])
    assert len(declared_names) == 1 and _distribution_key(declared_names[0]) == _distribution_key(
        DISTRIBUTION_NAME
    ), f"Unexpected distribution Name: {declared_names!r}"
    assert declared_versions == [expected_version], (
        f"Unexpected distribution Version: {declared_versions!r}"
    )

    wheel_metadata = BytesParser().parsebytes(package.read(wheel_name))
    wheel_versions = wheel_metadata.get_all("Wheel-Version", [])
    purelib_values = wheel_metadata.get_all("Root-Is-Purelib", [])
    tags = wheel_metadata.get_all("Tag", [])
    assert len(wheel_versions) == 1 and re.fullmatch(r"\d+\.\d+", wheel_versions[0]), (
        f"Invalid WHEEL Wheel-Version: {wheel_versions!r}"
    )
    assert len(purelib_values) == 1 and purelib_values[0].lower() == "true", (
        f"Expected a pure Python wheel: {purelib_values!r}"
    )
    assert tags and all(tag.strip() for tag in tags), "WHEEL must declare at least one Tag"

    license_name = expected_root + "/LICENSE"
    if license_name in member_by_name:
        license_bytes = package.read(license_name)
        assert license_bytes == (source_root / "LICENSE").read_bytes(), (
            "Wheel LICENSE does not match checkout"
        )
    top_level_name = expected_root + "/top_level.txt"
    if top_level_name in member_by_name:
        assert package.read(top_level_name) == b"backtrader\n", (
            "Wheel top_level.txt does not match the backtrader import package"
        )

    record_data = package.read(record_name)
    try:
        rows = list(csv.reader(io.StringIO(record_data.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise AssertionError("Invalid wheel RECORD CSV") from exc
    assert all(len(row) == 3 and row[0] for row in rows), "Invalid wheel RECORD row"
    record_names = [row[0] for row in rows]
    assert len(record_names) == len(set(record_names)), "Duplicate wheel RECORD rows"

    archive_files = {member.filename for member in members if not member.is_dir()}
    signatures = {expected_root + "/RECORD.jws", expected_root + "/RECORD.p7s"}
    expected_record_names = archive_files - signatures
    assert set(record_names) == expected_record_names, "Wheel RECORD does not match archive files"
    rows_by_name = {row[0]: row[1:] for row in rows}
    for name in sorted(expected_record_names - {record_name}):
        payload = package.read(name)
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode("ascii").rstrip("=")
        )
        assert rows_by_name[name] == ["sha256=" + digest, str(len(payload))], (
            f"Wheel RECORD digest or size mismatch: {name}"
        )
    assert rows_by_name[record_name] == ["", ""], "Wheel RECORD must not hash itself"


def _verify_wheel_source_identity(wheel, source_root, install_root, expected_version):
    """Check the wheel payload and all source/resource identities before imports."""
    source_root = source_root.resolve()
    install_root = install_root.resolve()
    checked = {}
    checked_resources = {}
    with zipfile.ZipFile(wheel) as package:
        members = package.infolist()
        names = _validate_archive_members(members)
        expected_dist_info_root = _dist_info_prefix(expected_version).rstrip("/")
        dist_info_roots = {
            member.filename.split("/", 1)[0]
            for member in members
            if member.filename.split("/", 1)[0].endswith(".dist-info")
        }
        assert dist_info_roots == {expected_dist_info_root}, (
            f"Expected one {expected_dist_info_root!r} directory, found {sorted(dist_info_roots)!r}"
        )
        dist_info_prefix = expected_dist_info_root + "/"
        unexpected = [
            name for name in names if not name.startswith((*SOURCE_PACKAGES, dist_info_prefix))
        ]
        assert not unexpected, f"Non-library files in wheel: {unexpected[:10]}"

        expected_private = {
            p.relative_to(source_root).as_posix()
            for p in (source_root / "backtrader/_cerebro").glob("*.py")
        }
        assert len(expected_private) == 9
        expected_sources = {
            p.relative_to(source_root).as_posix()
            for package_root in SOURCE_PACKAGES
            for p in (source_root / package_root.rstrip("/")).rglob("*.py")
        }
        expected_resources = set(PACKAGE_RESOURCES)
        expected_package_files = expected_sources | expected_resources
        archive_package_files = {
            member.filename
            for member in members
            if member.filename.startswith(SOURCE_PACKAGES) and not member.is_dir()
        }
        assert archive_package_files == expected_package_files, (
            "Wheel package payload mismatch: "
            f"missing={sorted(expected_package_files - archive_package_files)!r}, "
            f"extra={sorted(archive_package_files - expected_package_files)!r}"
        )
        assert not (install_root / "backtrader_runtime").exists(), (
            "Removed backtrader_runtime package is present in install root"
        )
        for name in sorted(expected_sources):
            expected = package.read(name)
            assert (source_root / name).read_bytes() == expected, name
            assert (install_root / name).read_bytes() == expected, name
            checked[name] = hashlib.sha256(expected).hexdigest()
        for name in sorted(expected_resources):
            expected = package.read(name)
            assert (source_root / name).read_bytes() == expected, name
            assert (install_root / name).read_bytes() == expected, name
            checked_resources[name] = hashlib.sha256(expected).hexdigest()

        _verify_dist_info(package, members, expected_dist_info_root, expected_version, source_root)
        assert not any("account_config.yaml" in name for name in names)
        assert not any(pathlib.PurePosixPath(name).name == ".DS_Store" for name in names)
    return checked, checked_resources, expected_private


def verify(wheel, source_root, install_root, expected_version):
    """Check every packaged source and execute deterministic consumer trades."""
    install_root = install_root.resolve()
    checked, checked_resources, expected_private = _verify_wheel_source_identity(
        wheel, source_root, install_root, expected_version
    )

    import backtrader as bt
    import pandas as pd

    assert bt.__version__ == expected_version
    assert bt.__btversion__ == tuple(int(v) for v in expected_version.split("."))
    pathlib.Path(bt.__file__).resolve().relative_to(install_root)

    for source_name in sorted(expected_private | {"backtrader/cerebro.py"}):
        module_name = source_name[:-3].replace("/", ".")
        if module_name.endswith(".__init__"):
            module_name = module_name[:-9]
        module = importlib.import_module(module_name)
        pathlib.Path(module.__file__).resolve().relative_to(install_root)
    assert bt.Cerebro.__module__ == "backtrader.cerebro"
    assert bt.OptReturn.__module__ == "backtrader.cerebro"

    class RoundTrip(bt.Strategy):
        def __init__(self):
            self.fills = []

        def next(self):
            if len(self) == 1:
                self.buy(size=1)
            elif len(self) == 4:
                self.close()

        def notify_order(self, order):
            if order.status == order.Completed:
                self.fills.append(order.executed.price)

    prices = list(range(100, 108))
    frame = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices, "volume": 10},
        index=pd.date_range("2020-01-01", periods=len(prices)),
    )
    runs = []
    for runonce in (True, False):
        engine = bt.Cerebro(stdstats=False, runonce=runonce)
        engine.adddata(bt.feeds.PandasData(dataname=frame.copy()))
        engine.addstrategy(RoundTrip)
        engine.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        strategy = engine.run()[0]
        assert len(strategy) == 8
        assert strategy.fills == [101.0, 104.0], strategy.fills
        assert engine.broker.getvalue() == 10003.0
        assert strategy.analyzers.trades.get_analysis().total.closed == 1
        runs.append({"runonce": runonce, "bars": 8, "fills": strategy.fills, "value": 10003.0})
    return {
        "status": "PASS",
        "version": bt.__version__,
        "module_file": bt.__file__,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "packaged_source_hashes": checked,
        "packaged_resource_hashes": checked_resources,
        "private_modules": sorted(expected_private),
        "runs": runs,
    }


def main():
    """Write the full verification record, failing on any identity mismatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=pathlib.Path)
    parser.add_argument("--source-root", required=True, type=pathlib.Path)
    parser.add_argument("--install-root", required=True, type=pathlib.Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    result = verify(args.wheel, args.source_root, args.install_root, args.version)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"packaged_source_hashes", "packaged_resource_hashes"}
            }
        )
    )


if __name__ == "__main__":
    main()
