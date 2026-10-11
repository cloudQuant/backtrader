"""Minimal OKX demo client for certification cases.

Stdlib only, synchronous.  Signing follows the OKX v5 scheme: the prehash is
``timestamp + method + requestPath(+query) + body`` HMAC-SHA256'd with the
API secret and base64-encoded; the demo header ``x-simulated-trading: 1``
selects the demo environment.  The server-time offset is measured at
connect() and applied to every signed request.

Write requests (place/cancel) are never retried: if the connection fails or
the reply cannot be parsed, the outcome is unknown, so the client freezes and
refuses further writes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import random
import ssl
import string
import time
import urllib.parse
from datetime import datetime, timezone

DEFAULT_HOST = "www.okx.com"
_BODY_CAPTURE_CHARS = 8_000


class OkxError(Exception):
    """Base class for this client."""


class OkxApiError(OkxError):
    def __init__(self, code, msg, *, status=None, method=None, path=None):
        self.code = code
        self.msg = msg
        self.status = status
        self.method = method
        self.path = path
        super().__init__(f"{method} {path} -> {status} code={code} msg={msg}")


class TransportFailure(OkxError):
    """No usable reply was received for a read request."""


class WriteOutcomeUnknown(OkxError):
    """A write request was sent but its outcome could not be established."""


class ClientFrozen(OkxError):
    """A previous write left the outcome unknown; writes are refused."""


class OkxDemoClient:
    def __init__(self, api_key, secret, passphrase, *, host=DEFAULT_HOST, simulated=True, timeout=10.0):
        self.host = host
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._simulated = bool(simulated)
        self.timeout = float(timeout)
        self.time_offset_ms = 0
        self.server_time_ms = None
        self.calls = []
        self.frozen = False
        self.frozen_reason = ""
        self.pos_mode = ""
        self.td_mode = "cross"

    # ------------------------------------------------------------------ http
    def _one_request(self, method, path, headers, body=None):
        conn = http.client.HTTPSConnection(self.host, timeout=self.timeout, context=ssl.create_default_context())
        base_headers = {
            "User-Agent": "backtrader-cert/1.0",
            "Connection": "close",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        base_headers.update(headers)
        try:
            conn.request(method, path, body=body, headers=base_headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, raw
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _record(self, method, path, status, raw, error=None):
        text = raw.decode("utf-8", "replace") if raw else ""
        entry = {
            "t_ms": int(time.time() * 1000),
            "method": method,
            "path": path.split("?")[0],
            "status": status,
            "body": text[:_BODY_CAPTURE_CHARS],
            "body_sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
        }
        if error:
            entry["error"] = error
        self.calls.append(entry)

    def _sign_headers(self, method, path):
        ts_ms = int(time.time() * 1000) + self.time_offset_ms
        stamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
        stamp += f"{ts_ms % 1000:03d}Z"
        prehash = f"{stamp}{method.upper()}{path}"
        signature = base64.b64encode(
            hmac.new(self._secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": stamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
        }
        if self._simulated:
            headers["x-simulated-trading"] = "1"
        return headers

    def _request(self, method, path, params=None, body=None, *, signed=True, is_write=False):
        if is_write and self.frozen:
            raise ClientFrozen(f"client frozen after unknown write: {self.frozen_reason}")
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        full_path = path + query
        payload = json.dumps(body, separators=(",", ":")) if body is not None else None
        attempts = 0
        while True:
            attempts += 1
            headers = self._sign_headers(method, full_path) if signed else {}
            if body is not None:
                # The signature covers the exact serialized body bytes.
                prehash = headers["OK-ACCESS-TIMESTAMP"] + method.upper() + full_path + (payload or "")
                headers["OK-ACCESS-SIGN"] = base64.b64encode(
                    hmac.new(self._secret.encode(), prehash.encode(), hashlib.sha256).digest()
                ).decode()
            status = None
            raw = b""
            try:
                status, raw = self._one_request(method, full_path, headers, payload)
            except Exception as exc:
                self._record(method, full_path, None, b"", error=f"{type(exc).__name__}: {exc}")
                if is_write:
                    self.frozen = True
                    self.frozen_reason = f"{method} {path} transport failure: {type(exc).__name__}"
                    raise WriteOutcomeUnknown(self.frozen_reason) from exc
                if attempts == 1:
                    time.sleep(0.25)
                    continue
                raise TransportFailure(f"{method} {path} failed: {type(exc).__name__}: {exc}") from exc

            self._record(method, full_path, status, raw)

            if 200 <= status < 300:
                try:
                    envelope = json.loads(raw) if raw else {}
                except Exception:
                    if is_write:
                        self.frozen = True
                        self.frozen_reason = f"{method} {path} unparseable reply"
                        raise WriteOutcomeUnknown(self.frozen_reason)
                    raise TransportFailure(f"{method} {path} unparseable reply")
                code = str(envelope.get("code", ""))
                if code == "0":
                    return envelope
                detail = envelope.get("msg", "")
                items = envelope.get("data") or []
                if items and isinstance(items[0], dict):
                    sub_code = str(items[0].get("sCode") or "")
                    sub_msg = str(items[0].get("sMsg") or "")
                    if sub_code and sub_code != "0":
                        detail = f"{detail}: {sub_code} {sub_msg}".strip()
                raise OkxApiError(code, detail, status=status, method=method, path=path)

            try:
                envelope = json.loads(raw)
                raise OkxApiError(str(envelope.get("code", "")), envelope.get("msg", ""), status=status, method=method, path=path)
            except OkxApiError:
                raise
            except Exception:
                raise OkxApiError(None, raw[:200].decode("utf-8", "replace"), status=status, method=method, path=path)

    # ------------------------------------------------------------ connection
    def connect(self) -> dict:
        envelope = self._request("GET", "/api/v5/public/time", signed=False)
        server_ms = int(envelope["data"][0]["ts"])
        self.server_time_ms = server_ms
        self.time_offset_ms = server_ms - int(time.time() * 1000)
        config = self.account_config()
        self.pos_mode = str(config.get("posMode") or "")
        return {
            "host": self.host,
            "server_time_ms": server_ms,
            "time_offset_ms": self.time_offset_ms,
            "pos_mode": self.pos_mode,
            "acct_lv": config.get("acctLv"),
        }

    def describe(self) -> dict:
        return {
            "host": self.host,
            "server_time_ms": self.server_time_ms,
            "time_offset_ms": self.time_offset_ms,
            "pos_mode": self.pos_mode,
            "frozen": self.frozen,
            "frozen_reason": self.frozen_reason,
            "call_count": len(self.calls),
        }

    def close(self):
        return None

    # ---------------------------------------------------------------- reads
    def account_config(self):
        return self._request("GET", "/api/v5/account/config")["data"][0]

    def balance(self, ccy=None):
        params = {"ccy": ccy} if ccy else None
        return self._request("GET", "/api/v5/account/balance", params)["data"]

    def positions(self, inst_type="SWAP", inst_id=None):
        params = {"instType": inst_type}
        if inst_id:
            params["instId"] = inst_id
        return self._request("GET", "/api/v5/account/positions", params)["data"]

    def pending_orders(self, inst_type="SWAP", inst_id=None):
        params = {"instType": inst_type}
        if inst_id:
            params["instId"] = inst_id
        return self._request("GET", "/api/v5/trade/orders-pending", params)["data"]

    def order_details(self, inst_id, *, ord_id=None, cl_ord_id=None):
        params = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        return self._request("GET", "/api/v5/trade/order", params)["data"]

    def orders_history(self, inst_type="SWAP", limit=50):
        return self._request(
            "GET", "/api/v5/trade/orders-history", {"instType": inst_type, "limit": int(limit)}
        )["data"]

    def instruments(self, inst_id, inst_type="SWAP"):
        return self._request(
            "GET", "/api/v5/public/instruments", {"instType": inst_type, "instId": inst_id}
        )["data"]

    def ticker(self, inst_id):
        return self._request("GET", "/api/v5/market/ticker", {"instId": inst_id})["data"][0]

    # --------------------------------------------------------------- writes
    def place_order(self, inst_id, side, *, sz, px=None, ord_type="limit", pos_side=None,
                    td_mode=None, cl_ord_id=None):
        body = {
            "instId": inst_id,
            "tdMode": (td_mode or self.td_mode),
            "side": side.lower(),
            "ordType": ord_type.lower(),
            "sz": str(sz),
        }
        if px is not None:
            body["px"] = str(px)
        if pos_side:
            body["posSide"] = pos_side.lower()
        elif self.pos_mode == "long_short_mode":
            body["posSide"] = "long" if side.lower() == "buy" else "short"
        if cl_ord_id is None:
            cl_ord_id = "cert" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        body["clOrdId"] = cl_ord_id
        attempts = 0
        while True:
            attempts += 1
            try:
                envelope = self._request("POST", "/api/v5/trade/order", body=body, is_write=True)
                item = (envelope.get("data") or [{}])[0]
                s_code = str(item.get("sCode", "0"))
                if s_code != "0":
                    raise OkxApiError(s_code, item.get("sMsg", ""), method="POST", path="/api/v5/trade/order")
                item["_cl_ord_id"] = cl_ord_id
                return item
            except OkxApiError as exc:
                code = str(exc.code)
                # 50013 "systems busy" precedes order creation; retry with the
                # SAME clOrdId so a lost reply can never duplicate the order.
                if code == "50013" and attempts < 6:
                    time.sleep(min(2.0 * attempts, 8.0))
                    continue
                if code == "51016":  # clOrdId already exists: the order landed
                    rows = self.order_details(inst_id, cl_ord_id=cl_ord_id)
                    if rows:
                        item = dict(rows[0])
                        item["_cl_ord_id"] = cl_ord_id
                        item["_dedupe"] = True
                        return item
                raise

    def cancel_order(self, inst_id, *, ord_id=None, cl_ord_id=None):
        body = {"instId": inst_id}
        if ord_id:
            body["ordId"] = ord_id
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        if "ordId" not in body and "clOrdId" not in body:
            raise ValueError("order identity required")
        envelope = self._request("POST", "/api/v5/trade/cancel-order", body=body, is_write=True)
        item = (envelope.get("data") or [{}])[0]
        s_code = str(item.get("sCode", "0"))
        if s_code != "0":
            raise OkxApiError(s_code, item.get("sMsg", ""), method="POST", path="/api/v5/trade/cancel-order")
        return item
