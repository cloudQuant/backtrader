"""Retired SimNow launcher; use ``run.py --replay`` for local replay.

This entry no longer composes a provider runtime or reads the historical
configuration. It has no managed runtime session port, so it cannot expose a
session snapshot or qualify quote freshness.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

def _run_config_first_cli(argv=None) -> int:
    """Reject the retired live launcher without reading any runtime config."""

    del argv
    print(
        json.dumps(
            {
                "status": "BLOCKED",
                "mode": "live",
                "reason": "SIMNOW_LAUNCHER_RETIRED",
                "provider_configuration": "not_read",
                "provider_runtime": "not_started",
                "replay_entry": "python run.py --replay",
            },
            sort_keys=True,
        )
    )
    return 2


def main(argv=None) -> int:
    """Retain a fail-closed entrypoint for the retired launcher."""

    return _run_config_first_cli(argv)


if __name__ == "__main__":
    raise SystemExit(_run_config_first_cli())

CTP_EXCHANGE = "CTP___FUTURE"
_ENDPOINT_ENV_KEYS = ("CTP_TD_FRONT", "CTP_MD_FRONT", "CTP_ENV_PROFILE")
ARTIFACT_OVERRIDE_ENV = "ITER30_ALLOW_EXTERNAL_BACKTRADER"

try:
    from . import legacy_runner as run
except ImportError:  # Direct execution from this example directory.
    import legacy_runner as run


def require_runtime_artifact() -> dict[str, Any]:
    """Fail closed before any session unless the workspace source is loaded.

    ``ITER30_ALLOW_EXTERNAL_BACKTRADER=1`` relaxes the check for a diagnostic
    run; such a report must not be used as G3/G4 evidence.
    """

    allow = str(os.environ.get(ARTIFACT_OVERRIDE_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        return run.require_target_backtrader_artifact(allow_external=allow)
    except run.RunnerConfigurationError as exc:
        raise SystemExit(f"simnow_launcher: {exc}") from None


class FeedClock:
    """Minimal monotonic feed clock satisfying the injected-clock contract."""

    @staticmethod
    def monotonic_ns() -> int:
        """Return the process monotonic clock, satisfying the injected-clock contract."""
        return time.monotonic_ns()


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a local .env file into a plain dict without shell evaluation.

    Comments and blank lines are skipped and values are only quote-stripped;
    a missing file yields an empty dict.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def require_frozen_fronts(environ: Mapping[str, str], selection: Any) -> list[str]:
    """Reject inherited endpoints that disagree; return inert matching keys.

    The selected pair comes from the SDK's frozen table, so an environment
    variable is never a routing input.  A variable that agrees with the frozen
    pair is inert but recorded; one that disagrees fails closed instead of
    silently re-routing the session.
    """

    inert: list[str] = []
    expected = {
        "CTP_TD_FRONT": selection.td_front,
        "CTP_MD_FRONT": selection.md_front,
        "CTP_ENV_PROFILE": selection.actual_profile,
    }
    for key in _ENDPOINT_ENV_KEYS:
        value = str(environ.get(key) or "").strip()
        if not value:
            continue
        if expected[key] is None:
            inert.append(key)
            continue
        if value != expected[key]:
            raise SystemExit(
                f"simnow_launcher: SIMNOW_PROFILE_OVERRIDE_REJECTED: {key} disagrees with the "
                f"frozen pair selected by {selection.requested_profile}"
            )
        inert.append(key)
    return inert


def build_exchange_kwargs(
    env: Mapping[str, str], selection: Any, rules_hash: str = ""
) -> dict[str, Any]:
    """Reject the retired per-CTP config builder without asserting data quality."""

    del env, selection, rules_hash
    raise RuntimeError("CTP_EXCHANGE_KWARGS_UNAVAILABLE_NEUTRAL_RUNTIME_REQUIRED")


def wait_ctp_session_ready(
    api: Any,
    timeout: float = 30.0,
    *,
    _test_only_injection: object | None = None,
) -> dict[str, Any]:
    """Retire the raw CTP poll; session observation requires a managed SDK port."""

    del api, timeout, _test_only_injection
    raise RuntimeError("MANAGED_RUNTIME_ACCOUNT_SESSION_PORT_REQUIRED")
