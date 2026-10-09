"""Minimal Binance USD-M demo client for certification cases.

Stdlib only, direct TLS, synchronous. The server-time offset is measured at
connect() and applied to every signed request; a -1021 rejection refreshes the
offset once. Read requests may retry a single time on a transport failure.

Write requests (order placement/cancel, listen-key changes) are never retried:
if the connection fails or the reply cannot be parsed, the outcome is unknown,
so the client freezes and refuses further writes. Callers must then report the
case as UNKNOWN and only clean up orders whose identity is certain.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import math
import random
import ssl
import string
import time
import urllib.parse

DEFAULT_HOST = "demo-fapi.binance.com"
MAX_RECV_WINDOW_MS = 60_000
_BODY_CAPTURE_CHARS = 8_000


class BinanceError(Exception):
    """Base class for this client."""


class BinanceApiError(BinanceError):
    """The venue answered with a non-2xx status and a code/msg body."""

    def __init__(self, code, msg, *, status=None, method=None, path=None):
        self.code = code
        self.msg = msg
        self.status = status
        self.method = method
        self.path = path
        super().__init__(f"{method} {path} -> {status} code={code} msg={msg}")


class TransportFailure(BinanceError):
    """No usable reply was received for a read request."""


class WriteOutcomeUnknown(BinanceError):
    """A write request was sent but its outcome could not be established."""


class ClientFrozen(BinanceError):
    """A previous write left the outcome unknown; writes are refused."""


class BinanceDemoClient:
    def __init__(self, api_key, secret, *, host=DEFAULT_HOST, timeout=10.0, recv_window_ms=MAX_RECV_WINDOW_MS):
        self.host = host
        self._api_key = api_key
        self._secret = secret
        self.timeout = float(timeout)
        self.recv_window_ms = int(recv_window_ms)
        self.time_offset_ms = 0
        self.server_time_ms = None
        self.connect_rtt_ms = None
        self.calls = []
        self.frozen = False
        self.frozen_reason = ""
        self._exchange_cache = {}

    # ------------------------------------------------------------------ http
    def _one_request(self, method, path, query, *, signed):
        conn = http.client.HTTPSConnection(
            self.host, timeout=self.timeout, context=ssl.create_default_context()
        )
        headers = {"User-Agent": "backtrader-cert/1.0", "Connection": "close", "Accept": "application/json"}
        if signed:
            headers["X-MBX-APIKEY"] = self._api_key
        url = path + (f"?{query}" if query else "")
        try:
            conn.request(method, url, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, raw
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _record(self, method, path, params, status, raw, error=None):
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:
            text = ""
        entry = {
            "t_ms": int(time.time() * 1000),
            "method": method,
            "path": path,
            "status": status,
            "params": {k: v for k, v in params.items() if k != "signature"},
            "body": text[:_BODY_CAPTURE_CHARS],
            "body_sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
        }
        if error:
            entry["error"] = error
        self.calls.append(entry)

    def _request(self, method, path, params=None, *, signed=True, is_write=False):
        if is_write and self.frozen:
            raise ClientFrozen(f"client frozen after unknown write: {self.frozen_reason}")
        params = dict(params or {})
        attempts = 0
        refreshed = False
        while True:
            attempts += 1
            query_params = dict(params)
            if signed:
                query_params["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
                query_params["recvWindow"] = self.recv_window_ms
                query = urllib.parse.urlencode(query_params)
                signature = hmac.new(self._secret.encode(), query.encode(), hashlib.sha256).hexdigest()
                query = query + "&signature=" + signature
                query_params["signature"] = signature
            else:
                query = urllib.parse.urlencode(query_params)
            status = None
            raw = b""
            try:
                status, raw = self._one_request(method, path, query, signed=signed)
            except Exception as exc:  # transport-level failure
                self._record(method, path, query_params, None, b"", error=f"{type(exc).__name__}: {exc}")
                if is_write:
                    self.frozen = True
                    self.frozen_reason = f"{method} {path} transport failure: {type(exc).__name__}"
                    raise WriteOutcomeUnknown(self.frozen_reason) from exc
                if attempts == 1:
                    time.sleep(0.25)
                    continue
                raise TransportFailure(f"{method} {path} failed: {type(exc).__name__}: {exc}") from exc

            self._record(method, path, query_params, status, raw)

            if 200 <= status < 300:
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except Exception:
                    if is_write:
                        self.frozen = True
                        self.frozen_reason = f"{method} {path} unparseable reply"
                        raise WriteOutcomeUnknown(self.frozen_reason)
                    raise TransportFailure(f"{method} {path} unparseable reply")

            code = None
            msg = ""
            try:
                body = json.loads(raw)
                code = body.get("code")
                msg = body.get("msg", "")
            except Exception:
                msg = raw[:200].decode("utf-8", "replace")

            if signed and code == -1021 and not refreshed:
                refreshed = True
                self.server_time_ms = None
                self._measure_time_offset()
                continue
            if is_write and code is None:
                self.frozen = True
                self.frozen_reason = f"{method} {path} rejected without code"
                raise WriteOutcomeUnknown(self.frozen_reason)
            raise BinanceApiError(code, msg, status=status, method=method, path=path)

    # ------------------------------------------------------------ connection
    def _measure_time_offset(self):
        t0 = int(time.time() * 1000)
        status, raw = self._one_request("GET", "/fapi/v1/time", "", signed=False)
        t1 = int(time.time() * 1000)
        if status != 200:
            raise TransportFailure(f"server time probe failed: {status}")
        server = json.loads(raw)["serverTime"]
        self.server_time_ms = server
        self.connect_rtt_ms = t1 - t0
        self.time_offset_ms = server - (t0 + t1) // 2

    def connect(self) -> dict:
        self._measure_time_offset()
        return {
            "host": self.host,
            "server_time_ms": self.server_time_ms,
            "time_offset_ms": self.time_offset_ms,
            "rtt_ms": self.connect_rtt_ms,
        }

    def describe(self) -> dict:
        return {
            "host": self.host,
            "server_time_ms": self.server_time_ms,
            "time_offset_ms": self.time_offset_ms,
            "recv_window_ms": self.recv_window_ms,
            "frozen": self.frozen,
            "frozen_reason": self.frozen_reason,
            "call_count": len(self.calls),
        }

    def close(self):
        return None

    # ---------------------------------------------------------------- reads
    def exchange_info(self, symbol=None):
        if symbol and symbol in self._exchange_cache:
            return self._exchange_cache[symbol]
        data = self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
        if symbol:
            for item in data.get("symbols", []):
                if item.get("symbol") == symbol:
                    self._exchange_cache[symbol] = item
                    return item
            raise BinanceApiError(None, f"symbol not found: {symbol}", path="/fapi/v1/exchangeInfo")
        return data

    def filters(self, symbol):
        info = self.exchange_info(symbol)
        out = {"tick_size": None, "step_size": None, "min_qty": None, "max_qty": None, "min_notional": None,
               "status": info.get("status"), "contract_type": info.get("contractType")}
        for item in info.get("filters", []):
            kind = item.get("filterType")
            if kind == "PRICE_FILTER":
                out["tick_size"] = float(item["tickSize"])
            elif kind == "LOT_SIZE":
                out["step_size"] = float(item["stepSize"])
                out["min_qty"] = float(item["minQty"])
                out["max_qty"] = float(item["maxQty"])
            elif kind == "MIN_NOTIONAL":
                out["min_notional"] = float(item["notional"])
        return out

    def mark_price(self, symbol):
        data = self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)
        return data["markPrice"]

    def book_ticker(self, symbol):
        return self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol}, signed=False)

    def klines(self, symbol, interval="1m", limit=2):
        return self._request(
            "GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": int(limit)}, signed=False
        )

    def account_config(self):
        return self._request("GET", "/fapi/v1/accountConfig")

    def balances(self):
        return self._request("GET", "/fapi/v2/balance")

    def position_risk(self, symbol=None):
        params = {"symbol": symbol} if symbol else None
        return self._request("GET", "/fapi/v2/positionRisk", params)

    def open_orders(self, symbol=None):
        params = {"symbol": symbol} if symbol else None
        return self._request("GET", "/fapi/v1/openOrders", params)

    def query_order(self, symbol, *, order_id=None, client_order_id=None):
        params = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = int(order_id)
        if client_order_id is not None:
            params["origClientOrderId"] = client_order_id
        if "orderId" not in params and "origClientOrderId" not in params:
            raise ValueError("order identity required")
        return self._request("GET", "/fapi/v1/order", params)

    def all_orders(self, symbol, limit=50):
        return self._request("GET", "/fapi/v1/allOrders", {"symbol": symbol, "limit": int(limit)})

    def user_trades(self, symbol, limit=50):
        return self._request("GET", "/fapi/v1/userTrades", {"symbol": symbol, "limit": int(limit)})

    def income(self, *, symbol=None, income_type=None, limit=50):
        params = {"limit": int(limit)}
        if symbol:
            params["symbol"] = symbol
        if income_type:
            params["incomeType"] = income_type
        return self._request("GET", "/fapi/v1/income", params)

    def commission_rate(self, symbol):
        return self._request("GET", "/fapi/v1/commissionRate", {"symbol": symbol})

    # --------------------------------------------------------------- writes
    def place_order(self, symbol, side, *, order_type="LIMIT", quantity=None, price=None,
                    position_side=None, time_in_force=None, reduce_only=None,
                    client_order_id=None, close_position=None, working_type=None):
        params = {"symbol": symbol, "side": side.upper(), "type": order_type.upper()}
        if quantity is not None:
            params["quantity"] = str(quantity)
        if price is not None:
            params["price"] = str(price)
        if position_side:
            params["positionSide"] = position_side.upper()
        if time_in_force and order_type.upper() == "LIMIT":
            params["timeInForce"] = time_in_force.upper()
        if reduce_only is not None:
            params["reduceOnly"] = "true" if reduce_only else "false"
        if close_position is not None:
            params["closePosition"] = "true" if close_position else "false"
        if working_type:
            params["workingType"] = working_type.upper()
        if client_order_id is None:
            client_order_id = "cert" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        params["newClientOrderId"] = client_order_id
        reply = self._request("POST", "/fapi/v1/order", params, is_write=True)
        reply["_client_order_id"] = client_order_id
        return reply

    def cancel_order(self, symbol, *, order_id=None, client_order_id=None):
        params = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = int(order_id)
        if client_order_id is not None:
            params["origClientOrderId"] = client_order_id
        if "orderId" not in params and "origClientOrderId" not in params:
            raise ValueError("order identity required")
        return self._request("DELETE", "/fapi/v1/order", params, is_write=True)

    def cancel_all_open_orders(self, symbol):
        return self._request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol}, is_write=True)

    def listen_key_start(self):
        return self._request("POST", "/fapi/v1/listenKey", is_write=True)

    def listen_key_renew(self):
        return self._request("PUT", "/fapi/v1/listenKey", is_write=True)

    def listen_key_delete(self):
        return self._request("DELETE", "/fapi/v1/listenKey", is_write=True)


# ------------------------------------------------------------------ helpers
def round_step(value, step, rounding=math.floor):
    if step <= 0:
        raise ValueError("step must be positive")
    return round(rounding(round(value / step, 9)) * step, 10)


def format_decimal(value, places=10):
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text if text else "0"
