"""AC32-07 / AC32-10: per-channel request construction and message adaptation."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

import backtrader as bt

from .conftest import FakeTransport, json_response, text_response

# Responses differ per channel: Slack answers with the literal body ``ok`` and
# Bark answers with a JSON ``code``, so the shared default is not enough.
CHANNEL_RESPONSES = {
    "slack": lambda: text_response("ok"),
    "bark": lambda: json_response({"code": 200, "message": "success"}),
}

PAGER_CHANNELS = [
    ({"channel": "dingtalk", "access_token": "tok", "secret": "s3cret"}, "dingtalk"),
    ({"channel": "wecom_bot", "key": "k-1"}, "wecom_bot"),
    ({"channel": "feishu_bot", "token": "t-1"}, "feishu_bot"),
    ({"channel": "telegram", "bot_token": "b-1", "chat_id": "9"}, "telegram"),
    ({"channel": "slack", "webhook_url": "https://hooks.slack.com/services/T/B/X"}, "slack"),
    ({"channel": "discord", "webhook_url": "https://discord.com/api/webhooks/1/abc"}, "discord"),
    ({"channel": "ntfy", "topic": "topic-1"}, "ntfy"),
    ({"channel": "gotify", "base_url": "https://gotify.example.com", "token": "g-1"}, "gotify"),
    ({"channel": "bark", "device_key": "bk-1"}, "bark"),
    (
        {"channel": "webhook", "url": "https://example.com/hook", "body_json": {"m": "{text}"}},
        "webhook",
    ),
]

CHANNEL_IDS = [item[1] for item in PAGER_CHANNELS]


def _send(notifier_env, config, text="body text", **kwargs):
    """Configure one channel, send one message, return (request, parsed, result)."""
    channel_id = config["channel"]
    transport = FakeTransport(default=CHANNEL_RESPONSES.get(channel_id, lambda: None)())
    notifier, transport, _ = notifier_env([config], transport=transport)
    result = bt.send_message(text, wait=True, **kwargs)
    assert len(transport.requests) == 1, "exactly one HTTP request per send"
    return transport.requests[0], urlparse(transport.requests[0].url), result


def _payload(request):
    """Decode a request body as JSON."""
    return json.loads(request.body.decode("utf-8"))


@pytest.mark.parametrize("config,channel_id", PAGER_CHANNELS, ids=CHANNEL_IDS)
def test_request_shape_per_channel(notifier_env, config, channel_id):
    """Every webhook channel produces a well-formed POST with a JSON body."""
    request, parsed, result = _send(notifier_env, config)
    assert request.method == "POST"
    assert parsed.scheme == "https"
    assert request.headers.get("Content-Type", "").startswith("application/json")
    assert isinstance(_payload(request), dict)
    assert result.outcomes[0].channel == channel_id
    assert result.outcomes[0].ok is True


def test_dingtalk_signed_query_carries_token_and_signature(notifier_env):
    """The DingTalk query carries the token, a timestamp and a derived sign."""
    request, parsed, _ = _send(
        notifier_env, {"channel": "dingtalk", "access_token": "tok", "secret": "s3cret"}
    )
    query = parse_qs(parsed.query)
    assert query["access_token"] == ["tok"]
    assert query["timestamp"] and query["sign"]
    assert "s3cret" not in parsed.query


def test_dingtalk_at_all_only_for_critical(notifier_env):
    """The mention-everyone hint is applied to critical messages only."""
    notifier, transport, _ = notifier_env(
        [{"channel": "dingtalk", "access_token": "tok"}], at_all=True
    )
    bt.send_message("critical body", level="critical", wait=True)
    assert _payload(transport.requests[-1])["at"] == {"isAtAll": True}

    bt.send_message("info body", level="info", wait=True)
    assert "at" not in _payload(transport.requests[-1])


def test_dingtalk_without_secret_has_no_signature(notifier_env):
    """A robot without a signing secret is called with the token only."""
    request, parsed, _ = _send(notifier_env, {"channel": "dingtalk", "access_token": "tok"})
    query = parse_qs(parsed.query)
    assert "sign" not in query and "timestamp" not in query


def test_wecom_bot_switches_to_text_for_mentions(notifier_env):
    """WeCom only supports mentions on text messages."""
    _, transport, _ = notifier_env([{"channel": "wecom_bot", "key": "k-1"}])
    bt.send_message("plain", wait=True)
    assert _payload(transport.requests[-1])["msgtype"] == "markdown"

    _, transport2, _ = notifier_env([{"channel": "wecom_bot", "key": "k-1"}], at_all=True)
    bt.send_message("urgent", level="critical", wait=True)
    payload = _payload(transport2.requests[-1])
    assert payload["msgtype"] == "text"
    assert payload["text"]["mentioned_list"] == ["@all"]


def test_wecom_bot_content_comes_from_the_markdown_body(notifier_env):
    """Markdown content is nested where WeCom expects it."""
    request, _, _ = _send(notifier_env, {"channel": "wecom_bot", "key": "k-1"})
    payload = _payload(request)
    assert "[INFO]" in payload["markdown"]["content"]


def test_feishu_uses_plain_text_and_optional_signature(notifier_env):
    """Feishu text messages do not render markdown (M0 correction)."""
    request, _, _ = _send(notifier_env, {"channel": "feishu_bot", "token": "t-1"})
    payload = _payload(request)
    assert payload["msg_type"] == "text"
    assert "timestamp" not in payload and "sign" not in payload

    request, _, _ = _send(
        notifier_env, {"channel": "feishu_bot", "token": "t-1", "secret": "s3cret"}
    )
    payload = _payload(request)
    assert payload["timestamp"] and payload["sign"]


def test_slack_sends_text_field(notifier_env):
    """Slack expects a top-level ``text`` field."""
    request, _, _ = _send(
        notifier_env, {"channel": "slack", "webhook_url": "https://hooks.slack.com/services/T/B/X"}
    )
    assert "[INFO]" in _payload(request)["text"]


def test_discord_sends_content_field(notifier_env):
    """Discord expects a top-level ``content`` field."""
    request, _, _ = _send(
        notifier_env,
        {"channel": "discord", "webhook_url": "https://discord.com/api/webhooks/1/abc"},
    )
    assert "[INFO]" in _payload(request)["content"]


def test_ntfy_publishes_json_with_topic(notifier_env):
    """ntfy uses a JSON publish body so non-ASCII text survives."""
    request, parsed, _ = _send(
        notifier_env, {"channel": "ntfy", "topic": "topic-1"}, text="中文消息"
    )
    payload = _payload(request)
    assert parsed.path == "/"
    assert payload["topic"] == "topic-1"
    assert "中文消息" in payload["message"]


def test_gotify_and_bark_payload_fields(notifier_env):
    """Gotify and Bark use their documented JSON bodies."""
    request, parsed, _ = _send(
        notifier_env,
        {"channel": "gotify", "base_url": "https://gotify.example.com", "token": "g-1"},
    )
    assert parsed.path == "/message"
    assert parse_qs(parsed.query)["token"] == ["g-1"]
    assert _payload(request)["priority"] == 5

    request, parsed, _ = _send(notifier_env, {"channel": "bark", "device_key": "bk-1"})
    assert parsed.path == "/push"
    assert _payload(request)["device_key"] == "bk-1"


def test_webhook_body_json_keeps_multiline_text_valid(notifier_env):
    """A structured JSON body survives newlines and quotes in the message."""
    config = {
        "channel": "webhook",
        "url": "https://example.com/hook",
        "body_json": {"level": "{level}", "title": "{title}", "text": "{text}"},
    }
    request, _, _ = _send(notifier_env, config, text='line1\nline2 "quoted"', title="MyTitle")
    payload = _payload(request)
    assert payload["level"] == "info"
    assert payload["title"] == "MyTitle"
    # ``{text}`` is the adapted body: level prefix + title + the original text.
    assert payload["text"].startswith("[INFO] MyTitle")
    assert payload["text"].endswith('line1\nline2 "quoted"')


def test_webhook_body_template_placeholders_and_brace_escaping(notifier_env):
    """Raw templates substitute placeholders and keep literal braces."""
    config = {
        "channel": "webhook",
        "url": "https://example.com/hook",
        "body_template": "level={level} title={title} raw={{literal}} text={text}",
        "content_type": "text/plain; charset=utf-8",
    }
    request, _, _ = _send(notifier_env, config, text="hello", title="MyTitle")
    body = request.body.decode("utf-8")
    assert "level=info" in body
    assert "title=MyTitle" in body
    assert "raw={literal}" in body
    assert "text=" in body and "hello" in body


def test_webhook_without_template_sends_plain_text(notifier_env):
    """A template is optional; the adapted text is sent as-is."""
    request, _, _ = _send(notifier_env, {"channel": "webhook", "url": "https://example.com/hook"})
    assert request.headers["Content-Type"].startswith("text/plain")
    assert "[INFO]" in request.body.decode("utf-8")


def test_truncation_is_byte_safe_for_wecom(notifier_env):
    """WeCom truncates on a UTF-8 boundary and never splits a character."""
    _, transport, _ = notifier_env([{"channel": "wecom_bot", "key": "k-1"}])
    result = bt.send_message("中" * 2000, wait=True)
    content = _payload(transport.requests[-1])["markdown"]["content"]
    assert "已截断" in content
    assert len(content.encode("utf-8")) < 2048 * 2
    content.encode("utf-8").decode("utf-8")  # must round-trip
    assert bt.notification_stats()["wecom_bot"]["truncated"] == 1
    assert result.outcomes[0].ok is True


def test_truncation_by_character_for_discord(notifier_env):
    """Discord truncates at 2000 characters and reports how much was dropped."""
    _, transport, _ = notifier_env(
        [{"channel": "discord", "webhook_url": "https://discord.com/api/webhooks/1/abc"}]
    )
    bt.send_message("x" * 2500, wait=True)
    content = _payload(transport.requests[-1])["content"]
    removed = len("[INFO]\n" + "x" * 2500) - 2000
    assert "已截断 {0} 字符".format(removed) in content
    assert len(content) < 2100


def test_markdown_is_downgraded_for_plain_channels(notifier_env):
    """Plain-text channels do not receive markdown markers."""
    request, _, _ = _send(
        notifier_env, {"channel": "ntfy", "topic": "t"}, text="**bold** and `code`"
    )
    message = _payload(request)["message"]
    assert "**" not in message and "`" not in message
    assert "bold" in message and "code" in message


def test_telegram_escapes_markdown_v2(notifier_env):
    """Telegram text is escaped so parse_mode=MarkdownV2 never 400s."""
    request, _, _ = _send(
        notifier_env,
        {"channel": "telegram", "bot_token": "b-1", "chat_id": "9"},
        text="a_b *c* [d]",
    )
    payload = _payload(request)
    assert payload["parse_mode"] == "MarkdownV2"
    assert r"a\_b" in payload["text"]
    assert r"\[d\]" in payload["text"]


def test_level_prefix_and_case_insensitive_level(notifier_env):
    """Levels are normalised and prefixed in the payload."""
    request, _, _ = _send(notifier_env, {"channel": "ntfy", "topic": "t"}, level="WARNING")
    assert "[WARNING]" in _payload(request)["message"]


def test_invalid_level_and_empty_text_raise(notifier_env):
    """Programming errors surface immediately and never reach the queue."""
    notifier, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])
    with pytest.raises(ValueError):
        bt.send_message("", wait=True)
    with pytest.raises(ValueError):
        bt.send_message("   ")
    with pytest.raises(ValueError):
        bt.send_message("x", level="verbose", wait=True)
    assert transport.requests == []


def test_context_line_renders_data_and_strategy_names(notifier_env):
    """``data_name``/``strategy`` must reach the message, not just the object."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])
    bt.send_message(
        "signal fired",
        strategy="PairSpreadStrategy",
        data_name="RB889",
        at_time="2026-09-18 09:00:00",
        wait=True,
    )
    lines = _payload(transport.requests[-1])["message"].splitlines()
    assert lines[0] == "[INFO]"
    assert lines[1] == "2026-09-18 09:00:00 strategy=PairSpreadStrategy data=RB889"
    assert lines[2] == "signal fired"


def test_strategy_name_is_not_duplicated_when_title_already_carries_it(notifier_env):
    """Strategy sends put the class name in the title, so it must not repeat."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])
    bt.send_message(
        "entry",
        title="PairSpreadStrategy",
        strategy="PairSpreadStrategy",
        data_name="RB889",
        wait=True,
    )
    message = _payload(transport.requests[-1])["message"]
    lines = message.splitlines()
    assert lines[0] == "[INFO] PairSpreadStrategy"
    assert lines[1] == "data=RB889"
    assert lines[-1] == "entry"
    assert "strategy=" not in message


def test_no_context_line_when_nothing_is_injected(notifier_env):
    """Without context the message keeps its two-line shape."""
    request, _, _ = _send(notifier_env, {"channel": "ntfy", "topic": "t"}, text="plain")
    assert len(_payload(request)["message"].splitlines()) == 2
