"""Bounded, read-only OKX demo authentication check; never certification evidence.

Protocol reference: https://www.okx.com/docs-v5/en/#overview-rest-authentication
Demo/region reference: https://www.okx.com/docs-v5/en/#overview-demo-trading-services
"""

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import multiprocessing
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path


ENDPOINTS = {
    "global": ("https://openapi.okx.com", "https://www.okx.com"),
    "us": ("https://us.okx.com",),
    "eea": ("https://eea.okx.com",),
}
CREDENTIAL_NAMES = ("OKX_DEMO_API_KEY", "OKX_DEMO_SECRET", "OKX_DEMO_PASSPHRASE")
PUBLIC_TIME = "/api/v5/public/time"
ACCOUNT_CONFIG = "/api/v5/account/config"
MAX_BYTES = 65536
SOCKET_TIMEOUT = 5.0
WALL_TIMEOUT = 20.0


class PreflightError(Exception):
    """Contains a fixed diagnostic code, never provider or credential text."""


def _credentials(env_file):
    # Read only the dedicated demo names. Never load a shell, interpolate values,
    # import unrelated credentials, or mutate the calling process environment.
    try:
        with Path(env_file).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise PreflightError("credentials_file_too_large")
        lines = raw.decode("utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise PreflightError("credentials_file_unavailable") from None
    values = {}
    for line in lines:
        key, separator, value = line.strip().partition("=")
        if separator and key.strip() in CREDENTIAL_NAMES:
            key = key.strip()
            value = value.strip()
            if key in values:
                raise PreflightError("duplicate_demo_credential")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise PreflightError("invalid_demo_credential")
                value = value[1:-1]
            if not value or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise PreflightError("invalid_demo_credential")
            values[key] = value
    if set(values) != set(CREDENTIAL_NAMES):
        raise PreflightError("missing_demo_credentials")
    return values


def _https_get(host, path, headers, timeout):
    """Direct verified HTTPS only; no proxy discovery, redirects, or retries."""
    if path not in (PUBLIC_TIME, ACCOUNT_CONFIG):
        raise PreflightError("request_path_not_allowed")
    connection = http.client.HTTPSConnection(
        host, timeout=timeout, context=ssl.create_default_context()
    )
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            # In particular never follow a 3xx with credentials.
            raise PreflightError("http_response_rejected")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise PreflightError("response_too_large")
        return body
    finally:
        connection.close()


def _data(body):
    if not isinstance(body, bytes) or len(body) > MAX_BYTES:
        raise PreflightError("invalid_response")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise PreflightError("invalid_response") from None
    if not isinstance(payload, dict) or payload.get("code") != "0":
        raise PreflightError("api_response_rejected")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise PreflightError("invalid_response")
    return data[0]


def _report():
    return {
        "schema_version": 1,
        "venue": "okx",
        "environment": "demo",
        "scope": "DIRECT_READ_ONLY_ACCOUNT_PREFLIGHT",
        "status": "BLOCKED",
        "reason": "not_started",
        "connectivity": False,
        "authenticated": False,
        "requests_attempted": 0,
        "order_requests": 0,
        "cancel_requests": 0,
        "requested_product": "SWAP",
        "swap_eligibility": "NOT_CHECKED",
        "certification_status": "NOT_RUN",
        "certification_cases_passed": 0,
        "certification_cases_total": 33,
    }


def run_preflight(region, endpoint, env_file, *, transport=None):
    """Return only allowlisted facts. CLI adds a hard process wall deadline.

    ``transport`` is an offline-test seam, not a managed certification backend.
    Socket timeouts alone cannot bound DNS resolution; use the supervised CLI
    for a real request. A successful result never grants trading permission.
    """
    report = _report()
    if region not in ENDPOINTS or endpoint not in ENDPOINTS[region]:
        report["reason"] = "explicit_region_endpoint_required"
        return report
    report.update(region=region, endpoint=endpoint)
    transport = transport or _https_get
    try:
        credentials = _credentials(env_file)
        headers = {"Content-Type": "application/json", "x-simulated-trading": "1"}
        report["requests_attempted"] += 1
        server = _data(transport(endpoint[8:], PUBLIC_TIME, headers.copy(), SOCKET_TIMEOUT))
        server_time = server.get("ts")
        if not isinstance(server_time, str) or not re.fullmatch(r"[0-9]{13}", server_time):
            raise PreflightError("invalid_server_time")
        timestamp = (
            datetime.fromtimestamp(int(server_time) / 1000, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        report["connectivity"] = True
        signature = base64.b64encode(
            hmac.new(
                credentials["OKX_DEMO_SECRET"].encode("ascii"),
                (timestamp + "GET" + ACCOUNT_CONFIG).encode("ascii"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        headers.update(
            {
                "OK-ACCESS-KEY": credentials["OKX_DEMO_API_KEY"],
                "OK-ACCESS-PASSPHRASE": credentials["OKX_DEMO_PASSPHRASE"],
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-SIGN": signature,
            }
        )
        report["requests_attempted"] += 1
        account = _data(transport(endpoint[8:], ACCOUNT_CONFIG, headers, SOCKET_TIMEOUT))
        # The provider response can contain uid, mainUid, label and IP addresses.
        # None are copied, hashed, printed or persisted in this diagnostic.
        if (
            account.get("acctLv") not in ("1", "2", "3", "4")
            or account.get("posMode") not in ("net_mode", "long_short_mode")
            or not isinstance(account.get("uid"), str)
            or not re.fullmatch(r"[0-9]{1,32}", account["uid"])
        ):
            raise PreflightError("invalid_account_configuration")
        report.update(
            status="PREFLIGHT_OK",
            reason="demo_account_authenticated",
            authenticated=True,
            account_level=account["acctLv"],
            position_mode=account["posMode"],
        )
    except PreflightError as exc:
        # All locally raised codes are fixed; never emit remote response text.
        report["reason"] = str(exc) if transport is _https_get else "preflight_rejected"
    except Exception:
        # HTTP exceptions can embed request data; do not format or chain them.
        report["reason"] = "transport_or_response_failure"
    return report


def _worker(sender, region, endpoint, env_file):
    try:
        sender.send(run_preflight(region, endpoint, env_file))
    finally:
        sender.close()


def supervised_preflight(region, endpoint, env_file):
    """Hard wall deadline also covers DNS, TLS and slow response streams."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, region, endpoint, str(env_file)))
    report = _report()
    report["reason"] = "worker_failed"
    report["requests_attempted"] = None  # Unknown if the child dies or times out.
    started = time.monotonic()
    try:
        process.start()
        sender.close()
        remaining = max(0.0, WALL_TIMEOUT - (time.monotonic() - started))
        if receiver.poll(remaining):
            try:
                report = receiver.recv()
            except EOFError:
                pass
        else:
            report["reason"] = "wall_deadline_exceeded"
        process.join(timeout=0.1)
    except Exception:
        # A spawn/pipe failure must not produce an unredacted traceback.
        report["reason"] = "worker_failed"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
        receiver.close()
        sender.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True, choices=tuple(ENDPOINTS))
    parser.add_argument("--endpoint", required=True, help="Exact official HTTPS origin for region")
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parents[3] / ".env"
    )
    args = parser.parse_args(argv)
    report = supervised_preflight(args.region, args.endpoint, args.env_file)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PREFLIGHT_OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
