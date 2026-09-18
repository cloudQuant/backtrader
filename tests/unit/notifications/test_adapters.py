"""AC32-08: account-backed channels (email, WeCom app) and Telegram 429."""

import pytest

import backtrader as bt
from backtrader.notifications.transport import SmtpError

from .conftest import FakeSmtp, FakeTransport, json_response, text_response


def test_email_sends_html_with_smtp_ssl_for_port_465(notifier_env):
    """Port 465 implies implicit TLS; the subject carries the level prefix."""
    smtp = FakeSmtp()
    notifier_env(
        [
            {
                "channel": "email",
                "host": "smtp.example.com",
                "port": 465,
                "user": "bot@example.com",
                "password": "pw",
                "to": ["a@example.com", "b@example.com"],
                "html": True,
            }
        ],
        smtp=smtp,
    )
    result = bt.send_message("<b>hello</b>", title="Report", level="warning", wait=True)

    assert result.outcomes[0].ok is True
    envelope = smtp.envelopes[-1]
    assert envelope.use_ssl is True
    assert envelope.use_starttls is False
    assert envelope.subject == "[WARNING] Report"
    assert envelope.recipients == ("a@example.com", "b@example.com")
    assert envelope.sender == "bot@example.com"
    assert envelope.html is True
    assert "<b>hello</b>" in envelope.body


def test_email_uses_starttls_for_port_587(notifier_env):
    """Port 587 implies STARTTLS."""
    smtp = FakeSmtp()
    notifier_env(
        [
            {
                "channel": "email",
                "host": "smtp.example.com",
                "port": 587,
                "user": "bot@example.com",
                "password": "pw",
                "to": ["a@example.com"],
            }
        ],
        smtp=smtp,
    )
    bt.send_message("plain body", wait=True)
    assert smtp.envelopes[-1].use_starttls is True
    assert smtp.envelopes[-1].use_ssl is False


def test_email_auth_failure_is_classified_and_not_retried(notifier_env):
    """An SMTP auth error maps to ``auth`` with a single attempt."""
    smtp = FakeSmtp(error=SmtpError("auth", "535 rejected"))
    notifier_env(
        [
            {
                "channel": "email",
                "host": "smtp.example.com",
                "port": 465,
                "user": "u",
                "password": "p",
                "to": ["a@example.com"],
            }
        ],
        smtp=smtp,
    )
    result = bt.send_message("x", wait=True)
    outcome = result.outcomes[0]
    assert outcome.ok is False
    assert outcome.error_category == "auth"
    assert outcome.attempts == 1
    assert bt.notification_stats()["email"]["retried"] == 0


def test_email_timeout_is_classified(notifier_env):
    """An SMTP timeout maps to ``timeout``."""
    smtp = FakeSmtp(error=SmtpError("timeout", "no response"))
    notifier_env(
        [
            {
                "channel": "email",
                "host": "smtp.example.com",
                "port": 465,
                "user": "u",
                "password": "p",
                "to": ["a@example.com"],
            }
        ],
        smtp=smtp,
    )
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.error_category == "timeout"


def test_email_requires_non_empty_recipients(notifier_env):
    """An empty recipient list is rejected at configuration time."""
    with pytest.raises(ValueError):
        notifier_env([{"channel": "email", "host": "h", "port": 465, "to": []}], smtp=FakeSmtp())
    with pytest.raises(ValueError):
        notifier_env(
            [{"channel": "email", "host": "h", "port": 465, "to": "a@example.com"}],
            smtp=FakeSmtp(),
        )


def test_wecom_app_fetches_token_once_and_reuses_it(notifier_env):
    """The access token is cached until its expiry."""
    token_calls = []

    def handler(request):
        if "gettoken" in request.url:
            token_calls.append(request.url)
            return json_response({"errcode": 0, "access_token": "tok-1", "expires_in": 7200})
        return json_response({"errcode": 0})

    transport = FakeTransport(handler=handler)
    notifier_env(
        [
            {
                "channel": "wecom_app",
                "corpid": "cp",
                "corpsecret": "sec",
                "agentid": 1001,
                "touser": "alice",
            }
        ],
        transport=transport,
    )
    for _ in range(3):
        assert bt.send_message("x", wait=True).outcomes[0].ok is True

    assert len(token_calls) == 1, "token must be cached across sends"
    sends = [request for request in transport.requests if "message/send" in request.url]
    assert len(sends) == 3
    assert "access_token=tok-1" in sends[-1].url
    assert sends[-1].headers["Content-Type"].startswith("application/json")


def test_wecom_app_refreshes_expired_token_once(notifier_env):
    """An expired-token error triggers exactly one refresh and a retry."""
    token_calls = []
    send_calls = []

    def handler(request):
        if "gettoken" in request.url:
            token_calls.append(request.url)
            return json_response(
                {
                    "errcode": 0,
                    "access_token": "tok-{0}".format(len(token_calls)),
                    "expires_in": 7200,
                }
            )
        send_calls.append(request.url)
        if len(send_calls) == 1:
            return json_response({"errcode": 42001, "errmsg": "access_token expired"})
        return json_response({"errcode": 0})

    transport = FakeTransport(handler=handler)
    notifier_env(
        [
            {
                "channel": "wecom_app",
                "corpid": "cp",
                "corpsecret": "sec",
                "agentid": 1001,
                "touser": "alice",
            }
        ],
        transport=transport,
    )
    result = bt.send_message("x", wait=True)
    assert result.outcomes[0].ok is True
    assert len(token_calls) == 2, "one initial fetch plus exactly one refresh"
    assert len(send_calls) == 2
    assert "access_token=tok-2" in send_calls[-1]


def test_wecom_app_missing_credentials_raise(notifier_env):
    """Missing corpid/corpsecret/agentid/touser is a configuration error."""
    with pytest.raises(ValueError):
        notifier_env([{"channel": "wecom_app", "corpid": "cp", "corpsecret": "s"}])


def test_telegram_429_honours_retry_after(notifier_env):
    """A 429 is waited out using ``parameters.retry_after`` and retried."""
    responses = [
        json_response(
            {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 0.05},
            },
            status=429,
        ),
        json_response({"ok": True, "result": {"message_id": 1}}),
    ]
    transport = FakeTransport(responses=responses)
    notifier_env([{"channel": "telegram", "bot_token": "b", "chat_id": "1"}], transport=transport)
    result = bt.send_message("x", wait=True)
    outcome = result.outcomes[0]
    assert outcome.ok is True
    assert outcome.attempts == 2
    assert len(transport.requests) == 2


def test_telegram_unauthorized_is_not_retried(notifier_env):
    """A 401 is an auth error and is never retried."""
    transport = FakeTransport(
        handler=lambda request: json_response(
            {"ok": False, "error_code": 401, "description": "Unauthorized"}, status=401
        )
    )
    notifier_env([{"channel": "telegram", "bot_token": "b", "chat_id": "1"}], transport=transport)
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.error_category == "auth"
    assert outcome.attempts == 1
    assert len(transport.requests) == 1


def test_slack_requires_literal_ok_body(notifier_env):
    """Slack's success signal is the body ``ok``, not the HTTP status."""
    transport = FakeTransport(default=text_response("no_service"))
    notifier_env(
        [{"channel": "slack", "webhook_url": "https://hooks.slack.com/services/T/B/X"}],
        transport=transport,
    )
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.ok is False
    assert outcome.error_category == "bad_request"
