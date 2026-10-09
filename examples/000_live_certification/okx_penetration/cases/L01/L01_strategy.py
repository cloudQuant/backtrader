"""L01 — fill correlation: crossing MARKET open matched in the venue trade log.

PASS: the crossing MARKET BUY fills, the venue order history shows a row for
our ordId (fill price/size/fee recorded), a crossing MARKET SELL flattens the
position, and the position query is back at its starting (zero) level.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "L01"
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
    return {"ordId": ord_id, "clOrdId": placement.get("_cl_ord_id"),
            "state": str(row.get("state")), "accFillSz": row.get("accFillSz"),
            "avgPx": row.get("avgPx"), "fillPx": row.get("fillPx"), "fee": row.get("fee")}, None


class L01Strategy:
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
        history_timeout = float(scenario.get("history_timeout_ms", 20000)) / 1000.0

        position_before, before_rows = _positions(client, inst_id)
        if before_rows:
            return CaseResult(CASE_ID, "BLOCKED", "existing_position_present",
                              {"position_rows": before_rows})
        ctx.log(f"flat account; crossing MARKET BUY {size} {inst_id}")

        opened, open_error = _market(ctx, inst_id, "buy", size, fill_timeout)
        if open_error is not None:
            return CaseResult(CASE_ID, "FAIL", "open_rejected", {"open": open_error})
        if opened["state"] != "filled":
            position_now, _rows = _positions(client, inst_id)
            closed, close_error = (_market(ctx, inst_id, "sell", position_now, fill_timeout)
                                   if abs(position_now) > 1e-9 else (None, {"skipped": "no_position"}))
            return CaseResult(CASE_ID, "FAIL", "open_not_filled",
                              {"open": opened, "close": closed or close_error})

        matched, history_error = None, None
        deadline = time.monotonic() + history_timeout
        try:
            while time.monotonic() < deadline:
                rows = client.orders_history(limit=20)
                matched = next((r for r in rows if str(r.get("ordId")) == str(opened["ordId"])), None)
                if matched:
                    break
                time.sleep(0.5)
        except Exception as exc:
            history_error = type(exc).__name__
        history = None
        if matched is not None:
            history = {k: matched.get(k) for k in
                       ("ordId", "state", "fillPx", "fillSz", "avgPx", "fee", "fillTime")
                       if matched.get(k) is not None}

        closed, close_error = _market(ctx, inst_id, "sell", size, fill_timeout)
        position_after, after_rows = _positions(client, inst_id)
        facts = {"open": opened, "history": history, "close": closed or close_error,
                 "history_error": history_error, "position_before": position_before,
                 "position_after": position_after, "position_rows": after_rows}
        if history is None:
            return CaseResult(CASE_ID, "FAIL", "trade_not_found", facts)
        if close_error is not None or (closed or {}).get("state") != "filled":
            return CaseResult(CASE_ID, "FAIL", "close_not_filled", facts)
        if after_rows:
            return CaseResult(CASE_ID, "FAIL", "position_not_flat", facts)
        return CaseResult(CASE_ID, "PASS", "", {**facts, "flat": True})
