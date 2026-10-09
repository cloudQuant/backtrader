"""EM03 — external operator forced logout on the runner session (read-only).

Like M02: the recorded operator (operator/authorization refs) performs a
competing login on the same account through a second session.  The observed
session A must show a native disconnect within the bounded window; the case
records which signal fired and how long it took.  No write action is used.
"""

from __future__ import annotations

import time

from certlib import make_client
from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "EM03"
RISK = "READ"

_POLL_SECONDS = 0.5


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


class EM03Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em03")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em03")
        timeout = int(scenario.get("disconnect_timeout_ms", 20000)) / 1000.0
        observed_generation = int(client.login_facts.get("connection_generation", 0) or 0)

        hook_calls = []
        hook_registered = _register_disconnect_hook(client, hook_calls)

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
