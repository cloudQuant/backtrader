"""Retired SimNow launcher retained for historical source review.

The historical launcher could create a read-only SimNow session. Its public
``main`` now routes through the fixed Iteration 41 runtime directory, which
requires registered ``runtime/config.yaml`` and supports local replay only.
It does not load the legacy candidate config, credentials, or provider.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
RUNTIME_DIR = HERE / "runtime"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from backtrader_runtime.legacy import (  # noqa: E402
    legacy_direct_execution_error as _legacy_direct_execution_error,
    run_legacy_config_first_cli as _run_legacy_config_first_cli,
)

_SESSION_WAIT_TEST_TOKEN = object()


def _run_config_first_cli(argv=None) -> int:
    """Route the retired SimNow launcher through the registered replay runtime."""

    return _run_legacy_config_first_cli(RUNTIME_DIR, argv)


def main(argv=None) -> int:
    """Retain the importable entrypoint while requiring the Iteration 41 runtime."""

    return _run_config_first_cli(argv)


if __name__ == "__main__":
    raise SystemExit(_run_config_first_cli())

CTP_EXCHANGE = "CTP___FUTURE"
_ENDPOINT_ENV_KEYS = ("CTP_TD_FRONT", "CTP_MD_FRONT", "CTP_ENV_PROFILE")
ARTIFACT_OVERRIDE_ENV = "ITER30_ALLOW_EXTERNAL_BACKTRADER"

try:
    from . import run as run
except ImportError:  # Direct execution from this example directory.
    import run as run


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
    """Build ``CTP___FUTURE`` kwargs for the selected frozen environment.

    The ``quote_v2_metadata`` block carries the identifiers derived from the
    selected profile; the CTP managed receipt still withholds every execution
    qualification fact, so this metadata remains diagnostic only.
    """

    required = ("CTP_USER_ID", "CTP_PASSWORD")
    missing = [key for key in required if not str(env.get(key) or "").strip()]
    if missing:
        raise SystemExit(f"simnow_launcher: missing {missing} in {HERE / '.env'}")
    if not selection.actual_profile or not selection.td_front or not selection.md_front:
        raise SystemExit(
            "simnow_launcher: the selected environment has no resolved frozen front pair"
        )
    profile = str(selection.actual_profile)
    return {
        CTP_EXCHANGE: {
            "broker_id": str(env.get("CTP_BROKER_ID") or "9999").strip(),
            "user_id": str(env["CTP_USER_ID"]).strip(),
            "password": str(env["CTP_PASSWORD"]),
            "app_id": str(env.get("CTP_APP_ID") or "simnow_client_test").strip(),
            "auth_code": str(env.get("CTP_AUTH_CODE") or "0000000000000000").strip(),
            "td_front": str(selection.td_front),
            "md_front": str(selection.md_front),
            "ctp_env_profile": profile,
            "require_ctp_profile": profile,
            "auto_settlement_confirm": False,
            # CTP MD cannot self-certify clock calibration or rule identity:
            # tick clock_domain_id and rules_hash default to empty, while the
            # feed's decision-now attach and the observation wrapper require
            # tick/mapping/provider agreement. Declare the selected profile's
            # monotonic clock domain explicitly and bind the rules to the
            # frozen fixture bundle.
            "quote_v2_metadata": {
                "clock_domain_id": selection.clock_domain_id,
                "rules_hash": rules_hash,
                "receive_clock_quality": "verified",
                "freshness_verified": True,
            },
        }
    }


def wait_ctp_session_ready(
    api: Any,
    timeout: float = 30.0,
    *,
    _test_only_injection: object | None = None,
) -> dict[str, Any]:
    """Observe a fake session only; never trigger a lazy CTP connection.

    This retired launcher has no registered live runtime. The wait helper is
    therefore limited to explicitly marked test doubles and does not call the
    feed's query-session accessor, which may connect lazily.
    """

    if (
        _test_only_injection is not _SESSION_WAIT_TEST_TOKEN
        or getattr(api, "__backtrader_test_double__", False) is not True
        or isinstance(api, run.BtApiStore)
    ):
        raise _legacy_direct_execution_error("examples/015_ctp_options_highfreq/simnow_launcher.py")

    feed = api.exchange_feeds.get(CTP_EXCHANGE)
    if feed is None:
        raise SystemExit("simnow_launcher: CTP feed was not created by the injected test double")
    deadline = time.monotonic() + max(float(timeout), 1.0)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = dict(api.get_ctp_session_state(exchange_name=CTP_EXCHANGE) or {})
        if last.get("account_fingerprint") and last.get("read_only_ready"):
            return last
        time.sleep(0.25)
    return last
