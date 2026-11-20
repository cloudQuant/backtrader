"""R71-126: a 2xx status alone must not certify channel delivery.

Response shapes are pinned to provider documentation:
- DingTalk: https://open.dingtalk.com/document/robots/custom-robot-access
- WeCom webhook success: https://docs.cloudbase.net/recipes/connect-wecom-webhook-cloud-function
- Feishu custom bot: https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNxkjN?lang=zh-CN%2C
- Bark server: https://github.com/Finb/bark-server/blob/master/router.go
- QQ message send: https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md

Every request below uses an in-process fake transport; no provider is contacted.
"""

import time

import pytest

from backtrader.notifications.channels import CHANNEL_SPECS, Attempt, DeclarativeDriver, Notification
from backtrader.notifications.session import QQ_BOT_SPEC, QqBotDriver

from .conftest import FakeTransport, json_response, text_response


_CHANNEL_CONFIGS = {
    "dingtalk": {"access_token": "test-token"},
    "wecom_bot": {"key": "test-key"},
    "feishu_bot": {"token": "test-token"},
    "bark": {"device_key": "test-key"},
}

_SUCCESS_RESPONSES = [
    ("dingtalk", {"errcode": 0, "errmsg": "ok"}),
    ("wecom_bot", {"errcode": 0, "errmsg": "ok"}),
    ("feishu_bot", {"code": 0, "msg": "success", "data": {}}),
    # Feishu documents StatusCode/StatusMessage as redundant compatibility fields.
    ("feishu_bot", {"StatusCode": 0, "StatusMessage": "success"}),
    ("bark", {"code": 200, "message": "success", "timestamp": 1}),
    # QQ's successful message-send response is id + timestamp, not code=0.
    ("qq_bot", {"id": "message-1", "timestamp": 1}),
]

_ERROR_RESPONSES = [
    ("dingtalk", {"errcode": 310000, "errmsg": "rejected"}),
    ("wecom_bot", {"errcode": 45009, "errmsg": "rate limited"}),
    ("feishu_bot", {"code": 9499, "msg": "Bad Request", "data": {}}),
    ("bark", {"code": 400, "message": "invalid request", "timestamp": 1}),
    ("qq_bot", {"code": 1, "message": "rejected"}),
]


def _deliver_with_response(channel, response):
    """Run the selected production driver against one canned HTTP response."""
    transport = FakeTransport(default=response)
    if channel == "qq_bot":
        driver = QqBotDriver(
            QQ_BOT_SPEC,
            {"appid": "test-app", "appsecret": "test-secret", "user_openid": "user-1"},
            transport,
        )
        # Skip only QQ token acquisition so this test exercises the real message
        # request and response classifier with one controlled HTTP exchange.
        driver._token = "cached-test-token"
        driver._expires_at = time.monotonic() + 60
    else:
        driver = DeclarativeDriver(
            CHANNEL_SPECS[channel], _CHANNEL_CONFIGS[channel], transport
        )

    attempt = driver.deliver(Notification(text="controlled test"))
    assert len(transport.requests) == 1
    return attempt


@pytest.mark.parametrize("channel,payload", _SUCCESS_RESPONSES)
def test_channel_requires_its_documented_success_response(channel, payload):
    attempt = _deliver_with_response(channel, json_response(payload))
    assert attempt == Attempt(True)


@pytest.mark.parametrize("channel,payload", _ERROR_RESPONSES)
def test_channel_error_response_is_not_delivered(channel, payload):
    attempt = _deliver_with_response(channel, json_response(payload))
    assert attempt.ok is False
    assert attempt.category is not None


@pytest.mark.parametrize("channel", ("dingtalk", "wecom_bot", "feishu_bot", "bark", "qq_bot"))
@pytest.mark.parametrize(
    "response",
    (
        text_response("<html>proxy error</html>"),
        text_response(""),
        text_response("[]"),
        text_response("null"),
    ),
    ids=("html", "empty", "array", "null"),
)
def test_non_object_or_empty_2xx_response_is_bad_request(channel, response):
    attempt = _deliver_with_response(channel, response)
    assert attempt.ok is False
    assert attempt.category == "bad_request"


@pytest.mark.parametrize(
    "channel,payload",
    (
        ("dingtalk", {"errmsg": "ok"}),
        ("wecom_bot", {"errmsg": "ok"}),
        ("feishu_bot", {"errcode": 0, "ok": True}),
        ("feishu_bot", {"msg": "success", "data": {}}),
        ("bark", {"message": "success", "timestamp": 1}),
        ("bark", {"errcode": 0, "ok": True}),
        ("qq_bot", {"errcode": 0, "ok": True}),
        ("qq_bot", {"code": 0}),
        ("qq_bot", {"id": "message-1"}),
        ("qq_bot", {"timestamp": 1}),
    ),
)
def test_success_requires_documented_fields(channel, payload):
    attempt = _deliver_with_response(channel, json_response(payload))
    assert attempt.ok is False
    assert attempt.category == "bad_request"
