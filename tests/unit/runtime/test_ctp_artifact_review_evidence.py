"""Offline tests for non-authorizing CTP release review evidence."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest

from scripts import ctp_artifact_review_evidence as evidence


_FRONTS = {
    "set1_group1": ("tcp://180.168.146.187:10201", "tcp://180.168.146.187:10211"),
    "set1_group2": ("tcp://180.168.146.187:10202", "tcp://180.168.146.187:10212"),
    "set2_7x24": ("tcp://180.168.146.187:10130", "tcp://180.168.146.187:10131"),
}


def _record_digest(contents: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode("ascii")
    return "sha256=" + digest.rstrip("=")


def _record_bytes(files: Dict[str, bytes], record_path: str) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    for name in sorted(files):
        contents = files[name]
        writer.writerow((name, _record_digest(contents), str(len(contents))))
    writer.writerow((record_path, "", ""))
    return stream.getvalue().encode("utf-8")


def _wheel(
    tmp_path: Path,
    distribution: str,
    version: str,
    module: str,
    selector: bytes = b"",
    requires_dist: Tuple[str, ...] = (),
    additional_files: Optional[Dict[str, bytes]] = None,
    wheel_tag: str = "py3-none-any",
) -> Path:
    dist_info = "{}-{}.dist-info".format(distribution, version)
    files = {
        "{}/__init__.py".format(module): b"\"\"\"Candidate test package.\"\"\"\n",
        "{}/METADATA".format(dist_info): (
            "Metadata-Version: 2.1\nName: {}\nVersion: {}\nRequires-Python: >=3.9\n{}\n".format(
                distribution,
                version,
                "".join("Requires-Dist: {}\n".format(item) for item in requires_dist),
            ).encode("utf-8")
        ),
        "{}/WHEEL".format(dist_info): b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    if module == "bt_api_ctp":
        if not selector:
            pairs = ",\n".join(
                "    {!r}: {!r}".format(name, pair) for name, pair in _FRONTS.items()
            )
            selector = (
                "from types import MappingProxyType\n"
                "_SIMNOW_PROFILE_FRONTS = MappingProxyType({\n"
                + pairs
                + "\n})\n"
            ).encode("utf-8")
        files["bt_api_ctp/ctp_env_selector.py"] = selector
    if additional_files:
        files.update(additional_files)
    record_path = "{}/RECORD".format(dist_info)
    record = _record_bytes(files, record_path)
    if wheel_tag != "py3-none-any":
        files["{}/WHEEL".format(dist_info)] = (
            "Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {}\n".format(wheel_tag)
        ).encode("ascii")
        record = _record_bytes(files, record_path)
    wheel_path = tmp_path / "{}-{}-{}.whl".format(distribution, version, wheel_tag)
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in sorted(files.items()):
            archive.writestr(name, contents)
        archive.writestr(record_path, record)
    return wheel_path


def _minimal_amd64_pe() -> bytes:
    pe_offset = 0x80
    optional_header_size = 0xF0
    image = bytearray(pe_offset + 24 + optional_header_size + 40)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, pe_offset)
    image[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into(
        "<HHIIIHH",
        image,
        pe_offset + 4,
        0x8664,  # IMAGE_FILE_MACHINE_AMD64
        1,  # one section
        0,
        0,
        0,
        optional_header_size,
        0x2022,
    )
    struct.pack_into("<H", image, pe_offset + 24, 0x20B)  # PE32+
    return bytes(image)


def _selector(fronts) -> bytes:
    pairs = ",\n".join("    {!r}: {!r}".format(name, pair) for name, pair in fronts.items())
    return (
        "from types import MappingProxyType\n"
        "_SIMNOW_PROFILE_FRONTS = MappingProxyType({\n"
        + pairs
        + "\n})\n"
    ).encode("utf-8")


def _install_wheel(wheel_path: Path, site_root: Path) -> None:
    site_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel_path) as archive:
        archive.extractall(site_root)
        record_path = next(
            item for item in archive.namelist() if item.endswith(".dist-info/RECORD")
        )
    dist_info = site_root / record_path.rsplit("/", 1)[0]
    direct_url = {
        "url": wheel_path.resolve().as_uri(),
        "archive_info": {"hashes": {"sha256": hashlib.sha256(wheel_path.read_bytes()).hexdigest()}},
    }
    direct_url_bytes = (json.dumps(direct_url, sort_keys=True) + "\n").encode("utf-8")
    (dist_info / "direct_url.json").write_bytes(direct_url_bytes)
    old_record = (dist_info / "RECORD").read_bytes()
    rows = list(csv.reader(io.StringIO(old_record.decode("utf-8"), newline="")))
    rows.append(
        (
            (dist_info / "direct_url.json").relative_to(site_root).as_posix(),
            _record_digest(direct_url_bytes),
            str(len(direct_url_bytes)),
        )
    )
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(rows)
    (dist_info / "RECORD").write_text(stream.getvalue(), encoding="utf-8", newline="")


def _source_snapshot(
    dirty: bool,
    selector_hash: str,
    wheel_data: Tuple[Dict[str, object], ...],
) -> Dict[str, object]:
    git = {"available": True, "head": "abc123", "dirty": dirty, "change_count": int(dirty)}
    wheel_maps = {
        str(item["module"]): item["_python_source_map"] for item in wheel_data
    }
    package_projects = {}
    for name, version in (("bt_api_base", "0.15.4"), ("bt_api_ctp", "2.0.3")):
        source_map = wheel_maps.get(name, {})
        package_projects[name] = {
            "git": git,
            "project": {
                "available": True,
                "name": name,
                "version": version,
                "requires_python": ">=3.9",
            },
            "python_source_map": source_map,
            "python_source_snapshot_sha256": evidence._source_snapshot_digest(source_map),
            "python_source_file_count": len(source_map),
        }
    return {
        "sdk_root": "candidate-source",
        "sdk_repository": git,
        "packages": package_projects,
        "ctp_selector_sha256": selector_hash,
        "ctp_selector_fronts": {name: list(pair) for name, pair in _FRONTS.items()},
    }


def _make_sdk_root(tmp_path: Path) -> Path:
    ctp = tmp_path / "sdk" / "bt_api" / "bt_api_ctp" / "src" / "bt_api_ctp"
    base = tmp_path / "sdk" / "bt_api" / "bt_api_base"
    ctp.mkdir(parents=True)
    base.mkdir(parents=True)
    (ctp / "ctp_env_selector.py").write_text("_SIMNOW_PROFILE_FRONTS = {}\n", encoding="utf-8")
    (ctp.parents[1] / "pyproject.toml").write_text("[project]\nname='bt_api_ctp'\n", encoding="utf-8")
    (base / "pyproject.toml").write_text("[project]\nname='bt_api_base'\n", encoding="utf-8")
    return tmp_path / "sdk"


def test_wheel_review_evidence_extracts_exact_package_and_profile_material(tmp_path):
    ctp = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        requires_dist=("bt_api_base>=0.15.4,<1.0",),
    )

    found = evidence._read_wheel(ctp)

    assert found["distribution"] == "bt_api_ctp"
    assert found["version"] == "2.0.3"
    assert found["wheel_sha256"] == hashlib.sha256(ctp.read_bytes()).hexdigest()
    assert len(found["wheel_record_sha256"]) == 64
    assert found["requires_dist"] == ["bt_api_base>=0.15.4,<1.0"]
    assert found["member_scan"]["private_or_secret_member_count"] == 0
    assert found["selector_fronts"] == {
        name: list(pair) for name, pair in _FRONTS.items()
    }
    assert found["native_extension_integrity"] == "not_required"


def test_ctp_cp311_windows_wheel_accepts_one_plausible_amd64_extension(tmp_path):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        wheel_tag="cp311-cp311-win_amd64",
        additional_files={
            "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": _minimal_amd64_pe()
        },
    )

    result = evidence._read_wheel(wheel)

    assert result["native_extension_integrity"] == "verified"


@pytest.mark.parametrize("contents", (b"", b"not a PE image", b"MZ" + b"\0" * 80))
def test_ctp_cp311_windows_wheel_rejects_empty_or_invalid_pe_extension(tmp_path, contents):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        wheel_tag="cp311-cp311-win_amd64",
        additional_files={"bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": contents},
    )

    with pytest.raises(evidence.EvidenceError, match="invalid AMD64 PE header") as raised:
        evidence._read_wheel(wheel)

    assert raised.value.status == "rejected"
    assert raised.value.reason_code == "ctp_windows_native_extension_invalid_pe"


def test_ctp_cp311_windows_wheel_requires_expected_native_extension_exactly_once(tmp_path):
    missing = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        wheel_tag="cp311-cp311-win_amd64",
    )
    duplicate = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.4",
        "bt_api_ctp",
        wheel_tag="cp311-cp311-win_amd64",
        additional_files={
            "bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": _minimal_amd64_pe(),
            "bt_api_ctp/ctp/other.pyd": _minimal_amd64_pe(),
        },
    )

    with pytest.raises(evidence.EvidenceError, match="exactly one expected native extension") as absent:
        evidence._read_wheel(missing)
    with pytest.raises(evidence.EvidenceError, match="exactly one expected native extension") as ambiguous:
        evidence._read_wheel(duplicate)

    assert absent.value.reason_code == "ctp_windows_native_extension_missing_or_ambiguous"
    assert ambiguous.value.reason_code == "ctp_windows_native_extension_missing_or_ambiguous"


def test_cli_reports_stable_rejection_status_and_reason_for_empty_pe(tmp_path, capsys):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        wheel_tag="cp311-cp311-win_amd64",
        additional_files={"bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd": b""},
    )

    result = evidence.main(
        ["--sdk-root", str(_make_sdk_root(tmp_path)), "--wheel", str(wheel)]
    )

    assert result == 2
    assert (
        "status=rejected reason=ctp_windows_native_extension_invalid_pe"
        in capsys.readouterr().err
    )


def test_evidence_output_is_deterministic_for_identical_inputs(tmp_path, monkeypatch):
    ctp_wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    wheel_info = evidence._read_wheel(ctp_wheel)
    selector_hash = wheel_info["selector_sha256"]
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(False, selector_hash, (wheel_info,)),
    )
    sdk_root = _make_sdk_root(tmp_path)
    repo_root = Path(__file__).resolve().parents[3]

    first = evidence.generate_evidence(sdk_root, [ctp_wheel], repo_root=repo_root)
    second = evidence.generate_evidence(sdk_root, [ctp_wheel], repo_root=repo_root)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_dirty_sdk_source_refuses_copy_ready_pins_but_keeps_observed_evidence(
    tmp_path, monkeypatch
):
    base_wheel = _wheel(tmp_path, "bt_api_base", "0.15.4", "bt_api_base")
    ctp_wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        requires_dist=("bt_api_base>=0.15.4,<1.0",),
    )
    installed = tmp_path / "site"
    _install_wheel(base_wheel, installed)
    _install_wheel(ctp_wheel, installed)
    wheel_data = (
        evidence._read_wheel(base_wheel),
        evidence._read_wheel(ctp_wheel),
    )
    selector_hash = wheel_data[1]["selector_sha256"]
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(True, selector_hash, wheel_data),
    )

    result = evidence.generate_evidence(
        _make_sdk_root(tmp_path),
        [base_wheel, ctp_wheel],
        installed,
        repo_root=Path(__file__).resolve().parents[3],
    )

    assert result["pin_material_status"] == "refused_dirty_source"
    assert result["candidate_pin_material"] == {}
    assert result["catalog_approval"] == "none"
    assert result["independent_release_review_required"] is True
    assert set(result["observed_artifact_identities"]) == {"bt_api_base", "bt_api_ctp"}
    assert all(
        len(item["installed_record_sha256"]) == 64
        for item in result["observed_artifact_identities"].values()
    )
    assert set(result["candidate_runtime_profile_matches"]) == set(_FRONTS)


def test_clean_pair_emits_candidate_pin_fields_for_review_only(tmp_path, monkeypatch):
    base_wheel = _wheel(tmp_path, "bt_api_base", "0.15.4", "bt_api_base")
    ctp_wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    installed = tmp_path / "site"
    _install_wheel(base_wheel, installed)
    _install_wheel(ctp_wheel, installed)
    wheel_data = (
        evidence._read_wheel(base_wheel),
        evidence._read_wheel(ctp_wheel),
    )
    selector_hash = wheel_data[1]["selector_sha256"]
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(False, selector_hash, wheel_data),
    )

    result = evidence.generate_evidence(
        _make_sdk_root(tmp_path),
        [base_wheel, ctp_wheel],
        installed,
        repo_root=Path(__file__).resolve().parents[3],
    )

    assert result["pin_material_status"] == "ready_for_independent_review_only"
    assert result["catalog_approval"] == "none"
    assert result["candidate_runtime_profile_table_matches"] is True
    assert set(result["candidate_pin_material"]) == {"bt_api_base", "bt_api_ctp"}
    assert result["candidate_pin_material"]["bt_api_ctp"]["wheel_filename"] == ctp_wheel.name


def test_extra_candidate_front_profile_prevents_copy_ready_pin_material(
    tmp_path, monkeypatch
):
    candidate_fronts = dict(_FRONTS)
    candidate_fronts["unreviewed_profile"] = (
        "tcp://192.0.2.1:10001",
        "tcp://192.0.2.1:10002",
    )
    base_wheel = _wheel(tmp_path, "bt_api_base", "0.15.4", "bt_api_base")
    ctp_wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        selector=_selector(candidate_fronts),
    )
    installed = tmp_path / "site"
    _install_wheel(base_wheel, installed)
    _install_wheel(ctp_wheel, installed)
    wheel_data = (evidence._read_wheel(base_wheel), evidence._read_wheel(ctp_wheel))
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(
            False, wheel_data[1]["selector_sha256"], wheel_data
        ),
    )

    result = evidence.generate_evidence(
        _make_sdk_root(tmp_path),
        [base_wheel, ctp_wheel],
        installed,
        repo_root=Path(__file__).resolve().parents[3],
    )

    assert result["source_artifact_matches"] is True
    assert result["candidate_runtime_profile_table_matches"] is False
    assert result["candidate_extra_profiles"] == ["unreviewed_profile"]
    assert result["pin_material_status"] == "refused_runtime_profile_table_mismatch"
    assert result["candidate_pin_material"] == {}


def test_explicit_front_mode_bypasses_only_legacy_table_compatibility(
    tmp_path, monkeypatch
):
    candidate_fronts = dict(_FRONTS)
    candidate_fronts["legacy_extra_profile"] = (
        "tcp://192.0.2.1:10001",
        "tcp://192.0.2.1:10002",
    )
    base_wheel = _wheel(tmp_path, "bt_api_base", "0.15.4", "bt_api_base")
    ctp_wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        selector=_selector(candidate_fronts),
    )
    installed = tmp_path / "site"
    _install_wheel(base_wheel, installed)
    _install_wheel(ctp_wheel, installed)
    wheel_data = (evidence._read_wheel(base_wheel), evidence._read_wheel(ctp_wheel))
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(
            False, wheel_data[1]["selector_sha256"], wheel_data
        ),
    )

    result = evidence.generate_evidence(
        _make_sdk_root(tmp_path),
        [base_wheel, ctp_wheel],
        installed,
        repo_root=Path(__file__).resolve().parents[3],
        front_binding_mode="explicit_front_pair",
    )

    assert result["source_artifact_matches"] is True
    assert result["candidate_runtime_profile_table_matches"] is False
    assert result["runtime_profile_table_gate_applies"] is False
    assert result["runtime_profile_table_gate_satisfied"] is True
    assert result["explicit_front_verifier_available"] is True
    assert result["front_binding_mode"] == "explicit_front_pair"
    assert result["pin_material_scope"] == "explicit_config_front_pair_artifact_only"
    assert result["pin_material_status"] == "ready_for_independent_review_only"
    assert set(result["candidate_pin_material"]) == {"bt_api_base", "bt_api_ctp"}
    assert result["catalog_approval"] == "none"


def test_explicit_front_mode_requires_runtime_selected_front_verifier(
    tmp_path, monkeypatch
):
    base_wheel = _wheel(tmp_path, "bt_api_base", "0.15.4", "bt_api_base")
    ctp_wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    installed = tmp_path / "site"
    _install_wheel(base_wheel, installed)
    _install_wheel(ctp_wheel, installed)
    wheel_data = (evidence._read_wheel(base_wheel), evidence._read_wheel(ctp_wheel))
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(
            False, wheel_data[1]["selector_sha256"], wheel_data
        ),
    )
    monkeypatch.setattr(evidence, "_has_explicit_front_verifier", lambda _source: False)

    result = evidence.generate_evidence(
        _make_sdk_root(tmp_path),
        [base_wheel, ctp_wheel],
        installed,
        repo_root=Path(__file__).resolve().parents[3],
        front_binding_mode="explicit_front_pair",
    )

    assert result["pin_material_status"] == "refused_explicit_front_verifier_unavailable"
    assert result["candidate_pin_material"] == {}


def test_explicit_front_mode_still_refuses_dirty_sdk_source(tmp_path, monkeypatch):
    base_wheel = _wheel(tmp_path, "bt_api_base", "0.15.4", "bt_api_base")
    ctp_wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    installed = tmp_path / "site"
    _install_wheel(base_wheel, installed)
    _install_wheel(ctp_wheel, installed)
    wheel_data = (evidence._read_wheel(base_wheel), evidence._read_wheel(ctp_wheel))
    monkeypatch.setattr(
        evidence,
        "_source_evidence",
        lambda _root: _source_snapshot(
            True, wheel_data[1]["selector_sha256"], wheel_data
        ),
    )

    result = evidence.generate_evidence(
        _make_sdk_root(tmp_path),
        [base_wheel, ctp_wheel],
        installed,
        repo_root=Path(__file__).resolve().parents[3],
        front_binding_mode="explicit_front_pair",
    )

    assert result["pin_material_status"] == "refused_dirty_source"
    assert result["candidate_pin_material"] == {}


def test_front_binding_mode_cli_defaults_to_legacy_and_accepts_explicit_pair():
    legacy = evidence._parse_args(["--sdk-root", "."])
    explicit = evidence._parse_args(
        ["--sdk-root", ".", "--front-binding-mode", "explicit_front_pair"]
    )

    assert legacy.front_binding_mode == "legacy_profile"
    assert explicit.front_binding_mode == "explicit_front_pair"


def test_installed_record_rejects_a_changed_candidate_file(tmp_path):
    wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    site = tmp_path / "site"
    _install_wheel(wheel, site)
    (site / "bt_api_ctp" / "__init__.py").write_bytes(b"changed\n")
    wheel_evidence = evidence._read_wheel(wheel)

    with pytest.raises(evidence.EvidenceError, match="RECORD"):
        evidence._read_installed_record(site, wheel_evidence)


def test_wheel_record_rejects_changed_archive_file(tmp_path):
    wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    changed_dir = tmp_path / "changed"
    changed_dir.mkdir()
    changed = changed_dir / wheel.name
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(changed, "w") as target:
        for item in source.infolist():
            contents = source.read(item.filename)
            if item.filename == "bt_api_ctp/__init__.py":
                contents = b"x" * len(contents)
            target.writestr(item, contents)

    with pytest.raises(evidence.EvidenceError, match="RECORD digest"):
        evidence._read_wheel(changed)


def test_wheel_filename_must_match_distribution_and_version(tmp_path):
    wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    renamed = tmp_path / "bt_api_ctp-2.0.4-py3-none-any.whl"
    wheel.rename(renamed)

    with pytest.raises(evidence.EvidenceError, match="filename does not match"):
        evidence._read_wheel(renamed)


def test_wheel_member_scan_rejects_private_data_names_without_reading_them(tmp_path):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        additional_files={"bt_api_ctp/secrets.yaml": b"never emitted"},
    )

    with pytest.raises(evidence.EvidenceError, match="private-data pattern"):
        evidence._read_wheel(wheel)


@pytest.mark.parametrize(
    "member_name",
    (
        "bt_api_ctp/.env.production",
        "bt_api_ctp/private/token.txt",
        "bt_api_ctp/.ssh/id_ed25519",
        "bt_api_ctp/certs/client.p12",
        "bt_api_ctp/configs/credentials.ini",
    ),
)
def test_wheel_member_scan_rejects_private_names(tmp_path, member_name):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        additional_files={member_name: b"never emitted"},
    )

    with pytest.raises(evidence.EvidenceError, match="private-data pattern"):
        evidence._read_wheel(wheel)


def test_wheel_member_scan_rejects_unexpected_configuration_files(tmp_path):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        additional_files={"bt_api_ctp/config.yaml": b"never emitted"},
    )

    with pytest.raises(evidence.EvidenceError, match="unexpected configuration"):
        evidence._read_wheel(wheel)


def test_wheel_member_scan_reports_the_expected_public_config_name_only(tmp_path):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        additional_files={"bt_api_ctp/configs/ctp.yaml": b"contents stay unreported"},
    )

    result = evidence._read_wheel(wheel)

    assert result["member_scan"]["public_configuration_members"] == [
        "bt_api_ctp/configs/ctp.yaml"
    ]
    public_result = {key: value for key, value in result.items() if not key.startswith("_")}
    assert "contents stay unreported" not in json.dumps(public_result)


def test_wheel_member_scan_rejects_traversal_paths(tmp_path):
    wheel = _wheel(
        tmp_path,
        "bt_api_ctp",
        "2.0.3",
        "bt_api_ctp",
        additional_files={"bt_api_ctp/../outside.py": b"not emitted"},
    )

    with pytest.raises(evidence.EvidenceError, match="invalid path"):
        evidence._read_wheel(wheel)


def test_wheel_member_scan_rejects_symlinks(tmp_path):
    wheel = _wheel(tmp_path, "bt_api_ctp", "2.0.3", "bt_api_ctp")
    linked = tmp_path / "symlink-wheel.whl"
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(linked, "w") as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        link_info = zipfile.ZipInfo("bt_api_ctp/private-data.txt")
        link_info.create_system = 3
        link_info.external_attr = 0o120777 << 16
        target.writestr(link_info, b"../outside")

    with pytest.raises(evidence.EvidenceError, match="non-regular file"):
        evidence._read_wheel(linked)
