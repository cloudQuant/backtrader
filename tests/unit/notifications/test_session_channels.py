"""AC32-17 / AC32-18: session-anchored channels (WeChat ClawBot, QQ bot).

Only framework behaviour is asserted here. The iLink protocol itself is not
officially documented, so real delivery is out of scope for these tests - they
pin the anchor state machine, the failure classification and credential
handling, which is what the acceptance case requires.
"""

import json
import os
import stat

import pytest

import backtrader as bt
from backtrader.notifications import session as notify_session

from .conftest import FakeTransport, json_response


def _clawbot(*, context_token=None, transport=None, **options):
    """Configure a ClawBot channel and return its transport."""
    transport = transport if transport is not None else FakeTransport()
    config = {"channel": "wechat_clawbot", "bot_token": "bot-token", "to_user_id": "u-1"}
    if context_token:
        config["context_token"] = context_token
    bt.configure_notifications([config], transport=transport, **options)
    return transport


def test_clawbot_unbound_reports_not_bound_without_network():
    """An unbound ClawBot fails fast and never touches the network."""
    transport = _clawbot()
    outcome = bt.send_message("hello", wait=True).outcomes[0]
    assert outcome.ok is False
    assert outcome.error_category == "not_bound"
    assert outcome.attempts == 1
    assert transport.requests == []


def test_clawbot_missing_context_token_is_not_bound():
    """A bound bot without a context token still reports ``not_bound``."""
    transport = _clawbot()
    bt.update_anchor("wechat_clawbot", {"bot_token": "t", "to_user_id": "u"})
    outcome = bt.send_message("hello", wait=True).outcomes[0]
    assert outcome.error_category == "not_bound"
    assert "context_token" in outcome.error
    assert transport.requests == []


def test_clawbot_send_body_and_headers_match_the_anchor():
    """A bound send carries the documented fields and a unique client id."""
    transport = _clawbot(context_token="ctx-1")
    outcome = bt.send_message("hello", wait=True).outcomes[0]
    assert outcome.ok is True
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url.endswith(notify_session.CLAWBOT_SEND_PATH)
    assert request.headers["AuthorizationType"] == "ilink_bot_token"
    assert request.headers["Authorization"].startswith("Bearer ")
    assert request.headers.get("X-WECHAT-UIN")
    payload = json.loads(request.body.decode("utf-8"))
    message = payload["msg"]
    assert message["from_user_id"] == ""
    assert message["to_user_id"] == "u-1"
    assert message["message_type"] == 2
    assert message["message_state"] == 2
    assert message["context_token"] == "ctx-1"
    assert payload["base_info"]["channel_version"]
    assert message["item_list"][0]["text_item"]["text"]

    # Client ids must differ between sends.
    bt.send_message("again", wait=True)
    first = json.loads(transport.requests[0].body.decode("utf-8"))["msg"]["client_id"]
    second = json.loads(transport.requests[1].body.decode("utf-8"))["msg"]["client_id"]
    assert first != second


def test_clawbot_refresh_window_is_enforced():
    """The proactive send window stops at the threshold instead of silently failing."""
    transport = _clawbot(context_token="ctx-1")
    threshold = notify_session.CLAWBOT_REFRESH_THRESHOLD
    for index in range(threshold):
        outcome = bt.send_message("m{0}".format(index), wait=True).outcomes[0]
        assert outcome.ok is True, "send {0} should succeed".format(index)
    assert len(transport.requests) == threshold

    exhausted = bt.send_message("one too many", wait=True).outcomes[0]
    assert exhausted.ok is False
    assert exhausted.error_category == "not_bound"
    assert "refresh window exhausted" in exhausted.error
    assert len(transport.requests) == threshold, "no request for the blocked send"


def test_clawbot_inbound_message_refreshes_the_anchor():
    """A poll that returns a message resets the window and the token."""

    def handler(request):
        if request.url.endswith(notify_session.CLAWBOT_UPDATES_PATH):
            return json_response(
                {
                    "ret": 0,
                    "get_updates_buf": "cursor-1",
                    "msgs": [
                        {
                            "from_user_id": "u-1",
                            "context_token": "ctx-fresh",
                            "item_list": [{"type": 1, "text_item": {"text": "ping"}}],
                        }
                    ],
                }
            )
        return json_response({"ret": 0})

    transport = _clawbot(context_token="ctx-old", transport=FakeTransport(handler=handler))
    for _ in range(notify_session.CLAWBOT_REFRESH_THRESHOLD):
        bt.send_message("before", wait=True)
    assert bt.send_message("blocked", wait=True).outcomes[0].error_category == "not_bound"

    assert bt.poll_clawbot_once() == 1
    refreshed = bt.send_message("after refresh", wait=True).outcomes[0]
    assert refreshed.ok is True
    sends = [r for r in transport.requests if r.url.endswith(notify_session.CLAWBOT_SEND_PATH)]
    assert json.loads(sends[-1].body.decode("utf-8"))["msg"]["context_token"] == "ctx-fresh"


def test_clawbot_poll_classifies_transport_failure():
    """A failing poll is classified, not raised."""
    from backtrader.notifications.transport import TransportError

    transport = FakeTransport(handler=lambda request: TransportError("network", "unreachable"))
    _clawbot(context_token="ctx", transport=transport)
    assert bt.poll_clawbot_once() == 0


def test_anchor_persistence_uses_owner_only_permissions(tmp_path):
    """Anchor files are written with mode 0600 under a 0700 directory."""
    path = tmp_path / "nested" / "wechat_clawbot.json"
    notify_session.persist_anchor(str(path), {"bot_token": "t", "to_user_id": "u"})
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert notify_session.load_anchor(str(path))["bot_token"] == "t"


def test_bind_clawbot_runs_the_qr_flow_and_persists(tmp_path):
    """The QR flow stores the anchor and applies it to the live driver."""
    transport = FakeTransport(
        responses=[
            json_response({"qrcode_url": "https://example.com/qr", "qrcode_id": "id-1"}),
            json_response({"status": "waiting"}),
            json_response({"bot_token": "bot-1", "to_user_id": "u-9", "context_token": "ctx-9"}),
        ]
    )
    bt.configure_notifications(
        [{"channel": "wechat_clawbot", "bot_token": "old", "to_user_id": "u-1"}],
        transport=transport,
    )
    seen = []
    anchor = bt.bind_wechat_clawbot(
        qr_callback=seen.append, persist_path=str(tmp_path / "clawbot.json"), poll_interval=0.0
    )
    assert seen == ["https://example.com/qr"]
    assert anchor["bot_token"] == "bot-1"
    assert (tmp_path / "clawbot.json").exists()

    outcome = bt.send_message("after binding", wait=True).outcomes[0]
    assert outcome.ok is True
    assert outcome.error is None, "a successful outcome never carries credential text"
    sends = [r for r in transport.requests if r.url.endswith(notify_session.CLAWBOT_SEND_PATH)]
    assert json.loads(sends[-1].body.decode("utf-8"))["msg"]["to_user_id"] == "u-9"


def test_bind_clawbot_returns_empty_when_cancelled(tmp_path):
    """A cancelled or expired QR session yields no anchor."""
    transport = FakeTransport(
        responses=[
            json_response({"qrcode_url": "https://example.com/qr"}),
            json_response({"status": "expired"}),
        ]
    )
    bt.configure_notifications(
        [{"channel": "wechat_clawbot", "bot_token": "b", "to_user_id": "u"}], transport=transport
    )
    anchor = bt.bind_wechat_clawbot(persist_path=str(tmp_path / "clawbot.json"), poll_interval=0.0)
    assert anchor == {}
    assert not (tmp_path / "clawbot.json").exists()


def test_bind_clawbot_rejects_a_qr_response_without_target():
    """A malformed QR response is a hard error."""
    transport = FakeTransport(responses=[json_response({"unexpected": True})])
    bt.configure_notifications(
        [{"channel": "wechat_clawbot", "bot_token": "b", "to_user_id": "u"}], transport=transport
    )
    with pytest.raises(ValueError):
        bt.bind_wechat_clawbot(poll_interval=0.0)


# --- QQ ---------------------------------------------------------------------


def _qq(transport=None, **config):
    """Configure a QQ bot channel and return its transport.

    A default transport answers the token endpoint and accepts every message, so
    individual tests only need a handler when they exercise a failure path.
    """
    if transport is None:

        def handler(request):
            if "getAppAccessToken" in request.url:
                return json_response({"access_token": "tok-1", "expires_in": 7200})
            return json_response({"code": 0})

        transport = FakeTransport(handler=handler)
    entry = {"channel": "qq_bot", "appid": "app-1", "appsecret": "sec-1"}
    entry.update(config)
    bt.configure_notifications([entry], transport=transport)
    return transport


def test_qq_unbound_reports_not_bound():
    """Without an openid the channel reports ``not_bound`` and sends nothing."""
    transport = _qq()
    outcome = bt.send_message("hello", wait=True).outcomes[0]
    assert outcome.error_category == "not_bound"
    assert transport.requests == []


def test_qq_single_chat_request_shape():
    """The single-chat endpoint, headers and body follow the documented shape."""
    transport = _qq(user_openid="openid-1")
    outcome = bt.send_message("hello", wait=True).outcomes[0]
    assert outcome.ok is True
    requests = transport.requests
    assert any("getAppAccessToken" in r.url for r in requests)
    sends = [r for r in requests if "/v2/users/openid-1/messages" in r.url]
    assert len(sends) == 1
    assert sends[0].headers["Authorization"].startswith("QQBot ")
    assert json.loads(sends[0].body.decode("utf-8"))["msg_type"] == 0


def test_qq_group_chat_uses_the_group_endpoint():
    """A group anchor switches to the group endpoint."""
    transport = _qq(group_openid="group-1")
    assert bt.send_message("hello", wait=True).outcomes[0].ok is True
    assert any("/v2/groups/group-1/messages" in r.url for r in transport.requests)


def test_qq_token_is_cached_between_sends():
    """The access token is fetched once and reused."""
    transport = _qq(user_openid="openid-1")
    for _ in range(3):
        bt.send_message("x", wait=True)
    token_calls = [r for r in transport.requests if "getAppAccessToken" in r.url]
    assert len(token_calls) == 1


def test_qq_expired_token_is_refreshed_once():
    """An expired-token error triggers one refresh and a retry."""
    state = {"sends": 0, "tokens": 0}

    def handler(request):
        if "getAppAccessToken" in request.url:
            state["tokens"] += 1
            return json_response(
                {"access_token": "tok-{0}".format(state["tokens"]), "expires_in": 7200}
            )
        state["sends"] += 1
        if state["sends"] == 1:
            return json_response({"code": 11241, "message": "token expired"})
        return json_response({"code": 0})

    _qq(transport=FakeTransport(handler=handler), user_openid="openid-1")
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.ok is True
    assert state["tokens"] == 2
    assert state["sends"] == 2


def test_qq_permission_error_is_not_retried():
    """A disabled proactive message is a permission problem, not a retryable one."""

    def handler(request):
        if "getAppAccessToken" in request.url:
            return json_response({"access_token": "tok", "expires_in": 7200})
        return json_response({"code": 40034105, "message": "no permission"})

    transport = _qq(transport=FakeTransport(handler=handler), user_openid="openid-1")
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.error_category == "permission"
    assert outcome.attempts == 1
    sends = [r for r in transport.requests if "/messages" in r.url]
    assert len(sends) == 1


def test_qq_rate_limit_error_is_classified():
    """QQ rate limiting maps onto the rate_limit category."""

    def handler(request):
        if "getAppAccessToken" in request.url:
            return json_response({"access_token": "tok", "expires_in": 7200})
        return json_response({"code": 40034100, "message": "too frequent"})

    _qq(transport=FakeTransport(handler=handler), user_openid="openid-1")
    outcome = bt.send_message("x", wait=True).outcomes[0]
    assert outcome.error_category == "rate_limit"


def test_qq_sandbox_switches_the_base_url():
    """The sandbox flag selects the sandbox host."""
    transport = _qq(user_openid="openid-1", sandbox=True)
    bt.send_message("x", wait=True)
    sends = [r for r in transport.requests if "/messages" in r.url]
    assert notify_session.QQ_SANDBOX_BASE_URL in sends[0].url


def test_bind_qq_bot_requires_an_anchor():
    """Registering without an openid is a programming error."""
    with pytest.raises(ValueError):
        bt.bind_qq_bot()


def test_bind_qq_bot_persists_and_applies_the_anchor(tmp_path):
    """An explicit anchor registration is persisted and applied live."""
    transport = _qq()
    assert bt.send_message("before", wait=True).outcomes[0].error_category == "not_bound"
    path = tmp_path / "qq.json"
    bt.bind_qq_bot(user_openid="openid-9", persist_path=str(path))
    assert path.exists()
    assert bt.send_message("after", wait=True).outcomes[0].ok is True
    assert any("/v2/users/openid-9/messages" in r.url for r in transport.requests)


def test_qq_loads_no_anchor_from_disk_automatically(tmp_path):
    """Anchors are never read implicitly: the default-silence rule holds."""
    path = tmp_path / "qq.json"
    notify_session.persist_anchor(str(path), {"user_openid": "openid-from-disk"})
    _qq()
    # Nothing was configured with the file, so the channel stays unbound.
    assert bt.send_message("x", wait=True).outcomes[0].error_category == "not_bound"


def test_default_anchor_path_is_under_the_user_directory():
    """The documented default anchor location is used."""
    path = bt.default_anchor_path("qq_bot")
    assert path.endswith(os.path.join("notifications", "qq_bot.json"))
