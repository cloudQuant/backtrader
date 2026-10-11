"""EM03 — external operator forced logout on the runner session (read-only).

Mode selection (unchanged hold mode wins first):

* ``scenario.logout_mode == "venue_api"`` (the config default): the
  operator-authorized venue logout.  The case issues ``ReqUserLogout``
  through the session's native client, requires an observed termination
  signal plus a ghost (unusable) session, then restores a fresh session on
  the same account and closes it.  SimNow exposes no broker-admin kick
  channel, so this is the only operator-controlled logout available.
* ``scenario.logout_mode`` anything else: the historical competing-login
  quick path — the recorded operator (operator/authorization refs) performs
  a competing login on the same account through a second session and the
  observed session A must show a native disconnect within the bounded
  window.  SimNow currently keeps concurrent sessions alive, so this path
  usually ends BLOCKED (``forced_logout_not_observed``).
* Operator-assist mode (scenario ``hold_seconds`` > 0, or
  ``BT_CERT_EM03_HOLD_SECONDS`` when the scenario value is 0): the case
  holds session A open and waits while the human operator triggers the
  server-side forced logout; any disconnect signal observed on A passes the
  case.  No second session is created.

No write action is used in any mode; facts carry no broker/user/account id
strings.
"""

from __future__ import annotations

import os
import time

from certlib import make_client
from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "EM03"
RISK = "READ"

_POLL_SECONDS = 0.5
_HOLD_POLL_SECONDS = 1.0
_HOLD_PROBE_SECONDS = 30.0
_MAX_HOLD_SECONDS = 1800.0


def _native_of(session):
    return getattr(session, "_client", None)


def _observe_signal(session, hook_calls):
    """First disconnect signal visible on the session's native client."""
    native = _native_of(session)
    if native is None:
        return ""
    if getattr(native, "_connected", True) is False:
        return "native_connected_flag"
    if getattr(native, "is_read_only_ready", True) is False:
        return "readonly_ready_flag"
    if hook_calls:
        return "on_disconnect_hook"
    return ""


def _register_disconnect_hook(session, hook_calls):
    """Best-effort on_disconnect hook; the attribute may not exist."""
    try:
        native = _native_of(session)
        if native is None or not hasattr(native, "on_disconnect"):
            return False
        native.on_disconnect = lambda reason: hook_calls.append(str(reason))
        return True
    except Exception:
        return False


def _resolve_hold_seconds(scenario) -> float:
    """Operator-assist window: scenario first, then the env override; 0 disables."""
    try:
        value = float(
            scenario.get("hold_seconds") or os.environ.get("BT_CERT_EM03_HOLD_SECONDS") or 0
        )
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(_MAX_HOLD_SECONDS, value))


def _hold_observation(client, hold_seconds):
    """Wait for an operator-triggered logout signal on the primary session.

    Returns ``(signal, held_seconds, connected, readonly_ready)``.
    """
    started = time.monotonic()
    deadline = started + hold_seconds
    next_probe = started + _HOLD_PROBE_SECONDS
    signal = ""
    connected = None
    readonly_ready = None
    while time.monotonic() < deadline:
        native = _native_of(client)
        connected = getattr(native, "_connected", None)
        readonly_ready = getattr(native, "is_read_only_ready", None)
        if connected is False:
            signal = "native_connected_flag"
        elif readonly_ready is False:
            signal = "readonly_ready_flag"
        elif time.monotonic() >= next_probe:
            next_probe = time.monotonic() + _HOLD_PROBE_SECONDS
            try:
                client.query_account()
            except SimNowSessionError as exc:
                signal = f"query_failure:{exc.reason}"
        if signal:
            break
        time.sleep(_HOLD_POLL_SECONDS)
    return signal, round(time.monotonic() - started, 3), connected, readonly_ready


def _run_operator_assist(
    ctx,
    client,
    operator_ref,
    authorization_ref,
    observed_generation,
    hold_seconds,
    hook_registered,
    hook_calls,
):
    ctx.log("operator-assist hold started; perform the forced logout now")
    signal, held_seconds, connected, readonly_ready = _hold_observation(client, hold_seconds)
    facts = {
        "operator_ref": operator_ref,
        "authorization_ref": authorization_ref,
        "signal": signal,
        "hold_seconds": round(hold_seconds, 3),
        "held_seconds": held_seconds,
        "observed_generation": observed_generation,
        "hook_registered": hook_registered,
        "hook_fired": bool(hook_calls),
        "A_connected": connected,
        "A_readonly_ready": readonly_ready,
    }
    if signal:
        return CaseResult(CASE_ID, "PASS", "", facts)
    return CaseResult(CASE_ID, "BLOCKED", "operator_logout_not_observed_during_hold", facts)


def _restore_session(ctx):
    """Open a fresh session, prove it authenticates, and close it.

    Returns ``(restoration_facts, error_reason)``; the error reason is empty
    on success.  The second session is always closed.
    """
    second = None
    try:
        second = make_client(ctx.config, ctx._env_values, ctx.topology)
        second.connect()
        account = second.query_account()
        restoration = {
            "generation": int(second.login_facts.get("connection_generation", 0) or 0),
            "account_rows": len(account["rows"]),
        }
        return restoration, ""
    except SimNowSessionError as exc:
        return {}, exc.reason
    except Exception as exc:  # noqa: BLE001 - bounded failure path, reason is capped
        return {}, f"exception:{type(exc).__name__}"
    finally:
        if second is not None:
            second.close()


def _run_venue_logout(ctx, client, operator_ref, authorization_ref, observed_generation):
    """Operator-authorized venue logout through the native logout API."""
    facts = {
        "operator_ref": operator_ref,
        "authorization_ref": authorization_ref,
        "observed_generation": observed_generation,
    }
    try:
        logout = client.request_logout()
    except SimNowSessionError as exc:
        facts["logout_error"] = exc.reason
        facts["logout_error_facts"] = exc.facts
        return CaseResult(CASE_ID, "BLOCKED", "venue_logout_not_observed", facts)

    facts["logout"] = logout
    if not logout.get("signal"):
        return CaseResult(CASE_ID, "BLOCKED", "venue_logout_not_observed", facts)
    if not logout.get("session_unusable"):
        return CaseResult(CASE_ID, "FAIL", "logout_did_not_terminate_session", facts)

    ctx.log("venue logout observed; restoring a fresh session")
    restoration, error_reason = _restore_session(ctx)
    if error_reason:
        facts["restoration_error"] = error_reason
        return CaseResult(CASE_ID, "FAIL", "restoration_failed", facts)

    facts.update(
        {
            "rule": "operator_authorized_venue_logout",
            "ghost_session": {"unusable": True, "reason": logout.get("unusable_reason", "")},
            "restoration": restoration,
            "scope_note": (
                "logout issued through the venue logout API by the certification "
                "operator; SimNow exposes no broker-admin kick channel"
            ),
        }
    )
    return CaseResult(CASE_ID, "PASS", "", facts)


class EM03Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em03")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em03")
        logout_mode = str(scenario.get("logout_mode") or "").strip()
        timeout = int(scenario.get("disconnect_timeout_ms", 20000)) / 1000.0
        observed_generation = int(client.login_facts.get("connection_generation", 0) or 0)
        hold_seconds = _resolve_hold_seconds(scenario)

        hook_calls = []
        hook_registered = _register_disconnect_hook(client, hook_calls)

        if hold_seconds > 0:
            return _run_operator_assist(
                ctx,
                client,
                operator_ref,
                authorization_ref,
                observed_generation,
                hold_seconds,
                hook_registered,
                hook_calls,
            )

        if logout_mode == "venue_api":
            return _run_venue_logout(
                ctx, client, operator_ref, authorization_ref, observed_generation
            )

        second = make_client(ctx.config, ctx._env_values, ctx.topology)
        try:
            fault_started = time.monotonic()
            try:
                second.connect()
            except SimNowSessionError as exc:
                return CaseResult(
                    CASE_ID,
                    "BLOCKED",
                    "operator_login_failed",
                    {
                        "reason": exc.reason,
                        "operator_ref": operator_ref,
                        "authorization_ref": authorization_ref,
                    },
                )
            second_generation = int(second.login_facts.get("connection_generation", 0) or 0)
            ctx.log(f"operator {operator_ref} logged in (generation={second_generation})")

            signal = ""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                signal = _observe_signal(client, hook_calls)
                if signal:
                    break
                time.sleep(_POLL_SECONDS)
            seconds = round(time.monotonic() - fault_started, 3)
        finally:
            second.close()

        facts = {
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
            "signal": signal,
            "seconds": seconds,
            "second_generation": second_generation,
            "observed_generation": observed_generation,
            "hook_registered": hook_registered,
            "hook_fired": bool(hook_calls),
        }
        if signal:
            return CaseResult(CASE_ID, "PASS", "", facts)

        native = _native_of(client)
        facts["A_connected"] = getattr(native, "_connected", None)
        facts["A_readonly_ready"] = getattr(native, "is_read_only_ready", None)
        return CaseResult(CASE_ID, "BLOCKED", "forced_logout_not_observed", facts)
