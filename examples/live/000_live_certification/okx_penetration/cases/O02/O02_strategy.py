"""O02 — resting reduce order: accepted live, finally canceled, then flushed.

PASS: the crossing MARKET BUY opens a long position, the SELL LIMIT reduce
(order at last*(1+bps), posSide long, sz = position) is accepted into the book
and observable, a bounded cancel drives it to terminal canceled, and a MARKET
SELL then flushes whatever position remains back to flat.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "O02"
RISK = "DANGEROUS"

_LIVE = {"live", "partially_filled"}
_TERMINAL = {"canceled", "filled"}


def _round_to_step(value, step):
    return round(round(float(value) / float(step)) * float(step), 10)


def _brief(exc):
    return {"error_code": str(getattr(exc, "code", None)), "error_message": str(getattr(exc, "msg", "") or exc)[:120]}


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
    except Exception as exc:
        return None, {"rejected": _brief(exc)} if isinstance(exc, OkxApiError) else {"error": type(exc).__name__}
    ord_id = placement["ordId"]
    ctx.track_order(inst_id, ord_id, placement.get("_cl_ord_id"))
    try:
        row, ok = _poll_state(client, inst_id, ord_id, {"filled"}, timeout)
    except Exception as exc:
        return None, {"ordId": ord_id, "error": type(exc).__name__}
    if ok:
        ctx.mark_order_closed(ord_id)
    return {"ordId": ord_id, "state": str(row.get("state")), "accFillSz": row.get("accFillSz"),
            "avgPx": row.get("avgPx")}, None


def _flatten(ctx, inst_id, size, timeout):
    """Best-effort MARKET close of a long position; never raises."""
    if float(size) <= 0:
        return {"skipped": "zero_volume"}
    row, error = _market(ctx, inst_id, "sell", size, timeout)
    return error if error is not None else {"ordId": row["ordId"], "state": row["state"],
                                            "accFillSz": row.get("accFillSz")}


def _flush_position(ctx, inst_id, timeout):
    """Flatten the currently open long position (if any); never raises."""
    try:
        size, rows = _positions(ctx.client, inst_id)
    except Exception as exc:
        return {"error": type(exc).__name__}
    return _flatten(ctx, inst_id, size, timeout) if rows else {"skipped": "no_position"}


def _close(ctx, inst_id, ord_id, timeout):
    """Bounded cancel of one order; never raises; returns its final observation."""
    client = ctx.client
    entry = {"ordId": ord_id}
    try:
        rows = client.order_details(inst_id, ord_id=ord_id)
        row = rows[0] if rows else {}
        entry["state"] = str(row.get("state"))
    except Exception as exc:
        entry.update({"state": "unverified", "details_error": type(exc).__name__})
        return entry
    if entry["state"] in _LIVE:
        try:
            client.cancel_order(inst_id, ord_id=ord_id)
        except Exception as exc:
            entry["cancel"] = _brief(exc) if isinstance(exc, OkxApiError) else {"error": type(exc).__name__}
        try:
            final, ok = _poll_state(client, inst_id, ord_id, _TERMINAL, timeout)
            entry["final_state"] = str(final.get("state"))
            done = ok and entry["final_state"] in _TERMINAL
        except Exception as exc:
            entry["poll_error"] = type(exc).__name__
            done = False
    else:
        done = entry["state"] in _TERMINAL
    if done:
        ctx.mark_order_closed(ord_id)
    return entry


class O02Strategy:
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
        tick = float(instruments[0].get("tickSz") or 0.01)
        lot = float(instruments[0].get("lotSz") or 0.01)
        size = _round_to_step(float(scenario.get("size", 1)), lot)
        offset = float(scenario.get("reduce_offset_bps", 200)) / 10_000.0
        fill_timeout = float(scenario.get("fill_timeout_ms", 15000)) / 1000.0
        accept_timeout = float(scenario.get("accept_timeout_ms", 10000)) / 1000.0
        cancel_timeout = float(scenario.get("cancel_timeout_ms", 10000)) / 1000.0

        position_before, before_rows = _positions(client, inst_id)
        if before_rows:
            return CaseResult(CASE_ID, "BLOCKED", "existing_position_present",
                              {"position_rows": before_rows})
        ctx.log(f"flat account; crossing MARKET BUY open {size} {inst_id}")

        opened, open_error = _market(ctx, inst_id, "buy", size, fill_timeout)
        if open_error is not None:
            return CaseResult(CASE_ID, "FAIL", "open_rejected", {"open": open_error})
        if opened["state"] != "filled":
            return CaseResult(CASE_ID, "FAIL", "open_not_filled",
                              {"open": opened, "flush": _flush_position(ctx, inst_id, fill_timeout)})

        long_now, after_open_rows = _positions(client, inst_id)
        if not after_open_rows or long_now <= 0:
            return CaseResult(CASE_ID, "FAIL", "position_not_reflected",
                              {"open": opened, "position_after_open": long_now,
                               "position_rows": after_open_rows,
                               "flush": _flush_position(ctx, inst_id, fill_timeout)})

        last = float(client.ticker(inst_id)["last"])
        rest_px = _round_to_step(last * (1.0 + offset), tick)
        ctx.log(f"resting reduce SELL {long_now}@{rest_px} (posSide long) over market {last}")
        try:
            reducing = client.place_order(inst_id, "sell", sz=long_now, px=rest_px,
                                          ord_type="limit", pos_side="long")
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "reduce_rejected",
                              {"open": opened, "position_after_open": long_now, "error": _brief(exc),
                               "flush": _flush_position(ctx, inst_id, fill_timeout)})
        reduce_id = reducing["ordId"]
        ctx.track_order(inst_id, reduce_id, reducing.get("_cl_ord_id"))

        reduce_facts = {"ordId": reduce_id, "clOrdId": reducing.get("_cl_ord_id"),
                        "px": rest_px, "last": last, "sz": long_now}
        row, live = _poll_state(client, inst_id, reduce_id, _LIVE, accept_timeout)
        reduce_facts["state"] = str(row.get("state"))
        if not live:
            cancel = ({"ordId": reduce_id, "state": reduce_facts["state"], "skipped": "terminal"}
                      if reduce_facts["state"] in _TERMINAL else _close(ctx, inst_id, reduce_id, cancel_timeout))
            if reduce_facts["state"] in _TERMINAL:
                ctx.mark_order_closed(reduce_id)
            return CaseResult(CASE_ID, "FAIL", "reduce_not_live", {
                "open": opened, "position_after_open": long_now, "reduce": reduce_facts,
                "cancel": cancel, "flush": _flush_position(ctx, inst_id, fill_timeout)})
        ctx.log(f"reduce ordId={reduce_id} observable ({reduce_facts['state']}); canceling")

        try:
            client.cancel_order(inst_id, ord_id=reduce_id)
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "reduce_cancel_rejected", {
                "open": opened, "position_after_open": long_now,
                "reduce": {**reduce_facts, "cancel": _brief(exc)},
                "cleanup": _close(ctx, inst_id, reduce_id, cancel_timeout),
                "flush": _flush_position(ctx, inst_id, fill_timeout)})
        final, canceled = _poll_state(client, inst_id, reduce_id, _TERMINAL, cancel_timeout)
        reduce_facts["final_state"] = str(final.get("state"))
        reduce_facts["accFillSz"] = final.get("accFillSz")
        if not canceled or reduce_facts["final_state"] != "canceled":
            if reduce_facts["final_state"] in _TERMINAL:
                ctx.mark_order_closed(reduce_id)
            return CaseResult(CASE_ID, "FAIL", "reduce_cancel_unconfirmed", {
                "open": opened, "position_after_open": long_now, "reduce": reduce_facts,
                "cleanup": _close(ctx, inst_id, reduce_id, cancel_timeout),
                "flush": _flush_position(ctx, inst_id, fill_timeout)})
        ctx.mark_order_closed(reduce_id)

        remain, remain_rows = _positions(client, inst_id)
        flush = _flatten(ctx, inst_id, remain, fill_timeout) if remain_rows else {"skipped": "no_position"}
        position_after, after_rows = _positions(client, inst_id)
        facts = {"open": opened, "position_after_open": long_now, "reduce": reduce_facts, "flush": flush,
                 "position_before": position_before, "position_after": position_after, "position_rows": after_rows}
        flushed = flush.get("state") == "filled" or flush.get("skipped") == "no_position"
        if not flushed or after_rows:
            return CaseResult(CASE_ID, "FAIL", "flush_incomplete", facts)
        return CaseResult(CASE_ID, "PASS", "", {**facts, "flat": True})
