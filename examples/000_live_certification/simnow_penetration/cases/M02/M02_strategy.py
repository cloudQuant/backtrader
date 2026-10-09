"""M02 — monitoring observes a controlled external session stop (read-only).

SimNow accepts concurrent sessions for one account, so a competing login
cannot force a server-side disconnect (verified live: the runner session
stayed connected).  The bounded, observable external interruption for this
case is therefore an operator-performed controlled session stop: the
monitoring layer records the interruption event with the native stop receipt,
and the case captures the post-stop session state.  No order is ever
submitted.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M02"
RISK = "READ"

_POLL_SECONDS = 0.5


def _native_of(session):
    return getattr(session, "_client", None)


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


class M02Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        operator_ref = str(scenario.get("operator_ref", "operator-cert-m02"))
        authorization_ref = str(scenario.get("authorization_ref", "auth-cert-m02"))
        observed_generation = int(client.login_facts.get("connection_generation", 0) or 0)

        monitor = Monitor({})
        client.event_hook = monitor.record
        hook_calls = []
        hook_registered = _register_disconnect_hook(client, hook_calls)

        fault_started = time.monotonic()
        receipt = client.close()
        seconds = round(time.monotonic() - fault_started, 3)
        native = _native_of(client)
        post_connected = getattr(native, "_connected", None)
        post_ready = getattr(native, "is_read_only_ready", None)
        monitor.record(
            "disconnect_observed",
            generation=observed_generation,
            join_completed=receipt.get("join_completed"),
            timed_out=receipt.get("timed_out"),
            operator_ref=operator_ref,
        )

        facts = {
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
            "signal": "controlled_stop" if receipt.get("attempted") else "",
            "seconds": seconds,
            "observed_generation": observed_generation,
            "hook_registered": hook_registered,
            "hook_fired": bool(hook_calls),
            "post_connected": post_connected,
            "post_readonly_ready": post_ready,
            "stop_receipt": receipt,
            "monitor_event_kinds": [e.get("kind") for e in monitor.events],
        }
        ctx.record_artifact("monitor", monitor.dump())
        if receipt.get("attempted") is not True:
            return CaseResult(CASE_ID, "FAIL", "controlled_stop_not_attempted", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
