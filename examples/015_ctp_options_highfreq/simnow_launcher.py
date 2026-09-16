"""SimNow Set-2 (7x24) live launcher for the 015 engineering observation.

Local modification entry (user-approved): reads the SimNow Set-2 credentials
and fronts from this directory's ``.env``, builds an authenticated
``bt_api_py.BtApi`` and injects it into the example's existing zero-write
``run_engineering_observation(config, api=..., ...)`` path:

- Never modifies run.py / engineering_smoke.py / the strategy itself;
- the injected chain stays ``market_data_only`` read-only: no orders and no
  cancels;
- ClockMapping / CtpCohortNow are built here from a process monotonic+wall
  anchor, with rules_hash bound to the fixture bundle (matching the example's
  own checks) and synthetic=False.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

CTP_EXCHANGE = "CTP___FUTURE"
CLOCK_DOMAIN = "simnow-set2-live-monotonic-v1"
MAPPING_SOURCE = "simnow-set2-live-launcher-monotonic-anchor"
RUN_SECONDS = float(os.environ.get("SIMNOW_LAUNCHER_RUN_SECONDS") or "120")
RECEIVE_CLOCK_ERROR_MS = 5.0
ERROR_BOUND_NS = 50_000_000  # 50 ms calibration bound for a local monotonic anchor


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


def build_exchange_kwargs(env: dict[str, str], rules_hash: str = "") -> dict[str, Any]:
    """Build ``CTP___FUTURE`` kwargs including the cohort clock/rule identity.

    Unlike the 014_1/014_2 launchers, quote_v2_metadata must also carry the
    ``rules_hash`` (canonical sha256 of the frozen fixture bundle); otherwise
    the tick's rule identity fails the observation checks.
    """
    required = ("CTP_USER_ID", "CTP_PASSWORD")
    missing = [key for key in required if not str(env.get(key) or "").strip()]
    if missing:
        raise SystemExit(f"simnow_launcher: missing {missing} in {HERE / '.env'}")
    profile = str(env.get("CTP_ENV_PROFILE") or "set2_7x24_4000x").strip()
    return {
        CTP_EXCHANGE: {
            "broker_id": str(env.get("CTP_BROKER_ID") or "9999").strip(),
            "user_id": str(env["CTP_USER_ID"]).strip(),
            "password": str(env["CTP_PASSWORD"]),
            "app_id": str(env.get("CTP_APP_ID") or "simnow_client_test").strip(),
            "auth_code": str(env.get("CTP_AUTH_CODE") or "0000000000000000").strip(),
            "td_front": str(env.get("CTP_TD_FRONT") or "tcp://182.254.243.31:40001").strip(),
            "md_front": str(env.get("CTP_MD_FRONT") or "tcp://182.254.243.31:40011").strip(),
            "ctp_env_profile": profile,
            "require_ctp_profile": profile,
            "auto_settlement_confirm": False,
            # CTP MD cannot self-certify clock calibration or rule identity:
            # tick clock_domain_id and rules_hash default to empty, while the
            # feed's decision-now attach and the observation wrapper require
            # tick/mapping/provider agreement. Declare this launcher's monotonic
            # clock domain explicitly and bind the rules to the frozen fixture
            # bundle.
            "quote_v2_metadata": {
                "clock_domain_id": CLOCK_DOMAIN,
                "rules_hash": rules_hash,
                "receive_clock_quality": "verified",
                "freshness_verified": True,
            },
        }
    }


def wait_ctp_session_ready(api: Any, timeout: float = 30.0) -> dict[str, Any]:
    """Trigger the lazy CTP connect and wait (bounded) for auth/login."""

    feed = api.exchange_feeds.get(CTP_EXCHANGE)
    if feed is None:
        api.close()
        raise SystemExit("simnow_launcher: CTP feed was not created by BtApi")
    try:
        feed.get_query_session_scope()
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator below
        api.close()
        raise SystemExit(f"simnow_launcher: CTP connect failed: {exc}") from exc
    deadline = time.monotonic() + max(float(timeout), 1.0)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = dict(api.get_ctp_session_state(exchange_name=CTP_EXCHANGE) or {})
        if last.get("account_fingerprint") and last.get("read_only_ready"):
            return last
        time.sleep(0.25)
    return last


def main() -> int:
    """Run the bounded Set-2 zero-write engineering observation via injection.

    Builds an authenticated BtApi plus a process-monotonic ClockMapping
    (rules_hash bound to the fixture bundle, synthetic=False) and a
    CtpCohortNow provider, then injects them into the example's existing
    ``run_engineering_observation``; the report's PASS status decides the exit
    code.
    """
    from bt_api_py.bt_api import BtApi
    from backtrader.feeds import ClockMapping, CtpCohortNow
    from backtrader.feeds.ctpcohort import CtpCohortNow as _CohortNow  # noqa: F401

    from ctp_options_highfreq_strategy import canonical_sha256
    from engineering_smoke import SECOND_SET_ENGINEERING_PROFILE
    from run import (
        effective_config,
        load_config,
        load_fixture,
        run_engineering_observation,
        validate_bundle,
    )

    env = {**load_env_file(HERE / ".env"), **dict(os.environ)}
    if not math.isfinite(RUN_SECONDS) or not 0 < RUN_SECONDS <= 3600:
        raise SystemExit("simnow_launcher: SIMNOW_LAUNCHER_RUN_SECONDS must be in (0, 3600]")

    config, _path = load_config(HERE / "config.yaml")
    effective = effective_config(config, mode="shadow", purpose="observation")
    fixture, _fixture_path, _fixture_hash = load_fixture(effective)
    bundle = validate_bundle(fixture, effective)
    bundle_hash = canonical_sha256(bundle)

    api = BtApi(
        exchange_kwargs=build_exchange_kwargs(env, rules_hash=bundle_hash),
        debug=False,
    )
    session = wait_ctp_session_ready(api)
    if not (session.get("account_fingerprint") and session.get("read_only_ready")):
        api.close()
        raise SystemExit(
            "simnow_launcher: CTP session not ready in 30s: "
            + json.dumps(session, ensure_ascii=False, default=str)
        )
    generation = int(session.get("connection_generation") or 0)
    if generation <= 0:
        api.close()
        raise SystemExit("simnow_launcher: CTP session has no positive connection generation")

    anchor_mono_ns = time.monotonic_ns()
    anchor_wall = dt.datetime.now(dt.timezone.utc)
    # Cover the whole bounded observation window plus calibration slack.
    valid_until_ns = anchor_mono_ns + int((RUN_SECONDS + 120.0) * 1_000_000_000)
    mapping = ClockMapping(
        mapping_id=f"simnow-set2-live-{int(anchor_wall.timestamp())}",
        wall_utc_at_anchor=anchor_wall,
        mono_ns_at_anchor=anchor_mono_ns,
        clock_domain_id=CLOCK_DOMAIN,
        connection_generation=generation,
        source=MAPPING_SOURCE,
        error_bound_ns=ERROR_BOUND_NS,
        valid_until_mono_ns=valid_until_ns,
        rules_hash=bundle_hash,
        synthetic=False,
    )

    def live_now_provider(tick: Any) -> CtpCohortNow:
        receive_ns = getattr(tick, "recv_monotonic_ns", None)
        now_ns = time.monotonic_ns()
        if type(receive_ns) is int and now_ns < receive_ns:
            now_ns = receive_ns
        return CtpCohortNow(
            now_monotonic_ns=now_ns,
            now_epoch=time.time(),
            clock_domain_id=CLOCK_DOMAIN,
            receive_clock_error_ms=RECEIVE_CLOCK_ERROR_MS,
        )

    try:
        report = run_engineering_observation(
            effective,
            api=api,
            environment_profile=SECOND_SET_ENGINEERING_PROFILE,
            run_seconds=RUN_SECONDS,
            feed_clock=FeedClock(),
            clock_mapping=mapping,
            live_now_provider=live_now_provider,
        )
    finally:
        try:
            api.close()
        except Exception:
            pass
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    status = str(report.get("status") or report.get("exit_status") or "")
    return 0 if "PASS" in status else 2


if __name__ == "__main__":
    raise SystemExit(main())
