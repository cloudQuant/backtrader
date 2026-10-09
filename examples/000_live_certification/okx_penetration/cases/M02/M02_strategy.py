"""M02 — observed session auth loss (read-only).

OKX REST is stateless: there is no persistent socket an operator could
disconnect.  The honest, bounded interruption for this case is therefore
credential-level auth loss: a second client built by the same factory with a
deliberately tampered passphrase must be rejected by the venue (signed request
refused with an API error code), while the healthy session's own credential
context still reads.  No order is ever submitted.
"""

from __future__ import annotations

from certlib import make_client
from certlib.context import CaseResult
from certlib.envfile import load_env
from certlib.monitor import Monitor
from certlib.okx_client import OkxApiError

CASE_ID = "M02"
RISK = "READ"


def _env_values(ctx):
    """Reuse the runner's env if attached; otherwise reload by name."""
    env = getattr(ctx, "_env_values", None)
    if env:
        return dict(env), []
    creds = ctx.config.get("credentials", {})
    names = [creds.get("api_key_env"), creds.get("secret_env"), creds.get("passphrase_env")]
    return load_env([name for name in names if name])


class M02Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        operator_ref = str(scenario.get("operator_ref", "operator-cert-m02"))
        authorization_ref = str(scenario.get("authorization_ref", "auth-cert-m02"))

        passphrase_env = ctx.config.get("credentials", {}).get("passphrase_env")
        values, missing = _env_values(ctx)
        if not passphrase_env or missing:
            return CaseResult(
                CASE_ID, "BLOCKED", "credential_env_missing", {"missing": sorted(missing)}
            )
        tampered = dict(values)
        tampered[passphrase_env] = "invalid-passphrase"

        bad = make_client(ctx.config, tampered, ctx.topology)
        broken_code = None
        broken_msg = ""
        signal = ""
        try:
            bad.connect()
        except OkxApiError as exc:
            broken_code = str(exc.code) if exc.code is not None else None
            broken_msg = str(exc.msg)[:120]
            signal = "auth_rejected" if broken_code is not None else ""
        except Exception as exc:
            broken_msg = f"{type(exc).__name__}: {exc}"[:120]

        healthy_ok = True
        healthy_reason = ""
        try:
            client.account_config()
        except Exception as exc:
            healthy_ok = False
            healthy_reason = f"{type(exc).__name__}"

        monitor = Monitor({})
        monitor.record(
            "disconnect_observed",
            auth_loss=signal == "auth_rejected",
            broken_code=broken_code or "",
            operator_ref=operator_ref,
        )
        ctx.record_artifact("monitor", monitor.dump())

        facts = {
            "signal": signal,
            "broken_code": broken_code,
            "broken_msg": broken_msg,
            "broken_call_count": len(bad.calls),
            "healthy_ok": healthy_ok,
            "healthy_reason": healthy_reason,
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
            "monitor_event_kinds": [entry.get("kind") for entry in monitor.events],
        }
        if signal != "auth_rejected":
            return CaseResult(CASE_ID, "FAIL", "auth_loss_not_observed", facts)
        if not healthy_ok:
            return CaseResult(CASE_ID, "FAIL", "healthy_session_lost", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
