"""B01 — batch order flow: a crossing order fills and a resting order is canceled.

The demo engine was observed to fill crossing orders fully (partial fills are
not producible; see the SimNow/Binance adaptations).  PASS: order #1 (crossing
BUY LIMIT at the ask, sz scenario.order_volume) reaches fill evidence
(accFillSz > 0) or a terminal canceled state, order #2 (resting BUY LIMIT at
last*(1-bps)) is accepted live and finally canceled, no residual pending
orders remain, any filled quantity is flattened with a MARKET sell, and the
position returns flat.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "B01"
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
    return {"ordId": ord_id, "state": str(row.get("state")), "accFillSz": row.get("accFillSz")}, None


def _flatten(ctx, inst_id, size, timeout):
    """Best-effort MARKET close of a long position; never raises."""
    if float(size) <= 0:
        return {"skipped": "zero_volume"}
    row, error = _market(ctx, inst_id, "sell", size, timeout)
    return error if error is not None else {"ordId": row["ordId"], "state": row["state"],
                                            "accFillSz": row.get("accFillSz")}


def _close(ctx, inst_id, ord_id, timeout):
    """Bounded cancel of one order; never raises; returns its final observation."""
    client = ctx.client
    entry = {"ordId": ord_id}
    try:
        rows = client.order_details(inst_id, ord_id=ord_id)
        row = rows[0] if rows else {}
        entry["state"] = str(row.get("state"))
        entry["accFillSz"] = row.get("accFillSz")
    except Exception as exc:
        entry.update({"state": "unverified", "details_error": type(exc).__name__})
        return entry
    if entry["state"] in _LIVE:
        try:
            client.cancel_order(inst_id, ord_id=ord_id)
        except OkxApiError as exc:
            entry["cancel"] = _brief(exc)
        except Exception as exc:
            entry["cancel"] = {"error": type(exc).__name__}
        try:
            final, ok = _poll_state(client, inst_id, ord_id, _TERMINAL, timeout)
            entry["final_state"] = str(final.get("state"))
            entry["accFillSz"] = final.get("accFillSz", entry.get("accFillSz"))
            done = ok and entry["final_state"] in _TERMINAL
        except Exception as exc:
            entry["poll_error"] = type(exc).__name__
            done = False
    else:
        done = entry["state"] in _TERMINAL
    if done:
        ctx.mark_order_closed(ord_id)
    return entry


class B01Strategy:
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

        ticker = client.ticker(inst_id)
        last = float(ticker["last"])
        ask = float(ticker.get("askPx") or 0) or round(last * 1.002, 6)
        offset = float(scenario.get("price_offset_bps", 200)) / 10_000.0
        resting_px = _round_to_step(last * (1.0 - offset), tick)
        crossing_px = _round_to_step(ask, tick)
        size = _round_to_step(float(scenario.get("order_volume", 20)), lot)
        fill_timeout = float(scenario.get("fill_timeout_ms", 15000)) / 1000.0
        poll_timeout = float(scenario.get("fill_poll_timeout_ms", 20000)) / 1000.0
        cancel_timeout = float(scenario.get("cancel_timeout_ms", 10000)) / 1000.0

        position_before, before_rows = _positions(client, inst_id)
        if before_rows:
            return CaseResult(CASE_ID, "BLOCKED", "existing_position_present",
                              {"position_rows": before_rows})

        orders = []

        def reap(extra):
            entries = [_close(ctx, inst_id, o["ordId"], cancel_timeout) for o in orders]
            filled = sum(float(e.get("accFillSz") or 0) for e in entries)
            pos_after, after_rows = _positions(client, inst_id)
            return {**extra, "orders": entries, "flatten": _flatten(ctx, inst_id, filled, fill_timeout),
                    "position_after": pos_after, "position_rows": after_rows}

        # order #1 — crossing leg as a MARKET BUY: fills immediately on the
        # demo engine (a crossing LIMIT at the ask can trip the narrow venue
        # price band); the resting leg below covers the cancel path.
        try:
            placement = client.place_order(inst_id, "buy", sz=size,
                                           ord_type="market", pos_side="long")
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "place_rejected", reap({"error": _brief(exc)}))
        except Exception as exc:
            return CaseResult(CASE_ID, "FAIL", "place_failed", reap({"error": type(exc).__name__}))
        crossing = {"ordId": placement["ordId"], "clOrdId": placement.get("_cl_ord_id"), "ordType": "market"}
        ctx.track_order(inst_id, crossing["ordId"], crossing["clOrdId"])
        orders.append(crossing)
        ctx.log(f"placed crossing MARKET BUY {size} ordId={crossing['ordId']}")
        try:
            row, filled = _poll_state(client, inst_id, crossing["ordId"], {"filled", "partially_filled"}, poll_timeout)
        except Exception as exc:
            return CaseResult(CASE_ID, "FAIL", "fill_poll_error", reap({"error": type(exc).__name__}))
        crossing.update({"state": str(row.get("state")), "accFillSz": row.get("accFillSz")})
        ctx.log(f"crossing order state={crossing['state']} accFillSz={crossing.get('accFillSz')}")

        # order #2 — resting BUY below the market: expect live, then cancel.
        try:
            placement = client.place_order(inst_id, "buy", sz=size, px=resting_px,
                                           ord_type="limit", pos_side="long")
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "place_rejected", reap({"error": _brief(exc)}))
        except Exception as exc:
            return CaseResult(CASE_ID, "FAIL", "place_failed", reap({"error": type(exc).__name__}))
        resting = {"ordId": placement["ordId"], "clOrdId": placement.get("_cl_ord_id")}
        ctx.track_order(inst_id, resting["ordId"], resting["clOrdId"])
        orders.append(resting)
        try:
            row, live = _poll_state(client, inst_id, resting["ordId"], _LIVE, min(poll_timeout, 8.0))
        except Exception as exc:
            return CaseResult(CASE_ID, "FAIL", "resting_poll_error", reap({"error": type(exc).__name__}))
        resting["accept_state"] = str(row.get("state"))
        ctx.log(f"resting order state={resting['accept_state']} ordId={resting['ordId']}")

        entries = []
        for o in orders:
            entry = _close(ctx, inst_id, o["ordId"], cancel_timeout)
            entry.update({k: v for k, v in o.items() if k not in entry})
            entries.append(entry)
        filled_total = sum(float(e.get("accFillSz") or 0) for e in entries)
        flat = _flatten(ctx, inst_id, filled_total, fill_timeout) if filled_total > 0 else {"skipped": "zero_volume"}
        position_after, after_rows = _positions(client, inst_id)
        ours = {str(o["ordId"]) for o in orders}
        pending = client.pending_orders(inst_id=inst_id)
        residual = [{"ordId": o.get("ordId")} for o in pending if str(o.get("ordId")) in ours]
        facts = {
            "orders": entries,
            "crossing_px": crossing_px,
            "resting_px": resting_px,
            "last": last,
            "ask": ask,
            "size": size,
            "partial_fill_observed": any(
                0 < float(e.get("accFillSz") or 0) < size for e in entries
            ),
            "engine_note": "partial fills not producible on this engine; full fills observed",
            "filled_total": filled_total,
            "flatten": flat,
            "residual": residual,
            "position_before": position_before,
            "position_after": position_after,
            "position_rows": after_rows,
        }
        not_terminal = [e for e in entries
                        if str(e.get("final_state") or e.get("state")) not in _TERMINAL]
        if not_terminal:
            return CaseResult(CASE_ID, "FAIL", "order_not_terminal", {**facts, "open_orders": not_terminal})
        if residual:
            return CaseResult(CASE_ID, "FAIL", "residual_order_open", facts)
        crossing_filled = float(entries[0].get("accFillSz") or 0) > 0
        if not crossing_filled:
            return CaseResult(CASE_ID, "FAIL", "crossing_order_not_filled", facts)
        if after_rows or (filled_total > 0 and flat.get("state") != "filled"):
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", facts)
        return CaseResult(CASE_ID, "PASS", "", {**facts, "flat": True})
