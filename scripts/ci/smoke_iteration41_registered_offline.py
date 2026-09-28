"""Run every registered Iteration 41 offline config through the public CLI.

Only code-owned backtest/local_backtest and simulation/replay registrations are
eligible. The script filters registrations before reading configs, so it never
needs the private SimNow file and never runs shadow, private-read, or live
provider routes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.inventory import (
    ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
    ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
    ITERATION41_010_OKX_SHADOW_REGISTRATION,
    ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
    ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
    iteration41_runtime_registry,
)
from backtrader_runtime.registry import RuntimeProfile


OFFLINE_PAIRS = frozenset({("backtest", "local_backtest"), ("simulation", "replay")})
PRIVATE_READ_ONLY = (
    (
        ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
        ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
    ),
    (
        ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
        ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
    ),
)


def _offline_smoke_registrations(registry):
    """Filter by exact code-owned policy before opening any runtime config."""

    selected = []
    skipped = []
    for registration in registry.registrations:
        private_contract = next(
            (item for item in PRIVATE_READ_ONLY if item[0].runtime_id == registration.runtime_id),
            None,
        )
        if private_contract is not None:
            expected_registration, _binding = private_contract
            profile = registration.profile_for("simulation", "sandbox")
            unavailable = tuple(
                (item.mode, item.preset, item.reason)
                for item in registration.unavailable_mode_profiles
            )
            if (
                registration is not expected_registration
                or len(registration.profiles) != 1
                or type(profile) is not RuntimeProfile
                or registration.profiles[0] is not profile
                or registration.allowed_presets != ()
                or registration.allowed_secrets_refs != ("none",)
                or profile.allowed_parameter_keys != ()
                or profile.allowed_secrets_refs != ("config_yaml",)
                or profile.available_capabilities != ()
                or profile.approval_receipt_digest is not None
                or profile.runner_module is not None
                or profile.runner_entrypoint != "run_runtime"
                or profile.capability_modules != ()
                or profile.offline_managed_execution is not False
                or profile.sandbox_write_policy != "deny"
                or unavailable
                != (("live", "managed_live_direct", "managed_live_direct_profile_unavailable"),)
                or registration.runner_module is not None
                or registration.available_capabilities != ()
                or registration.capability_modules != ()
                or registration.bootstrap_parameters != ()
                or registration.sandbox_write_policy != "deny"
                or registry.ctp_simnow_readonly_bindings
                != tuple(binding for _, binding in PRIVATE_READ_ONLY)
            ):
                raise RuntimeError("private CTP runtime no longer matches its read-only contract")
            skipped.append((registration, "SKIP_PRIVATE_READ_ONLY"))
            continue
        if registration.runtime_id == ITERATION41_010_OKX_SHADOW_REGISTRATION.runtime_id:
            if (
                registration is not ITERATION41_010_OKX_SHADOW_REGISTRATION
                or registration.allowed_presets != ("shadow",)
            ):
                raise RuntimeError("public shadow runtime no longer matches its reviewed contract")
            skipped.append((registration, "SKIP_SHADOW"))
            continue
        if (
            registration.allowed_presets not in (("replay",), ("local_backtest",))
            or registration.runner_module is None
        ):
            raise RuntimeError("unreviewed runtime in offline smoke inventory")
        selected.append(registration)
    return tuple(selected), tuple(skipped)


def main() -> int:
    registry = iteration41_runtime_registry()
    selected, skipped = _offline_smoke_registrations(registry)
    for registration, skip_reason in skipped:
        print("{0}: {1}".format(registration.runtime_id, skip_reason), flush=True)

    for registration in selected:
        config = load_runtime_config(registration.runtime_dir, registry=registry)
        if (config.mode, config.preset) not in OFFLINE_PAIRS:
            raise RuntimeError("offline smoke config does not match its code-owned preset")
        if config.secrets_ref != "none":
            raise RuntimeError("offline smoke config unexpectedly references credentials")

    failures = []
    for registration in selected:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "backtrader_runtime",
                    "run",
                    "--strategy-dir",
                    str(registration.runtime_dir),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            status = "PASS" if result.returncode == 0 else "FAIL({0})".format(result.returncode)
            if result.returncode:
                failures.append(registration.runtime_id)
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
            failures.append(registration.runtime_id)
        print("{0}: {1}".format(registration.runtime_id, status), flush=True)

    print(
        "offline smoke: {0} passed, {1} failed, {2} selected, {3} skipped".format(
            len(selected) - len(failures), len(failures), len(selected), len(skipped)
        ),
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
