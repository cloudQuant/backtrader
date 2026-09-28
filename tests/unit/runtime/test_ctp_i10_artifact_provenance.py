"""Focused offline tests for the unregistered I10 artifact pin."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Mapping

import pytest

import backtrader_runtime.ctp_artifact_provenance as provenance


def _record_hash(contents: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode("ascii")
    return "sha256=" + encoded.rstrip("=")


def _write_fake_distribution(
    site_root: Path,
    distribution: str,
    module: str,
    version: str,
    wheel_filename: str,
    wheel_sha256: str,
) -> provenance.CtpSdkArtifactPin:
    package_root = site_root / module
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("FAKE_PACKAGE = True\n", encoding="utf-8")

    dist_info_name = distribution + "-" + version + ".dist-info"
    dist_info = site_root / dist_info_name
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: {0}\nVersion: {1}\n\n".format(distribution, version),
        encoding="utf-8",
    )
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        encoding="utf-8",
    )
    (dist_info / "direct_url.json").write_text(
        json.dumps(
            {
                "url": "file:///reviewed-wheelhouse/" + wheel_filename,
                "archive_info": {
                    "hash": "sha256=" + wheel_sha256,
                    "hashes": {"sha256": wheel_sha256},
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    record_relative = dist_info_name + "/RECORD"
    files = [
        path
        for root in (package_root, dist_info)
        for path in root.rglob("*")
        if path.is_file() and path.name != "RECORD"
    ]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for path in sorted(files):
        relative = path.relative_to(site_root).as_posix()
        contents = path.read_bytes()
        writer.writerow((relative, _record_hash(contents), str(len(contents))))
    writer.writerow((record_relative, "", ""))
    record_bytes = output.getvalue().encode("utf-8")
    (dist_info / "RECORD").write_bytes(record_bytes)
    return provenance.CtpSdkArtifactPin(
        distribution=distribution,
        module=module,
        version=version,
        wheel_filename=wheel_filename,
        wheel_sha256=wheel_sha256,
        record_sha256=hashlib.sha256(record_bytes).hexdigest(),
    )


def test_i10_pin_is_independent_and_uses_installed_record() -> None:
    i2 = provenance.CTP_SDK_ARTIFACT_PINS
    i9 = provenance.CTP_I9_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS
    i10 = provenance.CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS

    assert i10 is not i2
    assert i10 is not i9
    assert i10["bt_api_base"] is not i2["bt_api_base"]
    assert i10["bt_api_base"] == i2["bt_api_base"]
    assert i2["bt_api_ctp"].version == "2.0.3+iteration41.i2"
    assert not i9
    assert provenance.CTP_I10_REPRODUCED_WHEEL_SHA256 == (
        "e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4"
    )
    assert provenance.CTP_I10_EMBEDDED_WHEEL_RECORD_SHA256 == (
        "0f7f5724ed45f98a491f8f6bcc767f9825551a8e0753f0911a40e993a9c23911"
    )
    assert provenance.CTP_I10_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET == {
        "a": "c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673",
        "b": "cb768050b6f1a15c300591f3eae51e1ed9b4a7301a311817f88b285d85c40be2",
    }
    assert i10["bt_api_ctp"].version == "2.0.3+iteration41.i10"
    assert i10["bt_api_ctp"].wheel_sha256 == provenance.CTP_I10_REPRODUCED_WHEEL_SHA256
    assert (
        i10["bt_api_ctp"].record_sha256
        == provenance.CTP_I10_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET["a"]
    )
    assert i10["bt_api_ctp"].record_sha256 != provenance.CTP_I10_EMBEDDED_WHEEL_RECORD_SHA256


def test_i10_verifier_uses_its_independent_fake_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_root = tmp_path / "site-packages"
    site_root.mkdir()
    pins: Mapping[str, provenance.CtpSdkArtifactPin] = {
        "bt_api_base": _write_fake_distribution(
            site_root,
            "bt_api_base",
            "bt_api_base",
            "0.15.5",
            "bt_api_base-0.15.5-py3-none-any.whl",
            "1" * 64,
        ),
        "bt_api_ctp": _write_fake_distribution(
            site_root,
            "bt_api_ctp",
            "bt_api_ctp",
            "2.0.3+iteration41.i10",
            "bt_api_ctp-2.0.3+iteration41.i10-cp311-cp311-win_amd64.whl",
            "2" * 64,
        ),
    }
    monkeypatch.setattr(provenance.sysconfig, "get_paths", lambda: {"purelib": str(site_root)})
    monkeypatch.setattr(provenance, "CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS", pins)
    monkeypatch.syspath_prepend(str(site_root))
    # Other runtime tests may have imported the real SDK already. find_spec()
    # then reports that cached module's origin instead of this fake install.
    # Temporarily hide only the two top-level packages for this isolated test;
    # monkeypatch restores any pre-existing modules afterward.
    monkeypatch.delitem(sys.modules, "bt_api_base", raising=False)
    monkeypatch.delitem(sys.modules, "bt_api_ctp", raising=False)
    importlib.invalidate_caches()

    provenance.verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
        td_front="tcp://td.custom.example:15001",
        md_front="tcp://md.custom.example:15002",
    )

    assert "bt_api_base" not in sys.modules
    assert "bt_api_ctp" not in sys.modules


def test_i10_verifier_rejects_invalid_front_before_pin_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
            td_front="udp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "front_pair_syntax_invalid"


def test_i10_verifier_fails_closed_when_its_own_pin_table_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provenance, "CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS", {})

    with pytest.raises(provenance.CtpArtifactProvenanceError) as caught:
        provenance.verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://td.custom.example:15001",
            md_front="tcp://md.custom.example:15002",
        )

    assert caught.value.reason == "artifact_pin_unavailable"
