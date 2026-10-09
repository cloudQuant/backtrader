"""EM01 — operator permission restriction probe (evidence-based outcome).

The certification operator (recorded operator/authorization refs) attempts one
top-level operation the demo key is not expected to be allowed to perform:
toggling the account position mode through the signed
``POST /fapi/v1/positionSide/dual`` request with ``dualSidePosition=false``.

  * If the venue rejects the request (``BinanceApiError``: the -2015 /
    permission family or any code) the rejection code/message is recorded as
    the restriction evidence; hedge mode is re-read to confirm
    ``dualSidePosition is True`` (mode_unchanged) and the case PASSes with rule
    ``position_mode_restriction``.  No restore is needed.
  * If the demo key holds the permission (the observed demo behaviour: the
    toggle call succeeds) hedge mode is restored IMMEDIATELY
    (``dualSidePosition=true``), the mode is verified back to True, and the
    case returns BLOCKED (``permission_restriction_not_producible_on_demo_key``)
    with ``toggle_succeeded=True, restored=True, dual_side_position_after=True``.
    A restriction that cannot be produced is not a PASS.
  * If restoring hedge mode fails, the mode is still re-verified and the case
    returns FAIL (``mode_restore_failed``) — the account must never be
    silently left in one-way mode.

The case starts only when hedge mode is already active; otherwise it is
BLOCKED.  Facts: operator_ref, authorization_ref, code/msg (160 chars), and
the hedge-mode verification booleans.  No account aliases/UIDs are recorded.
"""

from __future__ import annotations

from certlib.binance_client import BinanceApiError, WriteOutcomeUnknown
from certlib.context import CaseResult

CASE_ID = "EM01"
RISK = "WRITE"

_PROBE_PATH = "/fapi/v1/positionSide/dual"


def _toggle(client, value):
    """Signed position-mode toggle; value is "true" or "false"."""
    return client._request("POST", _PROBE_PATH, {"dualSidePosition": value}, is_write=True)


def _hedge_mode(client):
    """True only when accountConfig reports hedge mode (dualSidePosition is True)."""
    return client.account_config().get("dualSidePosition") is True


def _restore_hedge_mode(client):
    """Toggle back to hedge mode and re-verify it; never raises."""
    out = {"restored": False, "dual_side_position_after": None}
    try:
        _toggle(client, "true")
        out["restored"] = True
    except BinanceApiError as exc:
        out["error"] = {"code": exc.code, "msg": str(exc.msg)[:160]}
    except WriteOutcomeUnknown:
        out["error"] = {"code": None, "msg": "outcome_unknown"}
    try:
        out["dual_side_position_after"] = _hedge_mode(client)
    except BinanceApiError as exc:
        out["verify_error"] = str(exc.msg)[:160]
    return out


class EM01Strategy:
    def run(self, ctx):
        scenario = ctx.scenario()
        client = ctx.client
        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em01")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em01")
        facts = {
            "rule": "position_mode_restriction",
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
            "probe_path": _PROBE_PATH,
            "probe_value": "false",
        }

        if not _hedge_mode(client):
            return CaseResult(CASE_ID, "BLOCKED", "hedge_mode_not_active", facts)

        def recover():
            """Restore + verify hedge mode; FAIL rather than leave one-way mode."""
            restore = _restore_hedge_mode(client)
            facts["restored"] = restore["restored"]
            facts["dual_side_position_after"] = restore["dual_side_position_after"]
            if restore.get("error"):
                facts["restore_error"] = restore["error"]
            if restore.get("verify_error"):
                facts["verify_error"] = restore["verify_error"]
            if not (restore["restored"] and restore["dual_side_position_after"] is True):
                return CaseResult(CASE_ID, "FAIL", "mode_restore_failed", facts)
            return CaseResult(CASE_ID, "BLOCKED",
                              "permission_restriction_not_producible_on_demo_key", facts)

        ctx.log(f"operator {operator_ref} probes the restricted position-mode toggle")
        try:
            _toggle(client, "false")
        except BinanceApiError as exc:
            facts["restriction_source"] = "venue_error"
            facts["code"] = exc.code
            facts["msg"] = str(exc.msg)[:160]
            try:
                facts["mode_unchanged"] = _hedge_mode(client)
            except BinanceApiError:
                facts["mode_unchanged"] = None
            if facts["mode_unchanged"] is True:
                return CaseResult(CASE_ID, "PASS", "", facts)
            if facts["mode_unchanged"] is None:
                return CaseResult(CASE_ID, "UNKNOWN", "mode_verification_unavailable", facts)
            # The rejection did not prevent the state change: restore at once.
            facts["toggle_succeeded"] = True
            return recover()
        except WriteOutcomeUnknown:
            try:
                facts["hedge_mode_after"] = _hedge_mode(client)
            except BinanceApiError:
                facts["hedge_mode_after"] = None
            return CaseResult(CASE_ID, "UNKNOWN", "toggle_outcome_unknown", facts)

        # The demo key performed the restricted toggle: restore hedge mode NOW.
        facts["toggle_succeeded"] = True
        ctx.log("probe accepted; restoring hedge mode (dualSidePosition=true)")
        return recover()
