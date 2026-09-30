"""One read-only USD-M demo account query; never a certification case result.

Run the CLI for a process-enforced deadline, including DNS and TLS setup.
No external SDK, proxy environment, redirects, retries or trading operations.
"""

import argparse
import hashlib
import hmac
import http.client
import json
import multiprocessing
from pathlib import Path
import re
import ssl
import subprocess
import time
from urllib.parse import urlencode


HOST = "demo-fapi.binance.com"
BASE_URL = "https://" + HOST
ACCOUNT_PATH = "/fapi/v3/account"
SOCKET_TIMEOUT = 5
PROCESS_TIMEOUT = 20
MAX_BODY = 256 * 1024
MAX_ENV = 64 * 1024
KEY_NAME = "BINANCE_DEMO_API_KEY"
SECRET_NAME = "BINANCE_DEMO_SECRET"


def _result(reason):
    return {
        "schema_version": 1,
        "kind": "binance_usdm_demo_direct_account_preflight",
        "observed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "endpoint": BASE_URL,
        "method": "GET",
        "path": ACCOUNT_PATH,
        "environment_binding": "FIXED_OFFICIAL_DEMO_HOST",
        "connectivity": "UNVERIFIED",
        "authentication": "UNVERIFIED",
        "preflight": "BLOCKED",
        "reason": reason,
        "strict_case_results": "NOT_EVALUATED",
        "strict_cases_passed": 0,
        "order_requests": 0,
        "cancel_requests": 0,
    }


def load_credentials(env_path):
    """Read only the two literal values, without shell execution/interpolation."""
    path = Path(env_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("credential_file_unavailable")
    with path.open("rb") as source:
        data = source.read(MAX_ENV + 1)
    if len(data) > MAX_ENV:
        raise ValueError("credential_file_invalid")
    values = {}
    for line in data.decode("utf-8-sig").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if name not in (KEY_NAME, SECRET_NAME):
            continue
        if not separator or name in values:
            raise ValueError("credential_file_invalid")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # HMAC keys are literal ASCII; reject whitespace, interpolation and headers.
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", value):
            raise ValueError("credential_file_invalid")
        values[name] = value
    if set(values) != {KEY_NAME, SECRET_NAME}:
        raise ValueError("credentials_missing")
    return values[KEY_NAME], values[SECRET_NAME]


def run_preflight(api_key, secret, *, connection_factory=None, timestamp_ms=None):
    """Perform the single GET. The CLI additionally enforces a wall-clock deadline."""
    result = _result("transport_unavailable")
    connection = None
    try:
        query = urlencode(
            {
                "timestamp": int(time.time() * 1000) if timestamp_ms is None else timestamp_ms,
                "recvWindow": 5000,
            }
        )
        signature = hmac.new(secret.encode("ascii"), query.encode("ascii"), hashlib.sha256)
        path = ACCOUNT_PATH + "?" + query + "&signature=" + signature.hexdigest()
        factory = connection_factory or http.client.HTTPSConnection
        connection = factory(HOST, timeout=SOCKET_TIMEOUT, context=ssl.create_default_context())
        connection.request(
            "GET", path, headers={"X-MBX-APIKEY": api_key, "Accept": "application/json"}
        )
        response = connection.getresponse()
        result["connectivity"] = "HTTPS_RESPONSE_RECEIVED"
        # Status is an integer supplied by HTTP framing; no headers/body/error text escape.
        status = response.status
        result["http_status"] = status
        if 300 <= status < 400:
            result["reason"] = "redirect_refused"
            return result
        if status != 200:
            result["reason"] = "http_rejected"
            if status in (401, 403):
                result["authentication"] = "NOT_ESTABLISHED"
            return result
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            result["reason"] = "response_too_large"
            return result
        payload = json.loads(body)
        # V3 has no stable account identifier or canTrade field. Do not invent either.
        if (
            not isinstance(payload, dict)
            or "code" in payload
            or not isinstance(payload.get("assets"), list)
            or not isinstance(payload.get("positions"), list)
            or not isinstance(payload.get("totalWalletBalance"), str)
            or not re.fullmatch(r"-?\d{1,40}(?:\.\d{1,30})?", payload["totalWalletBalance"])
        ):
            result["reason"] = "account_response_invalid"
            return result
        result.update(
            authentication="SIGNED_ACCOUNT_QUERY_ACCEPTED",
            preflight="OBSERVED",
            reason="read_only_account_response_observed",
        )
        return result
    except Exception:
        # Exception messages may contain headers, signatures, URLs or account data.
        result["reason"] = "transport_or_response_error"
        return result
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _worker(send_pipe):
    try:
        root = Path(__file__).resolve().parents[3]
        # Refuse a tracked or nonignored secret file, without reading its contents.
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        if ignored.returncode != 0:
            result = _result("credential_file_not_git_ignored")
        else:
            credentials = load_credentials(root / ".env")
            result = run_preflight(*credentials)
    except Exception:
        result = _result("credentials_unavailable_or_invalid")
    try:
        send_pipe.send(result)
    finally:
        send_pipe.close()


def supervised_preflight():
    """Kill the one-request child at the deadline, even if DNS/read stalls."""
    context = multiprocessing.get_context("spawn")
    receive_pipe, send_pipe = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(send_pipe,), daemon=True)
    try:
        process.start()
        send_pipe.close()
        if receive_pipe.poll(PROCESS_TIMEOUT):
            return receive_pipe.recv()
        return _result("process_deadline_exceeded")
    except Exception:
        return _result("preflight_worker_failed")
    finally:
        if process.pid is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        receive_pipe.close()
        send_pipe.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = supervised_preflight()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["preflight"] == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
