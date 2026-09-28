"""Offline tests for the CTP SDK wheel, RECORD, and front-profile gate."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import io
import json
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator, Mapping

import pytest

import backtrader_runtime.ctp_artifact_provenance as provenance


EXPECTED_FRONTS = (
    "tcp://180.168.146.187:10130",
    "tcp://180.168.146.187:10131",
)
EXPECTED_SET1_GROUP1_FRONTS = (
    "tcp://180.168.146.187:10201",
    "tcp://180.168.146.187:10211",
)
EXPECTED_SET1_GROUP2_FRONTS = (
    "tcp://180.168.146.187:10202",
    "tcp://180.168.146.187:10212",
)


def _sha256_record_value(contents: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode("ascii")
    return "sha256=" + encoded.rstrip("=")


def _write_record(
    site_root: Path,
    rows: list[tuple[str, str]],
    record_relative: str,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for relative, _filename in rows:
        contents = (site_root / relative).read_bytes()
        writer.writerow((relative, _sha256_record_value(contents), str(len(contents))))
    writer.writerow((record_relative, "", ""))
    data = buffer.getvalue().encode("utf-8")
    (site_root / record_relative).write_bytes(data)
    return data


def _write_distribution(
    site_root: Path,
    distribution: str,
    module: str,
    *,
    version: str,
    wheel_sha256: str,
    module_files: Mapping[str, str],
    editable: bool = False,
    source_install: bool = False,
) -> provenance.CtpSdkArtifactPin:
    package_root = site_root / module
    package_root.mkdir(parents=True)
    for relative, content in module_files.items():
        target = package_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    dist_info = site_root / (distribution + "-" + version + ".dist-info")
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: {0}\nVersion: {1}\n\n".format(distribution, version),
        encoding="utf-8",
    )
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        encoding="utf-8",
    )
    filename = "{0}-{1}-py3-none-any.whl".format(distribution, version)
    source_url = "file:///reviewed-wheelhouse/" + filename
    direct_url = {"url": source_url}
    if editable:
        direct_url["dir_info"] = {"editable": True}
    elif source_install:
        direct_url["dir_info"] = {"editable": False}
    else:
        direct_url["archive_info"] = {
            "hash": "sha256=" + wheel_sha256,
            "hashes": {"sha256": wheel_sha256},
        }
    (dist_info / "direct_url.json").write_text(
        json.dumps(direct_url, sort_keys=True), encoding="utf-8"
    )
    (dist_info / "RECORD").write_text("", encoding="utf-8")

    paths = [
        str(path.relative_to(site_root)).replace("\\", "/")
        for path in package_root.rglob("*")
        if path.is_file()
    ]
    paths.extend(
        str(path.relative_to(site_root)).replace("\\", "/")
        for path in dist_info.iterdir()
        if path.name != "RECORD"
    )
    rows = [(relative, relative) for relative in sorted(paths)]
    record = _write_record(
        site_root,
        rows,
        (dist_info.name + "/RECORD"),
    )
    return provenance.CtpSdkArtifactPin(
        distribution=distribution,
        module=module,
        version=version,
        wheel_filename=filename,
        wheel_sha256=wheel_sha256,
        record_sha256=hashlib.sha256(record).hexdigest(),
    )


def _selector_source(profile: str, fronts: tuple[str, str]) -> str:
    profile_fronts = dict(provenance._ALLOWED_SIMNOW_PROFILE_FRONTS)
    profile_fronts[profile] = fronts
    return (
        "FRONTS = {0!r}\ndef official_simnow_fronts(profile):\n    return FRONTS[profile]\n"
    ).format(profile_fronts)


def _write_sdk_install(
    site_root: Path,
    *,
    ctp_profile: str = "set2_7x24",
    ctp_fronts: tuple[str, str] = EXPECTED_FRONTS,
    ctp_version: str = "2.0.2",
    ctp_wheel_sha256: str = "b" * 64,
    editable_ctp: bool = False,
    source_ctp: bool = False,
    include_parent: bool = False,
) -> dict[str, provenance.CtpSdkArtifactPin]:
    site_root.mkdir(parents=True, exist_ok=True)
    base_pin = _write_distribution(
        site_root,
        "bt_api_base",
        "bt_api_base",
        version="0.15.4",
        wheel_sha256="a" * 64,
        module_files={"__init__.py": "BASE = True\n"},
    )
    ctp_pin = _write_distribution(
        site_root,
        "bt_api_ctp",
        "bt_api_ctp",
        version=ctp_version,
        wheel_sha256=ctp_wheel_sha256,
        editable=editable_ctp,
        source_install=source_ctp,
        module_files={
            "__init__.py": "\n",
            "ctp_env_selector.py": _selector_source(ctp_profile, ctp_fronts),
        },
    )
    pins = {"bt_api_base": base_pin, "bt_api_ctp": ctp_pin}
    if include_parent:
        pins["bt_api_py"] = _write_distribution(
            site_root,
            "bt_api_py",
            "bt_api_py",
            version="0.15.4",
            wheel_sha256="c" * 64,
            module_files={
                "__init__.py": "from ._ctp_execution_authorization import CtpExecutionApprovalContext\n",
                "_ctp_credential_binding.py": "class CtpCredentialBindingVerifier: pass\n",
                "_ctp_execution_authorization.py": "class CtpExecutionApprovalContext: pass\n",
            },
        )
    return pins


@contextmanager
def _installed_test_sdk(
    monkeypatch: pytest.MonkeyPatch,
    site_root: Path,
    *,
    ctp_profile: str = "set2_7x24",
    ctp_fronts: tuple[str, str] = EXPECTED_FRONTS,
    ctp_version: str = "2.0.2",
    ctp_wheel_sha256: str = "b" * 64,
    editable_ctp: bool = False,
    include_parent: bool = False,
) -> Iterator[dict[str, provenance.CtpSdkArtifactPin]]:
    pins = _write_sdk_install(
        site_root,
        ctp_profile=ctp_profile,
        ctp_fronts=ctp_fronts,
        ctp_version=ctp_version,
        ctp_wheel_sha256=ctp_wheel_sha256,
        editable_ctp=editable_ctp,
        include_parent=include_parent,
    )
    monkeypatch.setattr(
        provenance.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_root), "platlib": str(site_root)},
    )
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", pins)
    monkeypatch.syspath_prepend(str(site_root))
    importlib.invalidate_caches()

    cached = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name in ("bt_api_base", "bt_api_ctp", "bt_api_py")
        or name.startswith(("bt_api_base.", "bt_api_ctp.", "bt_api_py."))
    }
    for name in cached:
        sys.modules.pop(name, None)
    try:
        yield pins
    finally:
        for name in tuple(sys.modules):
            if name in ("bt_api_base", "bt_api_ctp", "bt_api_py") or name.startswith(
                ("bt_api_base.", "bt_api_ctp.", "bt_api_py.")
            ):
                sys.modules.pop(name, None)
        sys.modules.update(cached)


def test_no_code_owned_pin_fails_closed_without_importing_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})
    sdk_modules_before = {
        name: module
        for name, module in sys.modules.items()
        if name in ("bt_api_base", "bt_api_ctp") or name.startswith(("bt_api_base.", "bt_api_ctp."))
    }

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")

    assert caught.value.reason == "artifact_pin_unavailable"
    assert all(sys.modules.get(name) is module for name, module in sdk_modules_before.items())
    assert not any(
        name == root or name.startswith(root + ".")
        for root in ("bt_api_base", "bt_api_ctp")
        for name in sys.modules.keys() - sdk_modules_before.keys()
    )


def test_pinned_test_artifacts_validate_record_and_exact_official_fronts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _installed_test_sdk(monkeypatch, tmp_path / "site-packages"):
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")


def test_explicit_front_verifier_accepts_pinned_artifact_without_profile_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_pair = ("tcp://td.custom.example:15001", "tcp://md.custom.example:15002")
    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_profile="custom_unlisted",
        ctp_fronts=configured_pair,
    ):
        monkeypatch.setattr(
            provenance.importlib,
            "import_module",
            lambda *_args, **_kwargs: pytest.fail(
                "explicit-front verifier must not load a selector"
            ),
        )

        provenance.verify_ctp_sdk_artifact_provenance_for_fronts(
            td_front=configured_pair[0],
            md_front=configured_pair[1],
        )


def test_i3_oneshot_verifier_has_independent_pin_without_changing_i2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    i2_pins = provenance.CTP_SDK_ARTIFACT_PINS
    i2_ctp_pin = i2_pins["bt_api_ctp"]
    i3_pin = provenance.CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_ctp"]
    assert i3_pin.version == "2.0.3+iteration41.i3"
    assert i3_pin.wheel_filename == ("bt_api_ctp-2.0.3+iteration41.i3-cp311-cp311-win_amd64.whl")
    assert i3_pin.wheel_sha256 == (
        "c1ead607c9b6758b7850b8517996cc1654514cdd8fa81ef10fbf2858e1d914d8"
    )
    assert i3_pin.record_sha256 == (
        "df7644d667a1adeff151c98e58f788e2637cf77473b7cf37f6928cfffda17cb8"
    )
    assert (
        provenance.CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_base"]
        is (provenance.CTP_SDK_ARTIFACT_PINS["bt_api_base"])
    )
    assert i2_pins["bt_api_ctp"] is i2_ctp_pin

    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_version="2.0.3+iteration41.i3",
        ctp_wheel_sha256="b" * 64,
    ) as installed_pins:
        monkeypatch.setattr(provenance, "CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", installed_pins)
        monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})
        provenance.verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )


def test_i3_oneshot_verifier_checks_front_syntax_before_artifact_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="udp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_i4_oneshot_verifier_has_independent_pin_without_changing_i2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    i2_pins = provenance.CTP_SDK_ARTIFACT_PINS
    i2_ctp_pin = i2_pins["bt_api_ctp"]
    i2_base_pin = i2_pins["bt_api_base"]
    i4_base_pin = provenance.CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_base"]
    i4_pin = provenance.CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS["bt_api_ctp"]
    assert i4_base_pin.distribution == i2_base_pin.distribution == "bt_api_base"
    assert i4_base_pin.module == i2_base_pin.module == "bt_api_base"
    assert i4_base_pin.version == i2_base_pin.version == "0.15.5"
    assert i4_base_pin.wheel_filename == i2_base_pin.wheel_filename
    assert i4_base_pin.wheel_sha256 == i2_base_pin.wheel_sha256
    assert i4_base_pin.record_sha256 == (
        "aa91bfa982d473eb2b8ce59192196f87a84e7c9c19aafd8e961c73e5ea87ce90"
    )
    assert i2_base_pin.record_sha256 == (
        "47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762"
    )
    assert i4_base_pin is not i2_base_pin
    assert i4_pin.version == "2.0.3+iteration41.i4"
    assert i4_pin.wheel_filename == ("bt_api_ctp-2.0.3+iteration41.i4-cp311-cp311-win_amd64.whl")
    assert i4_pin.wheel_sha256 == (
        "96f8c874871b6f571e3abb14bf25b32a4ccb133ca09e51767584e5c03682283e"
    )
    assert i4_pin.record_sha256 == (
        "327998c95de9c3a69ac9cb40444361822c8602e30975067705a750c782ffbd6f"
    )
    assert i2_pins["bt_api_ctp"] is i2_ctp_pin

    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_version="2.0.3+iteration41.i4",
        ctp_wheel_sha256="c" * 64,
    ) as installed_pins:
        monkeypatch.setattr(provenance, "CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", installed_pins)
        monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})
        provenance.verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )


def test_i4_oneshot_verifier_checks_front_syntax_before_artifact_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="udp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_i5_oneshot_verifier_has_independent_pin_without_changing_i2_or_i4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    i2_pins = provenance.CTP_SDK_ARTIFACT_PINS
    i4_pins = provenance.CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i5_pins = provenance.CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i5_pin = i5_pins["bt_api_ctp"]
    assert i5_pins["bt_api_base"] is i4_pins["bt_api_base"]
    assert i5_pin.version == "2.0.3+iteration41.i5"
    assert i5_pin.wheel_filename == (
        "bt_api_ctp-2.0.3+iteration41.i5-cp311-cp311-win_amd64.whl"
    )
    assert i5_pin.wheel_sha256 == (
        "552dc8711523aef930864b7441a2a93ed2f4cb9541acc15435ac8fe9a3ca98dc"
    )
    assert i5_pin.record_sha256 == (
        "3320042e1b0d4706cda2c9272806c91aa5ef7efe329f85178db45f3ed2b36026"
    )
    assert i2_pins["bt_api_ctp"].version == "2.0.3+iteration41.i2"
    assert i4_pins["bt_api_ctp"].version == "2.0.3+iteration41.i4"

    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_version="2.0.3+iteration41.i5",
        ctp_wheel_sha256="d" * 64,
    ) as installed_pins:
        monkeypatch.setattr(provenance, "CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", installed_pins)
        monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})
        monkeypatch.setattr(provenance, "CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})
        provenance.verify_ctp_i5_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )


def test_i5_oneshot_verifier_checks_front_syntax_before_artifact_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i5_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="udp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_i6_oneshot_verifier_has_independent_pin_without_changing_prior_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    i2_pins = provenance.CTP_SDK_ARTIFACT_PINS
    i4_pins = provenance.CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i5_pins = provenance.CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i6_pins = provenance.CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i6_pin = i6_pins["bt_api_ctp"]
    assert i6_pins["bt_api_base"] is i4_pins["bt_api_base"]
    assert i6_pin.version == "2.0.3+iteration41.i6"
    assert i6_pin.wheel_filename == (
        "bt_api_ctp-2.0.3+iteration41.i6-cp311-cp311-win_amd64.whl"
    )
    assert i6_pin.wheel_sha256 == (
        "3788bf75019eb8fa685b828be9dae66b2f17d41422e770441870a105e02c1ded"
    )
    assert i6_pin.record_sha256 == (
        "e5ab9889853f1d01683c2754156ca4c2875cad2ceafdea05baadf5d2420a9bb6"
    )
    assert i2_pins["bt_api_ctp"].version == "2.0.3+iteration41.i2"
    assert i4_pins["bt_api_ctp"].version == "2.0.3+iteration41.i4"
    assert i5_pins["bt_api_ctp"].version == "2.0.3+iteration41.i5"

    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_version="2.0.3+iteration41.i6",
        ctp_wheel_sha256="e" * 64,
    ) as installed_pins:
        monkeypatch.setattr(provenance, "CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", installed_pins)
        monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})
        monkeypatch.setattr(provenance, "CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})
        monkeypatch.setattr(provenance, "CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})
        provenance.verify_ctp_i6_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )


def test_i6_oneshot_verifier_checks_front_syntax_before_artifact_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i6_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="udp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_i7_oneshot_verifier_checks_installed_origin_against_its_own_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    i2_pins = provenance.CTP_SDK_ARTIFACT_PINS
    i4_pins = provenance.CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i5_pins = provenance.CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i6_pins = provenance.CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i7_pins = provenance.CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i7_pin = i7_pins["bt_api_ctp"]
    assert i7_pins["bt_api_base"] is i6_pins["bt_api_base"]
    assert i7_pins["bt_api_base"].wheel_sha256 == (
        "1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d"
    )
    assert i7_pins["bt_api_base"].record_sha256 == (
        "aa91bfa982d473eb2b8ce59192196f87a84e7c9c19aafd8e961c73e5ea87ce90"
    )
    assert i7_pin.version == "2.0.3+iteration41.i7"
    assert i7_pin.wheel_filename == (
        "bt_api_ctp-2.0.3+iteration41.i7-cp311-cp311-win_amd64.whl"
    )
    assert i7_pin.wheel_sha256 == (
        "22bc34140233785abcad61e7c3bc4dbb85c9d97b171692d5e6b44cf89eda94b4"
    )
    assert i7_pin.record_sha256 == (
        "03b4d23a6a647c4b29c392304e56dcd3be8b776e9c3eef695af0adcfbbdc45b6"
    )
    assert i2_pins["bt_api_ctp"].version == "2.0.3+iteration41.i2"
    assert i4_pins["bt_api_ctp"].version == "2.0.3+iteration41.i4"
    assert i5_pins["bt_api_ctp"].version == "2.0.3+iteration41.i5"
    assert i6_pins["bt_api_ctp"].version == "2.0.3+iteration41.i6"

    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_version="2.0.3+iteration41.i7",
        ctp_wheel_sha256="f" * 64,
    ) as installed_pins:
        monkeypatch.setattr(provenance, "CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", installed_pins)
        monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})
        monkeypatch.setattr(provenance, "CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})
        monkeypatch.setattr(provenance, "CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})
        monkeypatch.setattr(provenance, "CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})
        provenance.verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )


def test_i7_oneshot_verifier_checks_front_syntax_before_artifact_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts(
            td_front="udp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_explicit_front_verifier_requires_pins_even_for_syntactically_valid_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "artifact_pin_unavailable"


def test_managed_explicit_front_verifier_requires_parent_pin_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _installed_test_sdk(monkeypatch, tmp_path / "site-packages"):
        with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
            provenance.verify_ctp_simnow_managed_artifact_provenance_for_fronts(
                td_front="tcp://td.custom.example:15001",
                md_front="tcp://md.custom.example:15002",
            )

        assert caught.value.reason == "artifact_pin_unavailable"
        assert not any(name == "bt_api_py" or name.startswith("bt_api_py.") for name in sys.modules)


def test_managed_explicit_front_verifier_accepts_exact_three_pinned_distributions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pair = ("tcp://td.custom.example:15001", "tcp://md.custom.example:15002")
    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_profile="custom_unlisted",
        ctp_fronts=pair,
        include_parent=True,
    ):
        provenance.verify_ctp_simnow_managed_artifact_provenance_for_fronts(
            td_front=pair[0], md_front=pair[1]
        )
        assert not any(
            name in ("bt_api_base", "bt_api_ctp", "bt_api_py")
            or name.startswith(("bt_api_base.", "bt_api_ctp.", "bt_api_py."))
            for name in sys.modules
        )


def test_managed_explicit_front_verifier_rejects_changed_parent_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site-packages"
    pins = _write_sdk_install(site_root, include_parent=True)
    parent_file = site_root / "bt_api_py" / "_ctp_execution_authorization.py"
    parent_file.write_text(
        "class CtpExecutionApprovalContext: pass\n# modified\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        provenance.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_root), "platlib": str(site_root)},
    )
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", pins)
    monkeypatch.syspath_prepend(str(site_root))
    importlib.invalidate_caches()

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_simnow_managed_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "artifact_file_hash_mismatch"


@pytest.mark.parametrize(
    ("td_front", "md_front"),
    (
        ("udp://td.custom.example:15001", "tcp://md.custom.example:15002"),
        ("tcp://td.custom.example/path", "tcp://md.custom.example:15002"),
        ("tcp://td.custom.example:0", "tcp://md.custom.example:15002"),
        (" tcp://td.custom.example:15001", "tcp://md.custom.example:15002"),
    ),
)
def test_explicit_front_verifier_rejects_noncanonical_tcp_strings(
    td_front: str, md_front: str
) -> None:
    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance_for_fronts(
            td_front=td_front,
            md_front=md_front,
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_explicit_front_verifier_rejects_shadowed_package_import_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site-packages"
    with _installed_test_sdk(monkeypatch, site_root):
        shadow_root = tmp_path / "shadow"
        shadow_package = shadow_root / "bt_api_base"
        shadow_package.mkdir(parents=True)
        (shadow_package / "__init__.py").write_text("SHADOW = True\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(shadow_root))

        with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
            provenance.verify_ctp_sdk_artifact_provenance_for_fronts(
                td_front="tcp://td.custom.example:15001",
                md_front="tcp://md.custom.example:15002",
            )

    assert caught.value.reason == "artifact_import_rejected"


@pytest.mark.parametrize(
    ("profile", "td_front", "md_front"),
    (
        (
            "set1_group1",
            "tcp://180.168.146.187:10201",
            "tcp://180.168.146.187:10211",
        ),
        (
            "set1_group2",
            "tcp://180.168.146.187:10202",
            "tcp://180.168.146.187:10212",
        ),
        (
            "set2_7x24",
            "tcp://180.168.146.187:10130",
            "tcp://180.168.146.187:10131",
        ),
    ),
)
def test_configured_front_pair_maps_exactly_to_reviewed_sdk_metadata(
    profile: str, td_front: str, md_front: str
) -> None:
    assert provenance.simnow_profile_for_fronts(td_front=td_front, md_front=md_front) == profile
    assert provenance.simnow_fronts_for_profile(profile) == (td_front, md_front)


@pytest.mark.parametrize(
    ("td_front", "md_front"),
    (
        ("tcp://180.168.146.187:10202", "tcp://180.168.146.187:10131"),
        ("tcp://127.0.0.1:10130", "tcp://127.0.0.1:10131"),
        ("tcp://user@180.168.146.187:10130", "tcp://180.168.146.187:10131"),
        ("tcp://180.168.146.187:10130/path", "tcp://180.168.146.187:10131"),
    ),
)
def test_configured_front_pair_rejects_mixed_custom_or_unsafe_addresses(
    td_front: str, md_front: str
) -> None:
    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.simnow_profile_for_fronts(td_front=td_front, md_front=md_front)
    assert caught.value.reason == "profile_front_mismatch"


@pytest.mark.parametrize(
    ("profile", "fronts"),
    (
        ("set1_group1", EXPECTED_SET1_GROUP1_FRONTS),
        ("set1_group2", EXPECTED_SET1_GROUP2_FRONTS),
    ),
)
def test_pinned_test_artifacts_accept_published_set1_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    fronts: tuple[str, str],
) -> None:
    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_profile=profile,
        ctp_fronts=fronts,
    ):
        provenance.verify_ctp_sdk_artifact_provenance(profile)


def test_same_version_repacked_content_fails_record_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site-packages"
    pins = _write_sdk_install(site_root)
    selector = site_root / "bt_api_ctp" / "ctp_env_selector.py"
    selector.write_text(
        _selector_source("set2_7x24", EXPECTED_FRONTS) + "# repacked\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        provenance.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_root), "platlib": str(site_root)},
    )
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", pins)
    monkeypatch.syspath_prepend(str(site_root))

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")

    assert caught.value.reason == "artifact_file_hash_mismatch"


def test_record_rewrite_cannot_relabel_a_repacked_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site-packages"
    approved = _write_sdk_install(site_root)
    repacked_root = tmp_path / "repacked-site-packages"
    repacked = _write_sdk_install(
        repacked_root,
        ctp_fronts=("tcp://180.168.146.187:10201", "tcp://180.168.146.187:10211"),
        ctp_wheel_sha256=approved["bt_api_ctp"].wheel_sha256,
    )
    assert repacked["bt_api_ctp"].record_sha256 != approved["bt_api_ctp"].record_sha256
    monkeypatch.setattr(
        provenance.sysconfig,
        "get_paths",
        lambda: {"purelib": str(repacked_root), "platlib": str(repacked_root)},
    )
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", approved)
    monkeypatch.syspath_prepend(str(repacked_root))

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")

    assert caught.value.reason == "artifact_record_pin_mismatch"


@pytest.mark.parametrize("source_kind", ("editable", "source"))
def test_source_distributions_are_rejected_even_with_matching_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_kind: str
) -> None:
    site_root = tmp_path / "site-packages"
    pins = _write_sdk_install(
        site_root,
        editable_ctp=source_kind == "editable",
        source_ctp=source_kind == "source",
    )
    monkeypatch.setattr(
        provenance.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_root), "platlib": str(site_root)},
    )
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", pins)
    monkeypatch.syspath_prepend(str(site_root))

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")

    assert caught.value.reason == "artifact_provenance_invalid"


def test_wheel_digest_mismatch_is_rejected_after_exact_record_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site-packages"
    installed = _write_sdk_install(site_root, ctp_wheel_sha256="c" * 64)
    approved = dict(installed)
    approved["bt_api_ctp"] = replace(installed["bt_api_ctp"], wheel_sha256="d" * 64)
    monkeypatch.setattr(
        provenance.sysconfig,
        "get_paths",
        lambda: {"purelib": str(site_root), "platlib": str(site_root)},
    )
    monkeypatch.setattr(provenance, "CTP_SDK_ARTIFACT_PINS", approved)
    monkeypatch.syspath_prepend(str(site_root))

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")

    assert caught.value.reason == "artifact_wheel_hash_mismatch"


def test_same_artifact_with_changed_profile_front_pair_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed_fronts = (
        "tcp://180.168.146.187:10201",
        "tcp://180.168.146.187:10211",
    )
    with _installed_test_sdk(
        monkeypatch,
        tmp_path / "site-packages",
        ctp_fronts=changed_fronts,
    ), pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance("set2_7x24")

    assert caught.value.reason == "profile_front_mismatch"


@pytest.mark.parametrize("profile", ("set2_7x24_vpn", "set2_7x24_4000x", "auto"))
def test_non_catalog_profile_is_rejected_without_loading_distributions(profile: str) -> None:
    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_sdk_artifact_provenance(profile)

    assert caught.value.reason == "profile_not_pinned"
