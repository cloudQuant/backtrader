"""EM03 — forced logout via the user-data-stream listenKey (session-only).

The certification operator (recorded operator/authorization refs) performs a
server-side forced logout of the observed session: the session starts a
listenKey, the operator deletes that listenKey at the venue
(``DELETE /fapi/v1/listenKey``), and the session's next renew
(``PUT /fapi/v1/listenKey``) MUST fail because the key no longer exists
(forced logout observed, usually code -1125).  Recovery then starts a fresh
listenKey, proves one renew works, and deletes it at the end so no session
residual remains.

PASS = renew failed after the operator delete + recovery key worked.
Facts carry operator/authorization refs, the renew error code/msg, and
recovery booleans; listenKeys are recorded only as short SHA-256 digests —
no raw keys, account aliases or UIDs.
"""

from __future__ import annotations

import hashlib

from certlib.binance_client import BinanceApiError, WriteOutcomeUnknown
from certlib.context import CaseResult

CASE_ID = "EM03"
RISK = "WRITE"


def _digest12(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _renew(client):
    """One renew; returns (error_dict, unknown) — error_dict None when accepted."""
    try:
        client.listen_key_renew()
        return None, False
    except BinanceApiError as exc:
        return {"code": exc.code, "msg": str(exc.msg)[:160]}, False
    except WriteOutcomeUnknown:
        return None, True


class EM03Strategy:
    def run(self, ctx):
        scenario = ctx.scenario()
        client = ctx.client
        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em03")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em03")
        facts = {
            "rule": "forced_logout_via_listenkey_delete",
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
        }

        # ---- observed session starts its listenKey ----
        try:
            started = client.listen_key_start()
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "BLOCKED", "listen_key_start_failed",
                              {**facts, "code": exc.code, "msg": str(exc.msg)[:160]})
        except WriteOutcomeUnknown:
            return CaseResult(CASE_ID, "UNKNOWN", "start_outcome_unknown", facts)
        key = started.get("listenKey")
        if not key:
            return CaseResult(CASE_ID, "FAIL", "listen_key_missing", facts)
        facts["initial_key_digest_12"] = _digest12(key)

        # ---- operator performs the server-side forced logout ----
        ctx.log(f"listenKey {facts['initial_key_digest_12']} started; "
                f"operator {operator_ref} deletes it server-side")
        try:
            client.listen_key_delete()
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "listen_key_delete_rejected",
                              {**facts, "code": exc.code, "msg": str(exc.msg)[:160]})
        except WriteOutcomeUnknown:
            return CaseResult(CASE_ID, "UNKNOWN", "delete_outcome_unknown", facts)
        facts["delete_ok"] = True

        # ---- the observed session must now be logged out: renew fails ----
        renew_error, unknown = _renew(client)
        if unknown:
            return CaseResult(CASE_ID, "UNKNOWN", "renew_outcome_unknown", facts)
        if renew_error is None:
            return CaseResult(CASE_ID, "FAIL", "forced_logout_not_observed", facts)
        facts["renew_error"] = renew_error
        ctx.log(f"renew after delete rejected code={renew_error['code']} (forced logout observed)")

        # ---- recovery: new key, one working renew, then delete it ----
        try:
            recovery = client.listen_key_start()
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "recovery_key_start_failed",
                              {**facts, "recovery_code": exc.code})
        except WriteOutcomeUnknown:
            return CaseResult(CASE_ID, "UNKNOWN", "recovery_start_outcome_unknown", facts)
        new_key = recovery.get("listenKey")
        if not new_key:
            return CaseResult(CASE_ID, "FAIL", "recovery_key_missing", facts)
        facts["recovery_key_digest_12"] = _digest12(new_key)

        recovery_error, unknown = _renew(client)
        if unknown:
            return CaseResult(CASE_ID, "UNKNOWN", "recovery_renew_outcome_unknown", facts)
        if recovery_error is not None:
            return CaseResult(CASE_ID, "FAIL", "recovery_renew_failed",
                              {**facts, "recovery_code": recovery_error["code"],
                               "recovery_msg": recovery_error["msg"]})
        facts["recovery_renew_ok"] = True

        recovery_deleted = False
        try:
            client.listen_key_delete()
            recovery_deleted = True
        except BinanceApiError as exc:
            facts["cleanup_error"] = f"code={exc.code}"
        except WriteOutcomeUnknown:
            facts["cleanup_error"] = "outcome_unknown"
        facts["recovery_key_deleted"] = recovery_deleted
        return CaseResult(CASE_ID, "PASS", "", facts)
