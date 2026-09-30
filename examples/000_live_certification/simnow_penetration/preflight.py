"""Offline admission inventory; never imports a provider or grants live access."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = Path(__file__).resolve().parent
ENV_KEYS = (
    "CTP_USER_ID",
    "CTP_PASSWORD",
    "CTP_BROKER_ID",
    "CTP_APP_ID",
    "CTP_AUTH_CODE",
    "CTP_MD_FRONT",
    "CTP_TD_FRONT",
)
PROFILES = ("set1_group1", "set1_group2", "set2_7x24")
MAX_ENV_BYTES = 1024 * 1024


class _Rejected(ValueError):
    pass


def _read_ignored_env(repo_root):
    """Read only a bounded, untracked regular file; never evaluate dotenv text."""
    path = repo_root / ".env"
    for args, required in (
        (["git", "check-ignore", "-q", "--", ".env"], 0),
        (["git", "ls-files", "--error-unmatch", "--", ".env"], 1),
    ):
        result = subprocess.run(
            args,
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if result.returncode != required:
            raise _Rejected("env_not_ignored_or_tracked")
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_file_attributes", 0) & 0x400
        or before.st_size > MAX_ENV_BYTES
    ):
        raise _Rejected("env_file_rejected")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        actual = os.fstat(stream.fileno())
        if (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
            raise _Rejected("env_file_changed")
        raw = stream.read(MAX_ENV_BYTES + 1)
    if len(raw) > MAX_ENV_BYTES:
        raise _Rejected("env_file_rejected")
    values = {}
    for line in raw.decode("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if key not in ENV_KEYS:
            continue
        if not separator or key in values:
            raise _Rejected("env_duplicate_or_invalid_assignment")
        value = value.strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise _Rejected("env_assignment_invalid")
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        if "${" in value or "$(" in value or "\x00" in value:
            raise _Rejected("env_expansion_unsupported")
        values[key] = value
    return values


def _environment_report(repo_root, profile):
    result = {"presence": dict.fromkeys(ENV_KEYS, False), "pair": "NOT_CHECKED"}
    try:
        values = _read_ignored_env(repo_root)
        result["presence"] = {key: bool(values.get(key)) for key in ENV_KEYS}
        if not all(result["presence"].values()):
            result["reason"] = "env_required_variables_missing"
        if profile is None:
            result["reason"] = "explicit_simnow_profile_required"
            return result
        from backtrader_runtime.ctp_artifact_provenance import simnow_fronts_for_profile

        td, md = simnow_fronts_for_profile(profile)
        matches = values.get("CTP_TD_FRONT") == td and values.get("CTP_MD_FRONT") == md
        result["pair"] = "MATCHES_SOURCE_PROFILE" if matches else "MISMATCH"
        if not matches:
            result["reason"] = "env_front_pair_does_not_match_selected_source_profile"
    except _Rejected as error:
        result["reason"] = error.args[0]
    except Exception:
        result["reason"] = "env_inspection_unavailable"
    return result


def _sdk_report():
    from backtrader_runtime.ctp_artifact_provenance import (
        CTP_SDK_ARTIFACT_PINS,
        _validate_installed_distribution,
    )

    reports = {}
    for name in ("bt_api_base", "bt_api_ctp", "bt_api_py", "bt_api_execution"):
        item = {"installed": False, "payload": "NOT_VERIFIED", "import_tested": False}
        reports[name] = item
        try:
            version = importlib.metadata.version(name)
            item["installed"] = True
            if re.fullmatch(r"[0-9][A-Za-z0-9.+!_-]{0,95}", version):
                item["version"] = version
            pin = CTP_SDK_ARTIFACT_PINS.get(name)
            if pin is None:
                item["reason"] = "no_pin_in_registered_readonly_artifact_set"
            else:
                item["expected_version"] = pin.version
                if version != pin.version:
                    item["reason"] = "installed_version_mismatch"
                else:
                    # Disk/metadata/RECORD verification only. Do not import SDKs
                    # or invoke the profile helper that imports a SDK selector.
                    _validate_installed_distribution(pin)
                    item["payload"] = "MATCHES_SOURCE_READONLY_PIN"
        except importlib.metadata.PackageNotFoundError:
            item["reason"] = "distribution_missing"
        except Exception:
            item["reason"] = "installed_payload_verification_failed"
    return reports


def inspect_admission(*, repo_root=REPO_ROOT, suite_root=SUITE_ROOT, profile=None):
    """Return value-free facts; successful inspections still cannot certify cases."""
    from backtrader_runtime.inventory import iteration41_runtime_registry
    from backtrader_runtime.registry import validate_runtime_config

    config = {"status": "BLOCKED", "reason": "suite_not_registered", "private_config_read": False}
    try:
        registry = iteration41_runtime_registry()
        registry.require_runtime_dir(suite_root)
    except Exception:
        pass
    else:
        config["private_config_read"] = True
        try:
            validate_runtime_config(suite_root, registry)
            config["reason"] = "registered_config_valid_but_certification_runner_unavailable"
        except Exception:
            config["reason"] = "registered_config_validation_failed"
    return {
        "mode": "OFFLINE_ADMISSION_PREFLIGHT",
        "certification": "BLOCKED",
        "write_policy": "NO_WRITE",
        "live_policy": "LIVE_NO_GO",
        "provider_preflight_started": False,
        "real_cases_passed": 0,
        "environment": _environment_report(Path(repo_root), profile),
        "config": config,
        "sdk": _sdk_report(),
        "blocking_reasons": [
            "managed_certification_runner_unavailable",
            "native_lifecycle_and_provider_acceptance_unverified",
            "ctp_write_admission_closed",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, help="explicit legacy source profile")
    args = parser.parse_args(argv)
    # The standalone entrypoint must inspect this checkout's source controls.
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        report = inspect_admission(profile=args.profile)
    except Exception:
        report = {"certification": "BLOCKED", "reason": "offline_inspection_failed"}
    print(json.dumps(report, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
