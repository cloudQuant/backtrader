"""T02 — open-then-close with real MARKET fills on the position track.

PASS: the crossing MARKET BUY opens a long position that is visible on the
position query, the MARKET SELL (posSide long) closes it with a filled state,
and the final position query shows the position back at its starting (zero)
level.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "T02"
RISK = "WRITE"

_LIVE = {"live", "partially_filled"}


def _round_to_step(value, step):
    step = float(step)
    return round(round(float(value) / step) * step, 10)


def _brief(exc):
    return {"error_code": str(getattr(exc, "code", None)),
            "error_message": str(getattr(exc, "msg", "") or exc)[:120]}


def _positions(client, inst_id):
    """(signed total in contracts, non-zero rows); long pos>0 in long_short mode."""
    rows = client.positions(inst_id=inst_id) or []
    total, nonzero = 0.0, []
    for row in rows:
        try:
            pos = float(row.get("pos") or 0)
        except (TypeError, ValueError):
            continue
        total += pos
        if abs(pos) > 1e-9:
            nonzero.append({"posSide": row.get("posSide"), "pos": row.get("pos")})
    return total, nonzero


def _poll_state(client, inst_id, ord_id, states, timeout):
    deadline, row = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        rows = client.order_details(inst_id, ord_id=ord_id)
        row = rows[0] if rows else {}
        if str(row.get("state")) in states:
            return row, True
        time.sleep(0.3)
    return row, False


def _market(ctx, inst_id, side, size, timeout):
    """Place a MARKET order (posSide long), track it, wait for filled. Never raises."""
    client = ctx.client
    try:
        placement = client.place_order(inst_id, side, sz=size, ord_type="market", pos_side="long")
    except OkxApiError as exc:
        return None, {"rejected": _brief(exc)}
    except Exception as exc:
        return None, {"error": type(exc).__name__}
    ord_id = placement["ordId"]
    ctx.track_order(inst_id, ord_id, placement.get("_cl_ord_id"))
    try:
        row, ok = _poll_state(client, inst_id, ord_id, {"filled"}, timeout)
    except Exception as exc:
        return None, {"ordId": ord_id, "error": type(exc).__name__}
    if ok:
        ctx.mark_order_closed(ord_id)
    return {"ordId": ord_id, "state": str(row.get("state")), "accFillSz": row.get("accFillSz"),
            "avgPx": row.get("avgPx"), "fee": row.get("fee")}, None


def _flatten(ctx, inst_id, size, timeout):
    """Best-effort MARKET close of a long position; never raises."""
    if float(size) <= 0:
        return {"skipped": "zero_volume"}
    row, error = _market(ctx, inst_id, "sell", size, timeout)
    return error if error is not None else {"ordId": row["ordId"], "state": row["state"],
                                            "accFillSz": row.get("accFillSz")}


class T02Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario, policy = ctx.scenario(), ctx.config.get("policy", {})
        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
        if inst_id not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed", {"inst_id": inst_id})
        instruments = client.instruments(inst_id)
        if not instruments:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_unknown", {"inst_id": inst_id})
        lot = float(instruments[0].get("lotSz") or 0.01)
        size = _round_to_step(float(scenario.get("size", 1)), lot)
        fill_timeout = float(scenario.get("fill_timeout_ms", 15000)) / 1000.0

        position_before, before_rows = _positions(client, inst_id)
        if before_rows:
            return CaseResult(CASE_ID, "BLOCKED", "existing_position_present",
                              {"position_rows": before_rows})
        ctx.log(f"flat account; crossing MARKET BUY open {size} {inst_id}")

        opened, open_error = _market(ctx, inst_id, "buy", size, fill_timeout)
        if open_error is not None:
            return CaseResult(CASE_ID, "FAIL", "open_rejected", {"open": open_error})
        if opened["state"] != "filled":
            position_now, rows_now = _positions(client, inst_id)
            flatten = (_flatten(ctx, inst_id, position_now, fill_timeout) if rows_now
                       else {"skipped": "no_position"})
            return CaseResult(CASE_ID, "FAIL", "open_not_filled",
                              {"open": opened, "flatten": flatten})

        long_now, after_open_rows = _positions(client, inst_id)
        if not after_open_rows or long_now <= 0:
            return CaseResult(CASE_ID, "FAIL", "position_not_reflected",
                              {"open": opened, "position_after_open": long_now,
                               "position_rows": after_open_rows,
                               "flatten": _flatten(ctx, inst_id, long_now, fill_timeout)})

        ctx.log(f"long position {long_now} observed; crossing MARKET SELL close {size}")
        closed, close_error = _market(ctx, inst_id, "sell", size, fill_timeout)
        position_after, after_rows = _positions(client, inst_id)
        facts = {"open": opened, "position_after_open": long_now,
                 "close": closed or close_error, "position_before": position_before,
                 "position_after": position_after, "position_rows": after_rows}
        if close_error is not None or (closed or {}).get("state") != "filled":
            if after_rows:
                facts["flatten_retry"] = _flatten(ctx, inst_id, position_after, fill_timeout)
            return CaseResult(CASE_ID, "FAIL", "close_not_filled", facts)
        if after_rows:
            facts["flatten_retry"] = _flatten(ctx, inst_id, position_after, fill_timeout)
            return CaseResult(CASE_ID, "FAIL", "position_not_flat", facts)
        return CaseResult(CASE_ID, "PASS", "", {**facts, "flat": True})
