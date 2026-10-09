"""Minimal SimNow CTP trader session for certification cases.

Runs on CPython 3.11 against the dev ``bt_api_ctp`` source (``BT_API_PY_ROOT``,
default ``D:/bt_api_py``).  Read cases connect, query, and close.  Write cases
first call the frozen-simulation direct admission
(``arm_execution_for_registered_sim``) and then use bounded limit-order and
cancel operations whose report carries the exact request/order identity.

The session never reads credentials itself: the caller passes values loaded
from the checkout-root ``.env`` by name.  Evidence projections skip account
identity fields (broker/investor/user/account id strings).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SDK_ROOT = "D:/bt_api_py"

_IDENTITY_KEYS = {"BrokerID", "InvestorID", "UserID", "AccountID", "AccountAlias"}

_ORDER_KEYS = (
    "OrderRef", "OrderSysID", "InstrumentID", "ExchangeID", "Direction",
    "CombOffsetFlag", "CombHedgeFlag", "LimitPrice", "VolumeTotalOriginal",
    "VolumeTraded", "VolumeTotal", "OrderStatus", "InsertDate", "InsertTime",
    "FrontID", "SessionID", "StatusMsg", "CancelTime",
)
_POSITION_KEYS = (
    "InstrumentID", "ExchangeID", "PosiDirection", "Position", "YdPosition",
    "TodayPosition", "OpenCost", "UseMargin", "PositionProfit",
)
_ACCOUNT_KEYS = (
    "Available", "Balance", "CurrMargin", "CloseProfit", "PositionProfit",
    "Commission", "FrozenMargin", "FrozenCommission", "WithdrawQuota",
    "PreBalance", "Deposit", "Withdraw",
)
_TRADE_KEYS = (
    "TradeID", "OrderRef", "OrderSysID", "InstrumentID", "ExchangeID",
    "Direction", "OffsetFlag", "HedgeFlag", "Price", "Volume", "TradeDate",
    "TradeTime",
)
_INSTRUMENT_KEYS = (
    "InstrumentID", "ExchangeID", "ProductID", "VolumeMultiple", "PriceTick",
    "MinLimitOrderVolume", "MaxLimitOrderVolume", "IsTrading",
)
_DEPTH_KEYS = (
    "InstrumentID", "ExchangeID", "LastPrice", "BidPrice1", "AskPrice1",
    "UpperLimitPrice", "LowerLimitPrice", "SettlementPrice", "PreSettlementPrice",
    "OpenInterest",
)

_FAMILY_KEYS = {
    "orders": _ORDER_KEYS,
    "positions": _POSITION_KEYS,
    "account": _ACCOUNT_KEYS,
    "trades": _TRADE_KEYS,
    "instruments": _INSTRUMENT_KEYS,
    "depth_market_data": _DEPTH_KEYS,
}


class SimNowError(Exception):
    """Base class for this client."""


class SimNowSessionError(SimNowError):
    """A bounded session or venue step failed; details carry a reason code."""

    def __init__(self, reason, facts=None):
        self.reason = reason
        self.facts = dict(facts or {})
        super().__init__(reason)


def ensure_sdk_importable(root=None, default_root=None) -> dict:
    """Put the dev bt_api_ctp/bt_api_base sources first and verify the origin."""
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11):
        raise SimNowSessionError(
            "cpython_311_required",
            {"running": f"{sys.implementation.name} {sys.version.split()[0]}",
             "hint": "run with C:/anaconda3/python.exe"},
        )
    base = Path(root or os.environ.get("BT_API_PY_ROOT") or (default_root or DEFAULT_SDK_ROOT))
    ctp_src = base / "bt_api" / "bt_api_ctp" / "src"
    base_src = base / "bt_api" / "bt_api_base" / "src"
    if not (ctp_src / "bt_api_ctp" / "__init__.py").is_file():
        raise SimNowSessionError("sdk_root_not_found", {"root": str(base)})
    for extra in (str(base), str(base_src), str(ctp_src)):
        if extra in sys.path:
            sys.path.remove(extra)
        sys.path.insert(0, extra)
    import bt_api_ctp  # noqa: E402

    origin = Path(bt_api_ctp.__file__).resolve()
    try:
        origin.relative_to(ctp_src.resolve())
    except ValueError:
        raise SimNowSessionError(
            "sdk_origin_not_dev_source", {"origin": str(origin)}
        ) from None
    return {"sdk_root": str(base), "sdk_origin": str(origin)}


@dataclass(frozen=True)
class FrontPair:
    index: int
    td_front: str
    md_front: str


def _endpoint(front: str):
    text = str(front or "").strip()
    if text.startswith("tcp://"):
        text = text[6:]
    host, _, port = text.rpartition(":")
    return host, int(port)


def select_front_pair(fronts, env, *, connect_timeout=3.0):
    """Pick the first configured pair whose TD and MD both accept a TCP connect.

    Returns ``(pair, attempts)``; attempts carry only indexes and booleans.
    """
    pairs = list((fronts or {}).get("pairs", []) or [])
    if not pairs:
        raise SimNowSessionError("no_front_pairs_configured")
    attempts = []
    for index, item in enumerate(pairs):
        td = env.get(item.get("td_env", ""))
        md = env.get(item.get("md_env", ""))
        if not td or not md:
            attempts.append({"index": index, "td": False, "md": False, "missing_env": True})
            continue
        td_ok = _probe(_endpoint(td), connect_timeout)
        md_ok = _probe(_endpoint(md), connect_timeout) if td_ok else False
        attempts.append({"index": index, "td": td_ok, "md": md_ok})
        if td_ok and md_ok:
            return FrontPair(index=index, td_front=td, md_front=md), attempts
    raise SimNowSessionError("no_reachable_front_pair", {"attempts": attempts})


def _probe(address, timeout):
    host, port = address
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pick(obj, names):
    facts = {}
    for name in names:
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            facts[name] = value
    return facts


def _row_facts(family, row):
    keys = _FAMILY_KEYS.get(family, ())
    return {k: v for k, v in _pick(row, keys).items() if k not in _IDENTITY_KEYS}


class SimNowSession:
    def __init__(
        self,
        *,
        broker_id,
        user_id,
        password,
        app_id,
        auth_code,
        pair,
        login_timeout=30.0,
        query_timeout=8.0,
        stop_timeout=12.0,
        sdk_provenance=None,
        front_selection=None,
    ):
        self.broker_id = broker_id
        self._user_id = user_id
        self._password = password
        self._app_id = app_id
        self._auth_code = auth_code
        self.pair = pair
        self.login_timeout = float(login_timeout)
        self.query_timeout = float(query_timeout)
        self.stop_timeout = float(stop_timeout)
        self.sdk_provenance = dict(sdk_provenance or {})
        self.front_selection = list(front_selection or [])
        self.calls = []
        self._client = None
        self._capability = None
        self._orders = {}
        self._closed = False
        self.login_facts = {}
        self._ref_counter = 0
        self.event_hook = None
        self.write_paused = False
        self.pause_reason = ""

    # ------------------------------------------------------------- plumbing
    def _record(self, kind, **fields):
        entry = {"t_ms": int(time.time() * 1000), "kind": kind}
        entry.update(fields)
        self.calls.append(entry)
        if self.event_hook is not None:
            try:
                self.event_hook(kind, **fields)
            except Exception:
                pass
        return entry

    def pause(self, reason="operator_pause"):
        self.write_paused = True
        self.pause_reason = str(reason)
        self._record("pause", reason=self.pause_reason)
        return {"paused": True, "reason": self.pause_reason}

    def resume(self):
        self.write_paused = False
        self._record("resume", reason=self.pause_reason)
        self.pause_reason = ""
        return {"paused": False}

    def connect(self) -> dict:
        from bt_api_ctp.ctp.client import TraderClient

        if self._client is not None:
            raise SimNowSessionError("already_connected")
        client = TraderClient(
            self.pair.td_front,
            self.broker_id,
            self._user_id,
            self._password,
            app_id=self._app_id,
            auth_code=self._auth_code,
            auto_settlement_confirm=False,
        )
        self._client = client
        started = time.monotonic()
        client.start(block=False)
        ready = client.wait_ready(timeout=self.login_timeout)
        elapsed = time.monotonic() - started
        if ready is not True:
            raise SimNowSessionError("login_not_ready", {"seconds": round(elapsed, 3)})
        facts = {
            "front_id": int(getattr(client, "_front_id", 0) or 0),
            "session_id": int(getattr(client, "_session_id", 0) or 0),
            "trading_day": str(getattr(client, "_trading_day", "") or ""),
            "connection_generation": int(getattr(client, "_connection_generation", 0) or 0),
            "login_seconds": round(elapsed, 3),
        }
        if facts["connection_generation"] <= 0 or len(facts["trading_day"]) != 8:
            raise SimNowSessionError("login_facts_invalid", facts)
        self.login_facts = facts
        self._record("login", **facts)
        return facts

    @property
    def account_fingerprint(self) -> str:
        if self._client is None:
            return ""
        return str(getattr(self._client, "_account_fingerprint", "") or "")

    def describe(self) -> dict:
        facts = {
            "pair_index": self.pair.index,
            "sdk_root": self.sdk_provenance.get("sdk_root", ""),
            "sdk_origin": self.sdk_provenance.get("sdk_origin", ""),
            "call_count": len(self.calls),
            "closed": self._closed,
        }
        if self._client is not None:
            facts["trading_ready"] = bool(self._client.is_trading_ready)
            facts["read_only_ready"] = bool(self._client.is_read_only_ready)
            facts["frozen"] = bool(getattr(self._client, "frozen", False))
        return facts

    # ---------------------------------------------------------- read queries
    def _run_query(self, family, timeout=None, attempts=2, gap=1.5, **filters):
        client = self._require_client()
        method = getattr(client, f"query_{family}_result")
        effective_timeout = float(timeout or self.query_timeout)
        attempt = 0
        while True:
            attempt += 1
            try:
                result = method(timeout=effective_timeout, **filters)
            except TypeError:
                result = method(timeout=effective_timeout)
            records = list(getattr(result, "records", ()) or ())
            facts = {
                "family": family,
                "complete": bool(getattr(result, "complete", False)),
                "timed_out": bool(getattr(result, "timed_out", False)),
                "error_code": getattr(result, "error_code", None),
                "record_count": len(records),
                "request_id": getattr(result, "request_id", None),
                "connection_generation": getattr(result, "connection_generation", None),
                "attempt": attempt,
            }
            self._record("query", **facts)
            if facts["complete"] and not facts["timed_out"] and facts["error_code"] in (None, 0):
                break
            # Live SimNow fronts occasionally drop the first query of a fresh
            # session, stall a large page, or answer -2 while a previous
            # request is still pending at the front; bounded retries are safe
            # for reads and back off further on flow control (-2).
            if attempt < attempts:
                time.sleep(gap + (2.0 if facts["error_code"] == -2 else 0.0))
                effective_timeout = max(effective_timeout * 1.5, effective_timeout + 4.0)
                continue
            raise SimNowSessionError(f"query_incomplete:{family}", facts)
        expected_generation = self.login_facts.get("connection_generation")
        if expected_generation and facts["connection_generation"] != expected_generation:
            raise SimNowSessionError(f"query_generation_mismatch:{family}", facts)
        return {"facts": facts, "rows": [_row_facts(family, row) for row in records]}

    def query_orders(self, instrument_id="", exchange_id="", order_sys_id=""):
        return self._run_query(
            "orders",
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            order_sys_id=order_sys_id,
        )

    def query_positions(self, instrument_id=""):
        return self._run_query("positions", instrument_id=instrument_id)

    def query_account(self):
        return self._run_query("account")

    def query_trades(self, instrument_id=""):
        return self._run_query("trades", instrument_id=instrument_id)

    def query_instruments(self, instrument_id="", exchange_id="", product_id=""):
        return self._run_query(
            "instruments",
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            product_id=product_id,
        )

    def query_depth_market_data(self, instrument_id=""):
        return self._run_query(
            "depth_market_data",
            instrument_id=instrument_id,
            timeout=12.0,
            attempts=4,
            gap=2.5,
        )

    def find_order(self, order_ref, *, instrument_id="", timeout=6.0, interval=0.5):
        """Poll the venue order query until our OrderRef appears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.query_orders(instrument_id=instrument_id)
            for row in result["rows"]:
                if str(row.get("OrderRef")) == str(order_ref):
                    self.mark_order_state(order_ref, "open", row.get("OrderSysID"))
                    return row
            time.sleep(interval)
        raise SimNowSessionError("order_not_visible", {"order_ref": str(order_ref)})

    def wait_order_status(self, order_ref, statuses, *, instrument_id="", timeout=10.0, interval=0.5):
        deadline = time.monotonic() + timeout
        wanted = {str(s) for s in statuses}
        latest = None
        while time.monotonic() < deadline:
            try:
                row = self.find_order(
                    order_ref,
                    instrument_id=instrument_id,
                    timeout=min(2.5, max(0.5, deadline - time.monotonic())),
                    interval=interval,
                )
            except SimNowSessionError as exc:
                if exc.reason != "order_not_visible":
                    raise
                continue
            latest = row
            if str(row.get("OrderStatus")) in wanted:
                return row
            time.sleep(interval)
        raise SimNowSessionError(
            "order_status_timeout",
            {"order_ref": str(order_ref), "expected": sorted(wanted), "latest": latest},
        )

    # ---------------------------------------------------------------- writes
    def arm(self, *, instrument_id, exchange_id, strategy_identity_sha256, execution_cycle_id, preflight_sha256):
        client = self._require_client()
        capability, state = client.arm_execution_for_registered_sim(
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            md_front=self.pair.md_front,
            strategy_identity_sha256=strategy_identity_sha256,
            execution_cycle_id=execution_cycle_id,
            preflight_sha256=preflight_sha256,
        )
        self._capability = capability
        projection = {
            "armed": bool(state.get("armed")),
            "environment_profile": state.get("environment_profile"),
            "connection_generation": state.get("connection_generation"),
            "trading_day": state.get("trading_day"),
        }
        self._record("arm", **projection)
        if projection["armed"] is not True:
            raise SimNowSessionError("arm_not_confirmed", projection)
        return projection

    def _require_armed(self):
        if self.write_paused:
            raise SimNowSessionError("write_paused", {"reason": self.pause_reason})
        if self._capability is None:
            raise SimNowSessionError("write_requires_arm")

    def _order_insert_evidence(self, client, request_id, *, timeout=8.0):
        deadline = time.monotonic() + timeout
        evidence = None
        while time.monotonic() < deadline:
            evidence = client.get_order_insert_evidence(request_id)
            if evidence is not None and (
                getattr(evidence, "evidence_received", False)
                or getattr(evidence, "callback_received", False)
            ):
                break
            time.sleep(0.25)
        if evidence is None:
            return {"status": "unknown", "reason": "no_recorded_request"}
        return {
            "status": str(getattr(evidence, "status", "unknown")),
            "error_code": getattr(evidence, "error_code", None),
            "error_message": str(getattr(evidence, "error_message", "") or "")[:160],
            "callback_received": bool(getattr(evidence, "callback_received", False)),
            "evidence_received": bool(getattr(evidence, "evidence_received", False)),
            "submit_code": getattr(evidence, "submit_code", None),
            "reason": str(getattr(evidence, "reason", "") or "")[:120],
        }

    def place_limit_order(
        self,
        *,
        instrument_id,
        exchange_id,
        direction,
        offset_flag,
        price,
        volume,
        hedge_flag="1",
    ) -> dict:
        from bt_api_ctp.ctp.client import CtpExecutionGateError
        from bt_api_ctp.ctp.ctp_structs_order import CThostFtdcInputOrderField

        self._require_armed()
        client = self._require_client()
        field = CThostFtdcInputOrderField()
        field.BrokerID = self.broker_id
        field.InvestorID = self._user_id
        field.UserID = self._user_id
        field.InstrumentID = str(instrument_id)
        field.ExchangeID = str(exchange_id)
        # The venue keeps orders from earlier sessions visible in queries, so
        # the SDK's per-session counter is not unique.  Use a timestamp-based
        # OrderRef (12 digits, increasing within a session) instead.
        self._ref_counter += 1
        field.OrderRef = f"{int(time.time()) % 10**10:010d}{self._ref_counter % 100:02d}"
        request_id = client._next_request_id()
        field.RequestID = request_id
        field.OrderPriceType = "2"
        field.Direction = str(direction)
        field.CombOffsetFlag = str(offset_flag)
        field.CombHedgeFlag = str(hedge_flag)
        field.LimitPrice = float(price)
        field.VolumeTotalOriginal = int(volume)
        field.TimeCondition = "3"
        field.VolumeCondition = "1"
        field.MinVolume = 1
        field.ContingentCondition = "1"
        field.StopPrice = 0.0
        field.ForceCloseReason = "0"
        field.IsAutoSuspend = 0
        field.UserForceClose = 0
        try:
            submit_code = client.submit_order_insert(
                field, request_id, execution_capability=self._capability
            )
        except CtpExecutionGateError as exc:
            self._record("order_refused", order_ref=field.OrderRef, error=str(exc)[:120])
            raise SimNowSessionError("write_refused", {"error": str(exc)[:120]}) from exc
        evidence = self._order_insert_evidence(client, request_id)
        record = {
            "order_ref": field.OrderRef,
            "request_id": request_id,
            "direction": str(direction),
            "offset_flag": str(offset_flag),
            "price": float(price),
            "volume": int(volume),
            "submit_code": submit_code,
            "evidence": evidence,
        }
        self._orders[field.OrderRef] = {
            "instrument_id": str(instrument_id),
            "exchange_id": str(exchange_id),
            "order_sys_id": "",
            "state": "unknown",
        }
        self._record("order_insert", **{k: v for k, v in record.items() if k != "evidence"})
        if evidence["status"] == "rejected":
            self._orders[field.OrderRef]["state"] = "rejected"
            raise SimNowSessionError("order_rejected", record)
        # An unresolved front callback is not a rejection: the order may still
        # be visible at the venue, so callers must confirm through a query.
        if evidence["status"] == "accepted":
            self._orders[field.OrderRef]["state"] = "open"
        return record

    def mark_order_state(self, order_ref, state, order_sys_id=None):
        entry = self._orders.setdefault(str(order_ref), {})
        entry["state"] = str(state)
        if order_sys_id:
            entry["order_sys_id"] = str(order_sys_id)
        return entry

    def pending_orders(self):
        """Orders whose terminal state is not yet confirmed."""
        return {
            order_ref: dict(entry)
            for order_ref, entry in self._orders.items()
            if entry.get("state") in {"open", "unknown"}
        }

    def cancel_order(self, *, instrument_id, exchange_id, order_ref, order_sys_id="", action_flag="0") -> dict:
        from bt_api_ctp.ctp.client import CtpExecutionGateError
        from bt_api_ctp.ctp.ctp_structs_order import CThostFtdcInputOrderActionField

        self._require_armed()
        client = self._require_client()
        action = CThostFtdcInputOrderActionField()
        action.BrokerID = self.broker_id
        action.InvestorID = self._user_id
        action.UserID = self._user_id
        action.InstrumentID = str(instrument_id)
        action.ExchangeID = str(exchange_id)
        action.OrderRef = str(order_ref)
        if order_sys_id:
            action.OrderSysID = str(order_sys_id)
        action.FrontID = int(getattr(client, "_front_id", 0) or 0)
        action.SessionID = int(getattr(client, "_session_id", 0) or 0)
        action.ActionFlag = str(action_flag)
        request_id = client._next_request_id()
        action.OrderActionRef = request_id
        action.RequestID = request_id
        try:
            submit_code = client.submit_order_action(
                action, request_id, execution_capability=self._capability
            )
        except CtpExecutionGateError as exc:
            self._record("cancel_refused", order_ref=str(order_ref), error=str(exc)[:120])
            raise SimNowSessionError("write_refused", {"error": str(exc)[:120]}) from exc
        record = {
            "order_ref": str(order_ref),
            "request_id": request_id,
            "action_flag": str(action_flag),
            "submit_code": submit_code,
        }
        self._record("order_action", **record)
        return record

    # ----------------------------------------------------------------- close
    def _require_client(self):
        if self._client is None:
            raise SimNowSessionError("session_not_connected")
        return self._client

    def close(self) -> dict:
        facts = {"attempted": False}
        if self._client is not None and not self._closed:
            self._closed = True
            facts["attempted"] = True
            try:
                receipt = self._client.stop_and_wait(timeout=self.stop_timeout)
                facts.update(
                    {
                        "join_required": getattr(receipt, "join_required", None),
                        "join_completed": getattr(receipt, "join_completed", None),
                        "native_released": getattr(receipt, "native_released", None),
                        "thread_alive": getattr(receipt, "thread_alive", None),
                        "timed_out": getattr(receipt, "timed_out", None),
                        "complete": getattr(receipt, "complete", None),
                    }
                )
            except Exception as exc:
                facts["error"] = f"{type(exc).__name__}: {exc}"[:200]
        self._record("native_stop", **facts)
        return facts
