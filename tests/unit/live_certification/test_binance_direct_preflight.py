"""Offline tests: all HTTP and process execution are fakes; no .env secrets read."""

import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


SOURCE = (
    Path(__file__).resolve().parents[3]
    / "examples/000_live_certification/binance_penetration/direct_preflight.py"
)
SPEC = importlib.util.spec_from_file_location("binance_preflight_under_test", SOURCE)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)
KEY = "fake_key_1234567890"
SECRET = "fake_secret_1234567890"


class FakeConnection:
    def __init__(self, status=200, body=None, failure=None):
        self.status = status
        self.body = (
            body
            if body is not None
            else json.dumps(
                {"assets": [], "positions": [], "totalWalletBalance": "123.45", "private": SECRET}
            ).encode()
        )
        self.failure = failure
        self.calls = []
        self.closed = False

    def factory(self, host, **kwargs):
        self.host = host
        self.options = kwargs
        return self

    def request(self, method, path, headers):
        self.calls.append((method, path, headers))
        if self.failure:
            raise self.failure

    def getresponse(self):
        return self

    def read(self, size):
        self.read_limit = size
        return self.body[:size]

    def close(self):
        self.closed = True


def execute(connection):
    return preflight.run_preflight(
        KEY, SECRET, connection_factory=connection.factory, timestamp_ms=1234567890000
    )


def test_exact_demo_get_hmac_and_output_allowlist(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://production.invalid")
    connection = FakeConnection()
    result = execute(connection)
    assert connection.host == "demo-fapi.binance.com"
    assert connection.options["timeout"] == 5
    assert connection.options["context"].check_hostname
    assert len(connection.calls) == 1
    method, path, headers = connection.calls[0]
    assert method == "GET"
    assert urlsplit(path).path == "/fapi/v3/account"
    query, signature = urlsplit(path).query.rsplit("&signature=", 1)
    assert parse_qs(query) == {"timestamp": ["1234567890000"], "recvWindow": ["5000"]}
    assert signature == hmac.new(SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    assert headers["X-MBX-APIKEY"] == KEY
    assert connection.read_limit == preflight.MAX_BODY + 1
    assert connection.closed
    assert result["preflight"] == "OBSERVED"
    assert result["authentication"] == "SIGNED_ACCOUNT_QUERY_ACCEPTED"
    assert result["strict_case_results"] == "NOT_EVALUATED"
    assert (
        result["strict_cases_passed"] == result["order_requests"] == result["cancel_requests"] == 0
    )
    rendered = json.dumps(result)
    for sensitive in (KEY, SECRET, signature, "123.45", "assets", "positions"):
        assert sensitive not in rendered


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 429, 500])
def test_rejections_never_retry_redirect_or_emit_body(status):
    connection = FakeConnection(status=status, body=(KEY + SECRET).encode())
    result = execute(connection)
    assert result["preflight"] == "BLOCKED"
    assert result["authentication"] != "SIGNED_ACCOUNT_QUERY_ACCEPTED"
    assert result["connectivity"] == "HTTPS_RESPONSE_RECEIVED"
    assert result["reason"] == ("redirect_refused" if status < 400 else "http_rejected")
    assert len(connection.calls) == 1
    assert not hasattr(connection, "read_limit")
    assert KEY not in json.dumps(result)
    assert connection.closed


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"code":-2015,"msg":"secret"}',
        b'{"assets":[],"positions":[],"totalWalletBalance":"NaN"}',
        b'{"assets":{},"positions":[],"totalWalletBalance":"1"}',
        b"x" * (preflight.MAX_BODY + 1),
    ],
    ids=["non-json", "array", "empty", "api-error", "nan", "bad-assets", "oversize"],
)
def test_malformed_or_oversize_account_response_is_blocked(body):
    result = execute(FakeConnection(body=body))
    assert result["preflight"] == "BLOCKED"
    assert result["strict_cases_passed"] == 0


def test_transport_exception_never_emits_secret():
    connection = FakeConnection(failure=RuntimeError(KEY + SECRET))
    result = execute(connection)
    assert result["reason"] == "transport_or_response_error"
    assert result["connectivity"] == "UNVERIFIED"
    assert SECRET not in json.dumps(result)
    assert connection.closed


def test_literal_env_only_selected_credentials(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        f"UNRELATED_SECRET=not-returned\nexport {preflight.KEY_NAME}='{KEY}'\n"
        f'{preflight.SECRET_NAME}="{SECRET}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(preflight.KEY_NAME, "ambient_production_key")
    assert preflight.load_credentials(path) == (KEY, SECRET)


@pytest.mark.parametrize(
    "contents",
    [
        "",
        f"{preflight.KEY_NAME}={KEY}\n",
        f"{preflight.KEY_NAME}={KEY}\n{preflight.KEY_NAME}={KEY}\n",
        f"{preflight.KEY_NAME}=${{PRODUCTION_KEY}}\n",
        f"{preflight.KEY_NAME}=$(read-secrets)\n",
        f"{preflight.KEY_NAME}=has spaces inside\n",
        "x" * (preflight.MAX_ENV + 1),
    ],
    ids=["empty", "missing-secret", "duplicate", "interpolation", "shell", "spaces", "oversize"],
)
def test_invalid_env_is_rejected_without_values(tmp_path, contents):
    path = tmp_path / ".env"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        preflight.load_credentials(path)
    assert KEY not in str(caught.value)


def test_supervisor_kills_stalled_worker(monkeypatch):
    class Pipe:
        def poll(self, timeout):
            assert timeout == 20
            return False

        def close(self):
            pass

    class Process:
        pid = 123
        alive = True
        terminated = False

        def start(self):
            pass

        def join(self, timeout):
            assert timeout <= 2

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False

    process = Process()

    class Context:
        def Pipe(self, duplex):
            assert duplex is False
            return Pipe(), Pipe()

        def Process(self, **kwargs):
            assert kwargs["target"] is preflight._worker
            assert kwargs["daemon"] is True
            return process

    monkeypatch.setattr(preflight.multiprocessing, "get_context", lambda method: Context())
    result = preflight.supervised_preflight()
    assert result["reason"] == "process_deadline_exceeded"
    assert result["preflight"] == "BLOCKED"
    assert process.terminated


def test_worker_refuses_nonignored_env_before_reading(monkeypatch):
    class Rejected:
        returncode = 1

    class Pipe:
        def send(self, result):
            self.result = result

        def close(self):
            pass

    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: Rejected())
    monkeypatch.setattr(preflight, "load_credentials", lambda path: pytest.fail("must not read"))
    pipe = Pipe()
    preflight._worker(pipe)
    assert pipe.result["reason"] == "credential_file_not_git_ignored"


def test_help_never_loads_credentials_or_starts_request(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "supervised_preflight", lambda: pytest.fail("no request"))
    with pytest.raises(SystemExit) as caught:
        preflight.main(["--help"])
    assert caught.value.code == 0
    assert "read-only" in capsys.readouterr().out
