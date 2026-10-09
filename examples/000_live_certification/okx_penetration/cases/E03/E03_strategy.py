"""E03 — genuine venue rejection: limit price outside the venue price band.

The case intentionally bypasses local validation — the BUY LIMIT price is
placed above the market (last*(1+bps)) on purpose, so the venue price-band
rules themselves must reject the insert (51006/51121 family).  One order is
submitted once; if the venue accepts it the order is canceled (and any fill
flushed) and the case fails (``no_rejection_observed``).

PASS: the venue rejects the insert (OkxApiError with code/message recorded)
and no order of this run remains.
"""

from __future__ import annotations

import time
import uuid

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "E03"
RISK = "WRITE"

_LIVE = {"live", "partially_filled"}
_TERMINAL = {"canceled", "filled"}


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
            done = ok and entry["final_state"] in _TERMINAL
        except Exception as exc:
            entry["poll_error"] = type(exc).__name__
            done = False
    else:
        done = entry["state"] in _TERMINAL
    if done:
        ctx.mark_order_closed(ord_id)
    return entry


def _flush_position(ctx, inst_id, timeout):
    """Flatten the currently open long position (if any); never raises."""
    client = ctx.client
    try:
        size, rows = _positions(client, inst_id)
    except Exception as exc:
        return {"error": type(exc).__name__}
    if not rows:
        return {"skipped": "no_position"}
    try:
        placement = client.place_order(inst_id, "sell", sz=size, ord_type="market", pos_side="long")
    except OkxApiError as exc:
        return {"rejected": _brief(exc)}
    except Exception as exc:
        return {"error": type(exc).__name__}
    ord_id = placement["ordId"]
    ctx.track_order(inst_id, ord_id, placement.get("_cl_ord_id"))
    try:
        row, ok = _poll_state(client, inst_id, ord_id, {"filled"}, timeout)
    except Exception as exc:
        return {"ordId": ord_id, "error": type(exc).__name__}
    if ok:
        ctx.mark_order_closed(ord_id)
    return {"ordId": ord_id, "state": str(row.get("state"))}


class E03Strategy:
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
        last = float(client.ticker(inst_id)["last"])
        offset = float(scenario.get("band_breach_bps", 200)) / 10_000.0
        px = _round_to_step(last * (1.0 + offset), tick)
        # Prefer the venue's own price-limit ceiling (typically ~0.5% here) so
        # the breach cannot be swallowed by a wider band; fall back to the bps
        # breach above the market when the endpoint is unavailable.
        try:
            envelope = client._request("GET", "/api/v5/public/price-limit", {"instId": inst_id})
            buy_lmt = float((envelope.get("data") or [{}])[0].get("buyLmt") or 0)
            if buy_lmt > 0:
                px = _round_to_step(buy_lmt * 1.05, tick)
        except Exception:
            pass
        size = _round_to_step(float(scenario.get("size", 1)),
                              float(instruments[0].get("lotSz") or 0.01))
        cancel_timeout = float(scenario.get("cancel_timeout_ms", 10000)) / 1000.0
        fill_timeout = float(scenario.get("fill_timeout_ms", 15000)) / 1000.0
        cl_ord_id = "cert" + uuid.uuid4().hex[:16]

        ctx.log(f"submitting BUY {size}@{px} above market {last} (deliberate band breach)")
        rejection, accepted = None, None
        try:
            accepted = client.place_order(inst_id, "buy", sz=size, px=px,
                                          ord_type="limit", pos_side="long", cl_ord_id=cl_ord_id)
        except OkxApiError as exc:
            rejection = _brief(exc)
        except Exception as exc:
            return CaseResult(CASE_ID, "FAIL", "place_failed", {"error": type(exc).__name__})

        if rejection is None:
            ord_id = accepted["ordId"]
            ctx.track_order(inst_id, ord_id, accepted.get("_cl_ord_id"))
            return CaseResult(CASE_ID, "FAIL", "no_rejection_observed", {
                "clOrdId": cl_ord_id, "px": px, "sz": size,
                "order": _close(ctx, inst_id, ord_id, cancel_timeout),
                "flush": _flush_position(ctx, inst_id, fill_timeout)})

        pending = client.pending_orders(inst_id=inst_id) or []
        residual = [{"ordId": o.get("ordId"), "clOrdId": o.get("clOrdId")}
                    for o in pending if str(o.get("clOrdId")) == cl_ord_id]
        position_after, after_rows = _positions(client, inst_id)
        facts = {"rejection_source": "api_error", **rejection, "clOrdId": cl_ord_id,
                 "px": px, "last": last, "sz": size, "pending_after": len(pending),
                 "residual": residual, "position_after": position_after,
                 "position_rows": after_rows}
        if residual:
            for item in residual:
                if item.get("ordId"):
                    _close(ctx, inst_id, item["ordId"], cancel_timeout)
            return CaseResult(CASE_ID, "FAIL", "residual_after_rejection", facts)
        if after_rows:
            facts["flush"] = _flush_position(ctx, inst_id, fill_timeout)
            return CaseResult(CASE_ID, "FAIL", "position_not_flat", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
