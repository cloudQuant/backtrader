"""Offline admission facts cannot authorize a provider session or expose secrets."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples/000_live_certification/simnow_penetration/preflight.py"
spec = importlib.util.spec_from_file_location("simnow_000_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def ignored_env(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    from backtrader_runtime.ctp_artifact_provenance import simnow_fronts_for_profile

    td, md = simnow_fronts_for_profile("set1_group1")
    text = (
        "\n".join(
            f"{key}=sensitive-value-{index}" for index, key in enumerate(preflight.ENV_KEYS[:5])
        )
        + f"\nCTP_MD_FRONT={md}\nCTP_TD_FRONT={td}\n"
    )
    (tmp_path / ".env").write_text(text, encoding="utf-8")
    return tmp_path


def test_env_presence_and_explicit_pair_do_not_export_values(ignored_env):
    before = dict(os.environ)
    report = preflight._environment_report(ignored_env, "set1_group1")
    assert all(report["presence"].values())
    assert report["pair"] == "MATCHES_SOURCE_PROFILE"
    assert "reason" not in report
    assert "sensitive-value" not in json.dumps(report)
    assert "tcp://" not in json.dumps(report)
    assert dict(os.environ) == before


def test_no_implicit_pair_and_mixed_pair_rejects(ignored_env):
    assert preflight._environment_report(ignored_env, None)["reason"] == (
        "explicit_simnow_profile_required"
    )
    assert preflight._environment_report(ignored_env, "set1_group2")["pair"] == "MISMATCH"


@pytest.mark.parametrize(
    "suffix",
    [
        "CTP_PASSWORD=duplicate-secret\n",
        "CTP_PASSWORD=${INJECTED}\n",
    ],
)
def test_ambiguous_env_rejected_without_values(ignored_env, suffix):
    with (ignored_env / ".env").open("a", encoding="utf-8") as stream:
        stream.write(suffix)
    report = preflight._environment_report(ignored_env, "set1_group1")
    assert report["reason"] == "env_duplicate_or_invalid_assignment"
    assert not any(report["presence"].values())
    assert "secret" not in json.dumps(report)


def test_expansion_is_never_evaluated(ignored_env):
    (ignored_env / ".env").write_text("CTP_PASSWORD=$(do_something)\n", encoding="utf-8")
    report = preflight._environment_report(ignored_env, "set1_group1")
    assert report["reason"] == "env_expansion_unsupported"


def test_missing_credentials_remain_missing(ignored_env):
    text = (ignored_env / ".env").read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.startswith("CTP_PASSWORD="))
    (ignored_env / ".env").write_text(text, encoding="utf-8")
    report = preflight._environment_report(ignored_env, "set1_group1")
    assert report["reason"] == "env_required_variables_missing"
    assert report["presence"]["CTP_PASSWORD"] is False


@pytest.mark.parametrize("tracked", [False, True])
def test_git_protection_required_before_read(ignored_env, tracked, monkeypatch):
    if tracked:
        subprocess.run(["git", "add", "-f", ".env"], cwd=ignored_env, check=True)
    else:
        (ignored_env / ".gitignore").write_text("", encoding="utf-8")
    real_open = os.open

    def guarded_open(path, *args, **kwargs):
        if Path(path).name == ".env":
            pytest.fail("private file opened")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    assert preflight._environment_report(ignored_env, "set1_group1")["reason"] == (
        "env_not_ignored_or_tracked"
    )


def test_oversize_file_rejects(ignored_env):
    (ignored_env / ".env").write_bytes(b"x" * (preflight.MAX_ENV_BYTES + 1))
    assert preflight._environment_report(ignored_env, "set1_group1")["reason"] == (
        "env_file_rejected"
    )


def test_sdk_versions_do_not_substitute_for_payload_validation(monkeypatch):
    import backtrader_runtime.ctp_artifact_provenance as provenance

    pins = provenance.CTP_SDK_ARTIFACT_PINS
    monkeypatch.setattr(
        preflight.importlib.metadata,
        "version",
        lambda name: (pins[name].version if name in pins else "0.2.0"),
    )

    def reject_payload(pin):
        raise ValueError("sensitive-provider-data")

    monkeypatch.setattr(provenance, "_validate_installed_distribution", reject_payload)
    report = preflight._sdk_report()
    assert report["bt_api_ctp"]["reason"] == "installed_payload_verification_failed"
    assert report["bt_api_py"]["reason"] == "no_pin_in_registered_readonly_artifact_set"
    assert "sensitive-provider-data" not in json.dumps(report)
    assert all(not item["import_tested"] for item in report.values())


def test_unregistered_suite_does_not_open_private_config(ignored_env, monkeypatch):
    import backtrader_runtime.registry as registry

    monkeypatch.setattr(
        registry,
        "validate_runtime_config",
        lambda *a, **kw: (pytest.fail("unregistered private config opened")),
    )
    monkeypatch.setattr(preflight, "_sdk_report", dict)
    report = preflight.inspect_admission(repo_root=ignored_env, profile="set1_group1")
    assert report["config"] == {
        "status": "BLOCKED",
        "reason": "suite_not_registered",
        "private_config_read": False,
    }
    assert report["certification"] == "BLOCKED"
    assert report["real_cases_passed"] == 0
    assert report["provider_preflight_started"] is False


def test_fresh_process_has_no_sdk_import_or_network(ignored_env):
    code = r"""
import importlib.abc, importlib.util, json, socket, sys
from pathlib import Path
attempts = []
class BlockSdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("bt_api_"):
            attempts.append("SDK")
            raise AssertionError("SDK import attempted")
sys.meta_path.insert(0, BlockSdk())
def deny(*args, **kwargs):
    attempts.append("network")
    raise AssertionError("network attempted")
socket.create_connection = socket.getaddrinfo = deny
socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = deny
spec = importlib.util.spec_from_file_location("preflight", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
report = module.inspect_admission(repo_root=Path(sys.argv[2]), profile="set1_group1")
assert not any(name.startswith("bt_api_") for name in sys.modules)
assert not attempts
assert report["environment"]["pair"] == "MATCHES_SOURCE_PROFILE"
print(json.dumps(report))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPT), str(ignored_env)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["certification"] == "BLOCKED"
    assert report["live_policy"] == "LIVE_NO_GO"
    assert "sensitive-value" not in result.stdout + result.stderr


def test_cli_always_exits_blocked(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "inspect_admission", lambda **kw: {"certification": "BLOCKED"})
    assert preflight.main([]) == 2
    assert json.loads(capsys.readouterr().out)["certification"] == "BLOCKED"
