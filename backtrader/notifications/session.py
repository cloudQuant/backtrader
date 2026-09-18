"""Session-anchored channels: WeChat ClawBot and QQ bot (iteration 32, D32-09).

These two channels are **not** "fill in a token and push". Both need an anchor
produced by an *inbound* message:

- WeChat ClawBot (iLink) needs a ``context_token`` carried by a received
  message; ``to_user_id`` alone is not enough to route a reply.
- QQ needs a bot-scoped ``openid`` obtained from an event.

State machine per channel::

    unbound --(inbound message, anchor extracted)--> bound --(expired/quota)--> stale
        |                                              |
        +-- send -> not_bound                          +-- send -> delivered

Design consequences implemented here:

- Sending while unbound (or while the refresh window is exhausted) returns
  ``error_category="not_bound"`` and is never retried: retrying cannot make the
  user send a message.
- An anchor is persisted with ``0600`` permissions and never logged.
- Nothing polls until the caller explicitly binds: the default-silence contract
  (no network until configured) still holds.

**Evidence level.** Every iLink endpoint, header and body field below is
``UNVERIFIED`` (third-party reverse engineering; see
``evidence/channel-facts.json``). They are isolated in named constants so the
M3 sandbox check can correct them in one place. QQ anchor registration is
explicit because obtaining an ``openid`` needs an event subscription
(WebSocket or a public webhook) and the standard library has no WebSocket
client - adding one would break the zero-dependency rule (D32-B).
"""

import base64
import json
import os
import secrets
import threading
import time

from .channels import (
    Attempt,
    ChannelSpec,
    compose_text,
    parse_json,
    status_attempt,
)
from .security import mask_text
from .transport import HttpRequest, TransportError

# --- iLink / ClawBot constants (all UNVERIFIED) -----------------------------

CLAWBOT_BASE_URL = "https://ilinkai.weixin.qq.com"
CLAWBOT_QRCODE_PATH = "/ilink/bot/get_bot_qrcode"
CLAWBOT_QRCODE_STATUS_PATH = "/ilink/bot/get_qrcode_status"
CLAWBOT_UPDATES_PATH = "/ilink/bot/getupdates"
CLAWBOT_SEND_PATH = "/ilink/bot/sendmessage"
CLAWBOT_CHANNEL_VERSION = "1.0.3"
# A fresh inbound message is reported to be required every ~10 proactive sends;
# stop at 8 and ask for a refresh so the boundary is never crossed.
CLAWBOT_REFRESH_THRESHOLD = 8

# --- QQ constants ----------------------------------------------------------

QQ_TOKEN_URL = (
    "https://bots.qq.com/app/getAppAccessToken"  # nosec B105 - endpoint, not a credential
)
QQ_API_BASE_URL = "https://api.bot.qq.com"
QQ_SANDBOX_BASE_URL = "https://sandbox.api.sgroup.qq.com"
QQ_EXPIRED_CODES = (11241, 11243)

DEFAULT_ANCHOR_DIR = os.path.join(os.path.expanduser("~"), ".backtrader", "notifications")


CLAWBOT_SPEC = ChannelSpec(
    id="wechat_clawbot",
    requires=("bot_token", "to_user_id"),
    optional=("context_token", "base_url", "cursor"),
    rate_limit=(None, None),
    max_length=None,
    markdown=False,
    supports_at_all=False,
)

QQ_BOT_SPEC = ChannelSpec(
    id="qq_bot",
    requires=("appid", "appsecret"),
    optional=("user_openid", "group_openid", "sandbox"),
    rate_limit=(20, None),
    max_length=None,
    markdown=False,
    supports_at_all=False,
)


def _random_uin():
    """Return the per-request ``X-WECHAT-UIN`` value.

    The header exists to make replays detectable, so the value comes from
    ``secrets`` rather than the pseudo-random generator.

    Returns:
        str: Base64 of a random 32-bit integer rendered as decimal text.
    """
    value = str(secrets.randbits(32)).encode("utf-8")
    return base64.b64encode(value).decode("ascii")


def _json_bytes(payload):
    """Serialise a payload to UTF-8 JSON bytes.

    Args:
        payload: JSON-serialisable object.

    Returns:
        bytes: Encoded body.
    """
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def persist_anchor(path, data):
    """Persist anchor credentials with owner-only permissions.

    Args:
        path: Destination file path.
        data: JSON-serialisable anchor mapping.

    Returns:
        str: The path written.

    Raises:
        OSError: If the file cannot be written.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:  # nosec B110 - best effort on platforms without POSIX modes
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:  # nosec B110 - best effort on platforms without POSIX modes
        pass
    return path


def load_anchor(path):
    """Load a persisted anchor file.

    Args:
        path: File path to read.

    Returns:
        dict: The anchor mapping, or an empty dict when the file is absent or
        unreadable.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class WechatClawbotDriver:
    """Deliver messages through a WeChat ClawBot session anchor.

    The driver owns the anchor state (:attr:`context_token` and the refresh
    counter) so a long-running process can keep sending after receiving new
    inbound messages.
    """

    def __init__(self, spec, config, transport, timeout=10.0):
        """Initialise anchor state from the channel config.

        Args:
            spec: The channel spec (metadata only).
            config: Resolved credentials and optional anchor.
            transport: HTTP transport to use.
            timeout: Per-request timeout in seconds.
        """
        self._spec = spec
        self._config = dict(config)
        self._transport = transport
        self._timeout = timeout
        self._lock = threading.Lock()
        self._base_url = str(self._config.get("base_url") or CLAWBOT_BASE_URL).rstrip("/")
        self._context_token = self._config.get("context_token") or None
        self._cursor = self._config.get("cursor") or ""
        self._sends_since_refresh = 0
        self._last_error = None

    def __repr__(self):
        """Return a credential-free representation."""
        return "{0}(channel={1!r})".format(type(self).__name__, self._spec.id)

    @property
    def spec(self):
        """Return the channel spec."""
        return self._spec

    @property
    def bound(self):
        """Whether a usable anchor is present."""
        with self._lock:
            return bool(self._config.get("bot_token") and self._config.get("to_user_id"))

    def anchor_snapshot(self):
        """Return the persistable anchor state.

        Returns:
            dict: ``bot_token``, ``to_user_id`` and the current
            ``context_token``.
        """
        with self._lock:
            return {
                "bot_token": self._config.get("bot_token"),
                "to_user_id": self._config.get("to_user_id"),
                "context_token": self._context_token,
                "cursor": self._cursor,
            }

    def apply_inbound(self, message):
        """Refresh the anchor from one inbound message.

        Args:
            message: Parsed inbound message mapping.

        Returns:
            bool: Whether the message carried a usable anchor.
        """
        if not isinstance(message, dict):
            return False
        token = message.get("context_token")
        sender = message.get("from_user_id")
        with self._lock:
            changed = False
            if token:
                self._context_token = str(token)
                self._sends_since_refresh = 0
                changed = True
            if sender and not self._config.get("to_user_id"):
                self._config["to_user_id"] = str(sender)
                changed = True
            return changed

    def _headers(self):
        """Build the iLink request headers.

        Returns:
            dict: Headers including the bearer token and a fresh ``X-WECHAT-UIN``.
        """
        return {
            "Content-Type": "application/json; charset=utf-8",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": "Bearer {0}".format(self._config.get("bot_token", "")),
            "X-WECHAT-UIN": _random_uin(),
        }

    def apply_anchor(self, anchor):
        """Apply a freshly bound anchor to this driver.

        Args:
            anchor: Mapping with ``bot_token``/``to_user_id``/``context_token``.

        Returns:
            bool: Whether anything changed.
        """
        if not isinstance(anchor, dict):
            return False
        changed = False
        with self._lock:
            for key in ("bot_token", "to_user_id"):
                value = anchor.get(key)
                if value:
                    self._config[key] = value
                    changed = True
            token = anchor.get("context_token")
            if token:
                self._context_token = str(token)
                self._sends_since_refresh = 0
                changed = True
        return changed

    def poll_once(self, timeout=None):
        """Fetch pending inbound messages once and refresh the anchor.

        Args:
            timeout: Request timeout override.

        Returns:
            Attempt: ``ok`` when the poll succeeded; failures are classified.
        """
        timeout = float(timeout if timeout is not None else self._timeout)
        url = self._base_url + CLAWBOT_UPDATES_PATH
        request = HttpRequest(
            method="POST",
            url=url,
            headers=self._headers(),
            body=_json_bytes({"get_updates_buf": self._cursor}),
            timeout=timeout,
        )
        try:
            response = self._transport.send(request)
        except TransportError as exc:
            self._last_error = mask_text(str(exc))
            return Attempt(False, exc.kind, self._last_error)
        attempt = status_attempt(response)
        if attempt is not None:
            return attempt
        data = parse_json(response)
        self._cursor = data.get("get_updates_buf", self._cursor)
        for message in data.get("msgs") or []:
            self.apply_inbound(message)
        return Attempt(True)

    def deliver(self, notification, timeout=None):
        """Send one message using the current anchor.

        Args:
            notification: Message to send.
            timeout: Per-call timeout override.

        Returns:
            Attempt: The outcome. ``not_bound`` covers "no anchor" and "refresh
            window exhausted" so callers can tell the user to message the bot.
        """
        timeout = float(timeout if timeout is not None else self._timeout)
        with self._lock:
            if not (self._config.get("bot_token") and self._config.get("to_user_id")):
                return Attempt(False, "not_bound", "clawbot anchor not bound")
            if not self._context_token:
                return Attempt(
                    False, "not_bound", "clawbot context_token missing; send the bot a message"
                )
            if self._sends_since_refresh >= CLAWBOT_REFRESH_THRESHOLD:
                return Attempt(
                    False,
                    "not_bound",
                    "clawbot refresh window exhausted; send the bot a message",
                )
            context_token = self._context_token
        text, truncated = compose_text(notification, self._spec)
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": str(self._config["to_user_id"]),
                "client_id": "backtrader-{0}".format(os.urandom(8).hex()),
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
            },
            "base_info": {"channel_version": CLAWBOT_CHANNEL_VERSION},
        }
        request = HttpRequest(
            method="POST",
            url=self._base_url + CLAWBOT_SEND_PATH,
            headers=self._headers(),
            body=_json_bytes(payload),
            timeout=timeout,
        )
        try:
            response = self._transport.send(request)
        except TransportError as exc:
            return Attempt(False, exc.kind, mask_text(str(exc)), truncated=truncated)
        attempt = status_attempt(response)
        if attempt is not None:
            return attempt
        # The protocol returns HTTP 200 with an empty body even when the message
        # is dropped, so success here is a weak signal (see the M0 evidence).
        with self._lock:
            self._sends_since_refresh += 1
        return Attempt(True, truncated=truncated)


class QqBotDriver:
    """Deliver messages through the QQ bot HTTP API with a cached token."""

    def __init__(self, spec, config, transport, timeout=10.0):
        """Store config and prepare an empty token cache.

        Args:
            spec: The channel spec (metadata only).
            config: Resolved credentials (``appid``, ``appsecret``, anchors).
            transport: HTTP transport to use.
            timeout: Per-request timeout in seconds.
        """
        self._spec = spec
        self._config = dict(config)
        self._transport = transport
        self._timeout = timeout
        self._lock = threading.Lock()
        self._token = None
        self._expires_at = 0.0
        base = QQ_SANDBOX_BASE_URL if config.get("sandbox") else QQ_API_BASE_URL
        self._base_url = str(config.get("base_url") or base).rstrip("/")

    def __repr__(self):
        """Return a credential-free representation."""
        return "{0}(channel={1!r})".format(type(self).__name__, self._spec.id)

    @property
    def spec(self):
        """Return the channel spec."""
        return self._spec

    @property
    def bound(self):
        """Whether a sendable anchor (user or group openid) is present."""
        return bool(self._config.get("user_openid") or self._config.get("group_openid"))

    def anchor_snapshot(self):
        """Return the persistable anchor state.

        Returns:
            dict: The configured app id and openids.
        """
        return {
            "appid": self._config.get("appid"),
            "user_openid": self._config.get("user_openid"),
            "group_openid": self._config.get("group_openid"),
        }

    def apply_anchor(self, anchor):
        """Apply a freshly registered anchor to this driver.

        Args:
            anchor: Mapping with ``appid``/``user_openid``/``group_openid``.

        Returns:
            bool: Whether anything changed.
        """
        if not isinstance(anchor, dict):
            return False
        changed = False
        for key in ("appid", "user_openid", "group_openid"):
            value = anchor.get(key)
            if value:
                self._config[key] = value
                changed = True
        return changed

    def _fetch_token(self, timeout):
        """Fetch a QQ access token.

        Args:
            timeout: Request timeout in seconds.

        Returns:
            str or None: The token, or ``None`` on failure.
        """
        payload = {
            "appId": str(self._config["appid"]),
            "clientSecret": str(self._config["appsecret"]),
        }
        request = HttpRequest(
            method="POST",
            url=QQ_TOKEN_URL,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=_json_bytes(payload),
            timeout=timeout,
        )
        try:
            response = self._transport.send(request)
        except TransportError:
            return None
        if not (200 <= response.status < 300):
            return None
        data = parse_json(response)
        token = data.get("access_token")
        if not token:
            return None
        try:
            expires_in = float(data.get("expires_in", 7200))
        except (TypeError, ValueError):
            expires_in = 7200.0
        with self._lock:
            self._token = str(token)
            self._expires_at = time.monotonic() + max(0.0, expires_in - 300.0)
        return self._token

    def _cached_token(self, timeout, force=False):
        """Return a usable token, fetching one when expired or forced.

        Args:
            timeout: Request timeout in seconds.
            force: Whether to bypass the cache.

        Returns:
            str or None: The token, or ``None`` on failure.
        """
        with self._lock:
            if not force and self._token and time.monotonic() < self._expires_at:
                return self._token
        return self._fetch_token(timeout)

    def _target(self):
        """Return ``(path_suffix, openid)`` for the configured anchor.

        Returns:
            tuple or None: Endpoint suffix and the anchor openid.
        """
        group = self._config.get("group_openid")
        if group:
            return "groups", str(group)
        user = self._config.get("user_openid")
        if user:
            return "users", str(user)
        return None

    def _classify(self, data):
        """Classify a QQ API error payload.

        Args:
            data: Parsed JSON body.

        Returns:
            Attempt: The classified outcome.
        """
        code = data.get("code", data.get("err_code", 0))
        message = data.get("message", data.get("msg", ""))
        detail = mask_text(str(message) or "code={0}".format(code))
        if code in QQ_EXPIRED_CODES:
            with self._lock:
                self._token = None
                self._expires_at = 0.0
            return Attempt(False, "auth", detail)
        if code in (40034100, 1100100):
            return Attempt(False, "rate_limit", detail)
        if code in (40034105, 11253, 11254):
            return Attempt(False, "permission", detail)
        return Attempt(False, "bad_request", detail)

    def _send(self, token, notification, text, timeout, truncated):
        """Post one message with a known token.

        Args:
            token: Access token.
            notification: Message being sent.
            text: Adapted text.
            timeout: Request timeout in seconds.
            truncated: Whether the body was truncated.

        Returns:
            Attempt: The outcome.
        """
        target = self._target()
        if target is None:
            return Attempt(False, "not_bound", "qq anchor not bound")
        collection, openid = target
        url = "{0}/v2/{1}/{2}/messages".format(self._base_url, collection, openid)
        request = HttpRequest(
            method="POST",
            url=url,
            headers={
                "Authorization": "QQBot {0}".format(token),
                "Content-Type": "application/json; charset=utf-8",
            },
            body=_json_bytes({"content": text, "msg_type": 0}),
            timeout=timeout,
        )
        try:
            response = self._transport.send(request)
        except TransportError as exc:
            return Attempt(False, exc.kind, mask_text(str(exc)), truncated=truncated)
        attempt = status_attempt(response)
        if attempt is not None:
            return attempt
        data = parse_json(response)
        code = data.get("code", 0)
        if code in (0, None):
            return Attempt(True, truncated=truncated)
        classified = self._classify(data)
        return Attempt(
            classified.ok,
            classified.category,
            classified.error,
            classified.retry_after,
            truncated=truncated,
        )

    def deliver(self, notification, timeout=None):
        """Send one message, refreshing an expired token once.

        Args:
            notification: Message to send.
            timeout: Per-call timeout override.

        Returns:
            Attempt: The outcome; failures are classified, never raised.
        """
        timeout = float(timeout if timeout is not None else self._timeout)
        if self._target() is None:
            return Attempt(False, "not_bound", "qq anchor not bound")
        text, truncated = compose_text(notification, self._spec)
        token = self._cached_token(timeout)
        if token is None:
            return Attempt(False, "auth", "qq access token unavailable", truncated=truncated)
        attempt = self._send(token, notification, text, timeout, truncated)
        if attempt.ok or attempt.category != "auth":
            return attempt
        refreshed = self._cached_token(timeout, force=True)
        if refreshed is None:
            return attempt
        return self._send(refreshed, notification, text, timeout, truncated)


def bind_wechat_clawbot(
    transport,
    qr_callback=None,
    persist_path=None,
    timeout=30.0,
    poll_interval=2.0,
    max_polls=150,
):
    """Run the ClawBot QR login flow and persist the resulting anchor.

    Args:
        transport: HTTP transport to use.
        qr_callback: Optional ``callable(url)`` invoked with the QR target so a
            caller can render it; defaults to printing the URL.
        persist_path: Where to store the anchor; ``None`` uses the default
            anchor directory.
        timeout: Request timeout in seconds.
        poll_interval: Seconds between QR status polls.
        max_polls: Maximum number of status polls before giving up.

    Returns:
        dict: ``{"bot_token", "to_user_id", "context_token"}`` on success, or an
        empty dict when binding did not complete.

    Raises:
        ValueError: If the QR step yields no usable payload.
    """
    base = CLAWBOT_BASE_URL
    qr_response = transport.send(
        HttpRequest(method="GET", url=base + CLAWBOT_QRCODE_PATH, timeout=timeout)
    )
    if not (200 <= qr_response.status < 300):
        raise ValueError("clawbot qr request failed with HTTP {0}".format(qr_response.status))
    qr_data = parse_json(qr_response)
    target = qr_data.get("qrcode_url") or qr_data.get("qrcode") or qr_data.get("url")
    if not target:
        raise ValueError("clawbot qr response carried no QR target")
    identifier = qr_data.get("qrcode_id") or qr_data.get("id")
    if qr_callback is not None:
        qr_callback(target)
    status_url = base + CLAWBOT_QRCODE_STATUS_PATH
    if identifier:
        status_url = "{0}?qrcode_id={1}".format(status_url, identifier)
    for _ in range(max_polls):
        status_response = transport.send(HttpRequest(method="GET", url=status_url, timeout=timeout))
        data = parse_json(status_response)
        token = data.get("bot_token") or data.get("token")
        if token:
            anchor = {
                "bot_token": str(token),
                "to_user_id": data.get("to_user_id") or data.get("user_id") or "",
                "context_token": data.get("context_token") or "",
            }
            if persist_path:
                persist_anchor(persist_path, anchor)
            return anchor
        state = str(data.get("status") or data.get("state") or "")
        if state in ("expired", "cancel", "cancelled"):
            return {}
        time.sleep(poll_interval)
    return {}


def bind_qq_bot(user_openid=None, group_openid=None, persist_path=None):
    """Register a QQ anchor explicitly.

    Automatic binding would need an event subscription (WebSocket or a public
    webhook). The standard library has no WebSocket client and adding one would
    break the zero-dependency rule, so the anchor is supplied by the caller -
    typically read from their own subscription or sandbox event log.

    Args:
        user_openid: Single-chat anchor.
        group_openid: Group-chat anchor.
        persist_path: Where to store the anchor.

    Returns:
        dict: The anchor mapping.

    Raises:
        ValueError: If neither anchor is supplied.
    """
    if not user_openid and not group_openid:
        raise ValueError("provide user_openid or group_openid")
    anchor = {"user_openid": user_openid, "group_openid": group_openid}
    if persist_path:
        persist_anchor(persist_path, anchor)
    return anchor


def default_anchor_path(channel_id):
    """Return the default anchor file path for a channel.

    Args:
        channel_id: Public channel id.

    Returns:
        str: Path under the user's home directory.
    """
    return os.path.join(DEFAULT_ANCHOR_DIR, "{0}.json".format(channel_id))
