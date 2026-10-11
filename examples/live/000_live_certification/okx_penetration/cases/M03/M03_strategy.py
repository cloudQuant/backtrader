"""M03 — recovery to a working credential context (read-only).

The observed fault is the M02-style credential-level auth loss: a second
client built by the same factory with a tampered passphrase is rejected with
an API error code.  Recovery is then the healthy session's own credentials
reading the account again: account configuration plus balance.  No order is
ever submitted.
"""

from __future__ import annotations

from certlib import make_client
from certlib.context import CaseResult
from certlib.envfile import load_env
from certlib.okx_client import OkxApiError

CASE_ID = "M03"
RISK = "READ"


def _env_values(ctx):
    """Reuse the runner's env if attached; otherwise reload by name."""
    env = getattr(ctx, "_env_values", None)
    if env:
        return dict(env), []
    creds = ctx.config.get("credentials", {})
    names = [creds.get("api_key_env"), creds.get("secret_env"), creds.get("passphrase_env")]
    return load_env([name for name in names if name])


class M03Strategy:
    def run(self, ctx):
        client = ctx.client
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
        try:
            bad.connect()
        except OkxApiError as exc:
            broken_code = str(exc.code) if exc.code is not None else None
        except Exception:
            broken_code = None
        else:
            broken_code = None
        if broken_code is None:
            return CaseResult(
                CASE_ID, "FAIL", "auth_loss_not_observed",
                {"broken_call_count": len(bad.calls)},
            )

        config = client.account_config()
        balance = client.balance()
        facts = {
            "signal": "recovered_session",
            "observed_auth_loss": True,
            "broken_code": broken_code,
            "recovered_session": True,
            "pos_mode": client.pos_mode,
            "acct_lv": config.get("acctLv"),
            "balance_rows": len(balance),
            "time_offset_ms": client.time_offset_ms,
        }
        if not balance:
            return CaseResult(CASE_ID, "FAIL", "recovered_balance_empty", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
