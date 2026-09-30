"""Offline contract tests: no OKX connections or account credentials are used."""

import base64
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "examples/000_live_certification/okx_penetration/direct_preflight.py"
)
SPEC = importlib.util.spec_from_file_location("okx_direct_preflight_test_subject", SCRIPT)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "UNRELATED_PRODUCTION_SECRET=do-not-load\n"
        "OKX_DEMO_API_KEY='fake-demo-key'\n"
        'OKX_DEMO_SECRET="fake-demo-secret"\n'
        "OKX_DEMO_PASSPHRASE=fake-demo-passphrase\n",
        encoding="utf-8",
    )
    return path


def response(data, **extra):
    return json.dumps({"code": "0", "data": [data], **extra}).encode()


def good_account():
    return {"uid": "123456789", "acctLv": "2", "posMode": "net_mode", "label": "PRIVATE"}


class FakeTransport:
    def __init__(self, account=None):
        self.calls = []
        self.replies = [
            response({"ts": "1607418537715"}),
            response(good_account() if account is None else account),
        ]

    def __call__(self, host, path, headers, timeout):
        self.calls.append((host, path, headers, timeout))
        return self.replies.pop(0)


def run(env_file, transport):
    return preflight.run_preflight(
        "global", "https://openapi.okx.com", env_file, transport=transport
    )


def test_only_two_read_only_demo_requests_and_official_signature(env_file):
    fake = FakeTransport()
    report = run(env_file, fake)
    assert report["status"] == "PREFLIGHT_OK"
    assert report["connectivity"] and report["authenticated"]
    assert report["certification_status"] == "NOT_RUN"
    assert report["certification_cases_passed"] == 0
    assert report["swap_eligibility"] == "NOT_CHECKED"
    assert report["order_requests"] == report["cancel_requests"] == 0
    assert len(fake.calls) == 2
    public, account = fake.calls
    assert public[:2] == ("openapi.okx.com", "/api/v5/public/time")
    assert account[:2] == ("openapi.okx.com", "/api/v5/account/config")
    assert "OK-ACCESS-KEY" not in public[2]
    for call in fake.calls:
        assert call[2]["x-simulated-trading"] == "1"
        assert 0 < call[3] <= 5
    headers = account[2]
    assert headers["OK-ACCESS-TIMESTAMP"] == "2020-12-08T09:08:57.715Z"
    expected = base64.b64encode(
        hmac.new(
            b"fake-demo-secret",
            b"2020-12-08T09:08:57.715ZGET/api/v5/account/config",
            hashlib.sha256,
        ).digest()
    ).decode()
    assert headers["OK-ACCESS-SIGN"] == expected
    assert headers["OK-ACCESS-KEY"] == "fake-demo-key"
    assert headers["OK-ACCESS-PASSPHRASE"] == "fake-demo-passphrase"
    serialized = json.dumps(report)
    for secret in ("fake-demo", "123456789", "PRIVATE", expected, "do-not-load"):
        assert secret not in serialized


@pytest.mark.parametrize(
    "region,endpoint",
    [
        (None, "https://openapi.okx.com"),
        ("global", None),
        ("us", "https://openapi.okx.com"),
        ("eea", "https://www.okx.com"),
        ("global", "http://openapi.okx.com"),
        ("global", "https://openapi.okx.com/"),
        ("global", "https://openapi.okx.com:443"),
        ("global", "https://openapi.okx.com.evil.test"),
        ("global", "https://user:secret@openapi.okx.com"),
        ("global", "https://openapi.okx.com?mode=production"),
    ],
)
def test_rejects_unbound_endpoints_without_loading_credentials(region, endpoint, tmp_path):
    fake = FakeTransport()
    report = preflight.run_preflight(region, endpoint, tmp_path / "absent", transport=fake)
    assert report["reason"] == "explicit_region_endpoint_required"
    assert fake.calls == []


@pytest.mark.parametrize(
    "region,endpoint",
    [
        ("global", "https://www.okx.com"),
        ("us", "https://us.okx.com"),
        ("eea", "https://eea.okx.com"),
    ],
)
def test_explicit_regions_have_no_fallback(env_file, region, endpoint):
    fake = FakeTransport()
    report = preflight.run_preflight(region, endpoint, env_file, transport=fake)
    assert report["status"] == "PREFLIGHT_OK"
    assert {call[0] for call in fake.calls} == {endpoint[8:]}


@pytest.mark.parametrize(
    "content",
    [
        "",
        "OKX_API_KEY=production\nOKX_API_SECRET=production\n",
        "OKX_DEMO_API_KEY=a\nOKX_DEMO_API_KEY=b\n",
        "OKX_DEMO_API_KEY='unterminated\n",
        "OKX_DEMO_API_KEY=has space\n",
        "x" * 65537,
    ],
    ids=["empty", "production", "duplicate", "unclosed-quote", "whitespace", "oversized"],
)
def test_invalid_credentials_never_contact_provider(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    fake = FakeTransport()
    assert run(path, fake)["status"] == "BLOCKED"
    assert fake.calls == []


@pytest.mark.parametrize(
    "reply",
    [
        b"not-json",
        b"[]",
        b"{}",
        b'{"code":"50101","msg":"fake-demo-secret"}',
        response({"ts": "garbage"}),
        response({"ts": 1607418537715}),
        b"x" * 65537,
    ],
    ids=["invalid-json", "array", "empty", "api-error", "bad-ts", "integer-ts", "oversized"],
)
def test_public_failure_stops_before_auth_and_redacts(env_file, reply):
    fake = FakeTransport()
    fake.replies[0] = reply
    report = run(env_file, fake)
    assert len(fake.calls) == 1
    assert not report["authenticated"]
    assert "fake-demo" not in json.dumps(report)


@pytest.mark.parametrize(
    "account",
    [
        {},
        {"uid": "secret", "acctLv": "2", "posMode": "net_mode"},
        {"uid": "1", "acctLv": "bogus", "posMode": "net_mode"},
        {"uid": "1", "acctLv": "2", "posMode": "bogus"},
    ],
)
def test_malformed_account_never_authenticates(env_file, account):
    report = run(env_file, FakeTransport(account))
    assert report["connectivity"] and not report["authenticated"]
    assert report["status"] == "BLOCKED"


def test_transport_exception_does_not_echo_secret(env_file):
    def failing(*args):
        raise OSError("secret=must-never-appear")

    report = run(env_file, failing)
    assert report["reason"] == "transport_or_response_failure"
    assert "must-never-appear" not in json.dumps(report)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 429, 500])
def test_real_transport_never_follows_redirect_or_retries(monkeypatch, status):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def request(self, method, path, **kwargs):
            assert method == "GET"

        def getresponse(self):
            return type("Response", (), {"status": status})()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(preflight.http.client, "HTTPSConnection", Connection)
    with pytest.raises(preflight.PreflightError, match="http_response_rejected"):
        preflight._https_get("openapi.okx.com", preflight.ACCOUNT_CONFIG, {}, 5)
    assert len(calls) == 2 and calls[-1] == "closed"
    assert calls[0][1]["context"].check_hostname


def test_transport_caps_body_and_closes_connection(monkeypatch):
    events = []

    class Response:
        status = 200

        def read(self, limit):
            assert limit == 65537
            return b"x" * limit

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            events.append("closed")

    monkeypatch.setattr(preflight.http.client, "HTTPSConnection", Connection)
    with pytest.raises(preflight.PreflightError, match="response_too_large"):
        preflight._https_get("openapi.okx.com", preflight.PUBLIC_TIME, {}, 5)
    assert events == ["closed"]


def test_transport_rejects_order_routes_before_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("must not open a connection")

    monkeypatch.setattr(preflight.http.client, "HTTPSConnection", forbidden)
    with pytest.raises(preflight.PreflightError, match="request_path_not_allowed"):
        preflight._https_get("openapi.okx.com", "/api/v5/trade/order", {}, 5)


def test_cli_spawn_path_with_missing_credentials_never_connects(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--region",
            "global",
            "--endpoint",
            "https://openapi.okx.com",
            "--env-file",
            str(tmp_path / "missing"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["reason"] == "credentials_file_unavailable"
    assert report["requests_attempted"] == 0
    assert not result.stderr


def test_cli_requires_region_and_endpoint_without_default():
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, timeout=10)
    assert result.returncode == 2
    assert b"--region" in result.stderr and b"--endpoint" in result.stderr


def test_supervisor_terminates_stalled_dns_worker_without_waiting_forever(monkeypatch):
    events = []

    class Pipe:
        def poll(self, timeout):
            assert 0 <= timeout <= preflight.WALL_TIMEOUT
            return False

        def close(self):
            events.append("pipe_closed")

    class Process:
        alive = True

        def start(self):
            events.append("started")

        def join(self, timeout):
            assert timeout <= 1

        def is_alive(self):
            return self.alive

        def terminate(self):
            events.append("terminated")
            self.alive = False

    class Context:
        def Pipe(self, duplex):
            assert not duplex
            return Pipe(), Pipe()

        def Process(self, **kwargs):
            return Process()

    monkeypatch.setattr(preflight.multiprocessing, "get_context", lambda mode: Context())
    report = preflight.supervised_preflight("global", "https://openapi.okx.com", "unused")
    assert report["reason"] == "wall_deadline_exceeded"
    assert report["requests_attempted"] is None
    assert report["status"] == "BLOCKED"
    assert "terminated" in events
