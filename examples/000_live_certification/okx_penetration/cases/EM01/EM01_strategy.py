"""EM01 — operator credential restriction is enforced, then restored.

The certification operator (recorded operator/authorization refs) is modelled
by a second client built from the same API key with a tampered secret: the
restricted client must be refused by the venue (signature-invalid family,
50113).  The healthy client then completes a bounded resting order cycle
(place -> live -> cancel -> canceled, no residual) as the restoration proof.
The restriction and the restoration use the client's own credential path; no
instrument-permission guessing is involved.
"""

from __future__ import annotations

import time

from certlib import envfile, make_client
from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "EM01"
RISK = "WRITE"

_LIVE = {"live", "partially_filled"}
_TERMINAL = {"canceled", "filled"}
_DIRECT = {"transport": "direct", "execution": False, "risk": False, "monitor": False}


def _round_to_step(value, step):
    step = float(step)
    return round(round(float(value) / step) * step, 10)


def _brief(exc):
    return {"error_code": str(getattr(exc, "code", None)),
            "error_message": str(getattr(exc, "msg", "") or exc)[:120]}


def _poll_state(client, inst_id, ord_id, states, timeout):
    deadline, row = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        rows = client.order_details(inst_id, ord_id=ord_id)
        row = rows[0] if rows else {}
        if str(row.get("state")) in states:
            return row, True
        time.sleep(0.3)
    return row, False


def _restricted_client(ctx):
    """Second client from the same .env values with the secret tampered."""
    creds = ctx.config.get("credentials", {})
    names = [creds.get("api_key_env"), creds.get("secret_env"), creds.get("passphrase_env")]
    values, missing = envfile.load_env([n for n in names if n])
    if missing:
        return None, missing
    values[creds["secret_env"]] = "invalid-secret"
    return make_client(ctx.config, values, dict(_DIRECT)), []


class EM01Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario, policy = ctx.scenario(), ctx.config.get("policy", {})
        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
        operator_ref = str(scenario.get("operator_ref", "operator-cert-em01"))
        authorization_ref = str(scenario.get("authorization_ref", "auth-cert-em01"))
        if inst_id not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed", {"inst_id": inst_id})
        instruments = client.instruments(inst_id)
        if not instruments:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_unknown", {"inst_id": inst_id})
        tick = float(instruments[0].get("tickSz") or 0.01)
        size = _round_to_step(float(scenario.get("size", 1)),
                              float(instruments[0].get("lotSz") or 0.01))
        offset = float(scenario.get("price_offset_bps", 200)) / 10_000.0
        accept_timeout = float(scenario.get("accept_timeout_ms", 10000)) / 1000.0
        cancel_timeout = float(scenario.get("cancel_timeout_ms", 10000)) / 1000.0

        restricted, missing = _restricted_client(ctx)
        if restricted is None:
            return CaseResult(CASE_ID, "BLOCKED", "credential_env_missing", {"missing": missing})
        restricted.time_offset_ms = getattr(client, "time_offset_ms", 0)  # reuse the measured clock offset
        restriction = None
        try:
            restricted.account_config()
        except OkxApiError as exc:
            restriction = {"error_code": str(exc.code), "error_message": str(exc.msg)[:120],
                           "status": exc.status}
        except Exception as exc:
            restriction = {"error": type(exc).__name__}
        finally:
            restricted.close()
        if restriction is None:
            return CaseResult(CASE_ID, "FAIL", "restriction_not_enforced",
                              {"operator_ref": operator_ref, "restriction": None})
        if "error_code" not in restriction or restriction["error_code"] in ("", "None"):
            return CaseResult(CASE_ID, "FAIL", "restriction_error_incomplete",
                              {"operator_ref": operator_ref, "restriction": restriction})
        ctx.log(f"restricted credential refused ({restriction['error_code']}); "
                f"operator {operator_ref} restores access")

        last = float(client.ticker(inst_id)["last"])
        px = _round_to_step(last * (1.0 - offset), tick)
        baseline = client.pending_orders(inst_id=inst_id) or []
        try:
            placement = client.place_order(inst_id, "buy", sz=size, px=px,
                                           ord_type="limit", pos_side="long")
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "restoration_rejected",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "restriction": restriction, "error": _brief(exc)})
        ord_id = placement["ordId"]
        ctx.track_order(inst_id, ord_id, placement.get("_cl_ord_id"))
        row, live = _poll_state(client, inst_id, ord_id, _LIVE, accept_timeout)
        restoration = {"ordId": ord_id, "clOrdId": placement.get("_cl_ord_id"), "px": px,
                       "state": str(row.get("state")), "baseline_pending": len(baseline)}
        if not live:
            return CaseResult(CASE_ID, "FAIL", "restoration_not_live",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "restriction": restriction, "restoration": restoration})

        try:
            client.cancel_order(inst_id, ord_id=ord_id)
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "restoration_cancel_rejected",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "restriction": restriction,
                               "restoration": {**restoration, "cancel": _brief(exc)}})
        final, canceled = _poll_state(client, inst_id, ord_id, _TERMINAL, cancel_timeout)
        restoration["final_state"] = str(final.get("state"))
        if not canceled or restoration["final_state"] != "canceled":
            if restoration["final_state"] in _TERMINAL:
                ctx.mark_order_closed(ord_id)
            return CaseResult(CASE_ID, "FAIL", "restoration_cancel_unconfirmed",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "restriction": restriction, "restoration": restoration})
        ctx.mark_order_closed(ord_id)

        pending = client.pending_orders(inst_id=inst_id) or []
        residual = [{"ordId": o.get("ordId")} for o in pending if str(o.get("ordId")) == str(ord_id)]
        facts = {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                 "restriction": restriction, "restoration": restoration,
                 "residual": residual, "final_pending": len(pending)}
        if residual:
            return CaseResult(CASE_ID, "FAIL", "residual_order_open", facts)
        return CaseResult(CASE_ID, "PASS", "", {**facts, "restored": True})
