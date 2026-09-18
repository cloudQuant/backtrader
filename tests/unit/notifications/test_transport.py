"""AC32-02 / AC32-05: transport contracts and credential masking.

Offline only: the urllib transport is exercised against a monkeypatched
``py3.urlopen`` so the real timeout handling and error normalisation are covered
without touching the network.
"""

import socket
import ssl
from unittest import mock
from urllib import error as urllib_error

import pytest

import backtrader.utils.py3 as py3
from backtrader.notifications.security import mask_text, mask_url
from backtrader.notifications.transport import (
    KIND_NETWORK,
    KIND_TIMEOUT,
    KIND_TLS,
    HttpRequest,
    SmtplibSender,
    TransportError,
    UrllibTransport,
)


class _FakeUrllibResponse:
    """Minimal stand-in for an ``http.client.HTTPResponse``."""

    def __init__(self, body, status=200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.closed = False

    def read(self):
        """Return the recorded body."""
        return self._body

    def close(self):
        """Mark the response as closed."""
        self.closed = True


def test_urllib_transport_sends_headers_body_and_explicit_timeout():
    """The request carries method, headers, body and an explicit timeout."""
    captured = {}

    def fake_urlopen(request, **kwargs):
        captured["request"] = request
        captured["timeout"] = kwargs.get("timeout")
        return _FakeUrllibResponse(b'{"ok": true}')

    with mock.patch.object(py3, "urlopen", fake_urlopen):
        response = UrllibTransport().send(
            HttpRequest(
                method="POST",
                url="https://example.com/hook",
                headers={"X-Test": "1"},
                body=b"{}",
                timeout=3.5,
            )
        )

    assert captured["timeout"] == 3.5
    assert captured["request"].get_method() == "POST"
    assert captured["request"].get_header("X-test") == "1"
    assert response.status == 200
    assert response.text() == '{"ok": true}'
    assert response.elapsed_ms >= 0


def test_urllib_transport_returns_http_error_responses():
    """4xx/5xx come back as responses so the channel layer can classify them."""
    error = urllib_error.HTTPError("https://example.com/hook", 500, "boom", {"X-Retry": "1"}, None)
    error.read = lambda: b'{"errcode": 500}'  # type: ignore[method-assign]

    with mock.patch.object(py3, "urlopen", side_effect=error):
        response = UrllibTransport().send(
            HttpRequest(method="POST", url="https://example.com/hook")
        )

    assert response.status == 500
    assert response.headers == {"x-retry": "1"}
    assert response.text() == '{"errcode": 500}'


def test_urllib_transport_normalises_failures():
    """Timeout, TLS and generic network failures map onto the three kinds."""
    cases = [
        (socket.timeout("slow"), KIND_TIMEOUT),
        (ssl.SSLError("bad cert"), KIND_TLS),
        (OSError("unreachable"), KIND_NETWORK),
        (urllib_error.URLError(socket.timeout("slow")), KIND_TIMEOUT),
        (urllib_error.URLError(ssl.SSLError("bad cert")), KIND_TLS),
        (urllib_error.URLError(OSError("unreachable")), KIND_NETWORK),
    ]
    for exc, expected in cases:
        with mock.patch.object(py3, "urlopen", side_effect=exc), pytest.raises(
            TransportError
        ) as info:
            UrllibTransport().send(
                HttpRequest(method="POST", url="https://example.com/hook?access_token=abc")
            )
        assert info.value.kind == expected
        # The failing URL is masked before it reaches the message.
        assert "abc" not in str(info.value)
        assert "access_token=***" in info.value.url


def test_urllib_transport_decodes_non_utf8_body():
    """Undecodable bytes are replaced rather than raising."""
    with mock.patch.object(py3, "urlopen", lambda *a, **k: _FakeUrllibResponse(b"\xff\xfe ok")):
        response = UrllibTransport().send(HttpRequest(method="GET", url="https://example.com"))
    assert "ok" in response.text()


def test_py3_urlopen_default_timeout_contract_unchanged():
    """The existing py3.urlopen default-timeout contract still holds."""
    with mock.patch.object(py3, "_urllib_request") as request:
        py3.urlopen("https://example.com/data.csv")
    assert request.urlopen.call_args[1]["timeout"] == py3._DEFAULT_URLOPEN_TIMEOUT


def test_mask_url_keeps_scheme_host_path_and_masks_secret_query():
    """Only secret query values are masked."""
    masked = mask_url(
        "https://oapi.dingtalk.com/robot/send?access_token=abc123&sign=xyz&timestamp=99"
    )
    assert masked.startswith("https://oapi.dingtalk.com/robot/send?")
    assert "abc123" not in masked
    assert "xyz" not in masked
    assert "access_token=***" in masked
    assert "sign=***" in masked
    assert "timestamp=99" in masked


def test_mask_text_covers_bearer_values_and_credential_pairs():
    """Bearer tokens, key/value pairs and URL passwords are masked."""
    masked = mask_text(
        'Authorization: Bearer abc.def-123 {"password": "hunter2"} '
        "https://user:secret@example.com/hook webhook_url=https://hooks.slack.com/services/T/B/X"
    )
    assert "hunter2" not in masked
    assert "abc.def-123" not in masked
    assert "secret@" not in masked
    assert "***" in masked


def test_mask_text_masks_qqbot_style_authorization():
    """The QQ bot Authorization scheme is covered as well."""
    masked = mask_text("Authorization: QQBot abcdef123456")
    assert "abcdef123456" not in masked


def test_smtplib_sender_classifies_auth_failure():
    """An SMTP authentication error is classified as ``auth``."""
    import smtplib

    from backtrader.notifications.transport import SmtpEnvelope

    envelope = SmtpEnvelope(
        host="smtp.example.com",
        port=465,
        user="u",
        password="p",
        sender="u@example.com",
        recipients=("a@example.com",),
        subject="[INFO] test",
        body="hello",
        use_ssl=True,
    )
    with mock.patch("smtplib.SMTP_SSL") as smtp_ssl:
        smtp_ssl.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"nope")
        with pytest.raises(Exception) as info:
            SmtplibSender().send(envelope)
    assert getattr(info.value, "kind", None) == "auth"


def test_notifier_and_driver_repr_hide_credentials():
    """repr() of the notifier and of custom drivers must not leak credentials."""
    import backtrader as bt
    from backtrader.notifications.config import get_notifier

    from .conftest import FakeSmtp, FakeTransport

    bt.configure_notifications(
        [
            {
                "channel": "wecom_app",
                "corpid": "corp-id",
                "corpsecret": "super-secret-value",
                "agentid": 1001,
                "touser": "alice",
            },
            {
                "channel": "email",
                "host": "smtp.example.com",
                "port": 465,
                "user": "bot@example.com",
                "password": "mail-password-value",
                "to": ["a@example.com"],
            },
        ],
        transport=FakeTransport(),
        smtp_sender=FakeSmtp(),
    )
    notifier = get_notifier()
    rendered = (
        repr(notifier)
        + repr(notifier.find_instance("wecom_app").driver)
        + repr(notifier.find_instance("email").driver)
    )
    for secret in ("super-secret-value", "mail-password-value", "corp-id"):
        assert secret not in rendered
    assert "wecom_app" in rendered and "email" in rendered
