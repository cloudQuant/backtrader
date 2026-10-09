"""EM03 — operator key revocation observed, with recovery on a new context.

The certification operator (recorded operator/authorization refs) is modelled
by revoking the session's credential: a client built from the same API key with
a revoked secret must fail its session connect (auth/signature rejected,
recorded code).  While the healthy client keeps reading, a NEW credential
context (a fresh client built from the configured .env values) must connect and
read again — the recovery proof.  Read-only: no order is placed.
"""

from __future__ import annotations

from certlib import envfile, make_client
from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "EM03"
RISK = "WRITE"

_DIRECT = {"transport": "direct", "execution": False, "risk": False, "monitor": False}


def _brief(exc):
    return {"error_code": str(getattr(exc, "code", None)),
            "error_message": str(getattr(exc, "msg", "") or exc)[:120]}


def _credential_names(ctx):
    creds = ctx.config.get("credentials", {})
    return [creds.get("api_key_env"), creds.get("secret_env"), creds.get("passphrase_env")]


def _load_values(ctx, tamper_secret=False):
    """Credential values by name from the .env; never printed into evidence."""
    creds = ctx.config.get("credentials", {})
    values, missing = envfile.load_env([n for n in _credential_names(ctx) if n])
    if missing:
        return None, missing
    if tamper_secret:
        values[creds["secret_env"]] = "revoked-secret"
    return values, []


class EM03Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario, policy = ctx.scenario(), ctx.config.get("policy", {})
        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
        operator_ref = str(scenario.get("operator_ref", "operator-cert-em03"))
        authorization_ref = str(scenario.get("authorization_ref", "auth-cert-em03"))
        if inst_id not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed", {"inst_id": inst_id})

        revoked_values, missing = _load_values(ctx, tamper_secret=True)
        if revoked_values is None:
            return CaseResult(CASE_ID, "BLOCKED", "credential_env_missing", {"missing": missing})
        revoked = make_client(ctx.config, revoked_values, dict(_DIRECT))
        revocation = None
        try:
            revoked.connect()
        except OkxApiError as exc:
            revocation = {"error_code": str(exc.code), "error_message": str(exc.msg)[:120],
                          "status": exc.status}
        except Exception as exc:
            revocation = {"error": type(exc).__name__}
        finally:
            revoked.close()
        if revocation is None:
            return CaseResult(CASE_ID, "FAIL", "revocation_not_observed",
                              {"operator_ref": operator_ref, "revocation": None})
        if "error_code" not in revocation or revocation["error_code"] in ("", "None"):
            return CaseResult(CASE_ID, "FAIL", "revocation_error_incomplete",
                              {"operator_ref": operator_ref, "revocation": revocation})
        ctx.log(f"revoked credential rejected ({revocation['error_code']}); "
                f"operator {operator_ref} revoked the key")

        healthy = None
        try:
            positions = client.positions(inst_id=inst_id) or []
            ticker = client.ticker(inst_id) or {}
            healthy = {"positions_rows": len(positions), "last": ticker.get("last")}
        except Exception as exc:
            healthy = {"error": type(exc).__name__}
        if "error" in healthy:
            return CaseResult(CASE_ID, "FAIL", "healthy_read_failed",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "revocation": revocation, "healthy": healthy})

        recovery = None
        fresh_values, missing = _load_values(ctx)
        if fresh_values is None:
            recovery = {"ok": False, "error": "credential_env_missing", "missing": missing}
        else:
            renewed = make_client(ctx.config, fresh_values, dict(_DIRECT))
            try:
                connect_facts = renewed.connect()
                positions = renewed.positions(inst_id=inst_id) or []
                recovery = {"ok": True, "pos_mode": connect_facts.get("pos_mode"),
                            "positions_rows": len(positions)}
            except Exception as exc:
                recovery = {"ok": False, "error": type(exc).__name__}
            finally:
                renewed.close()
            if not recovery.get("ok"):
                return CaseResult(CASE_ID, "FAIL", "recovery_read_failed",
                                  {"operator_ref": operator_ref,
                                   "authorization_ref": authorization_ref,
                                   "revocation": revocation, "healthy": healthy,
                                   "recovery": recovery})

        facts = {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                 "revocation": revocation, "healthy_after_revocation": healthy,
                 "new_context": recovery, "healthy_ok": True}
        return CaseResult(CASE_ID, "PASS", "", facts)
