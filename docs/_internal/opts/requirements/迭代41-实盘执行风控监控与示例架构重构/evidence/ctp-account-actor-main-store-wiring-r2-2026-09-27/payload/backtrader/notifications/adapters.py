"""Channels that are not a plain "one POST, read the code" webhook (D32-03).

- **Telegram** fits the declarative shape except that a 429 carries
  ``parameters.retry_after``; it is declared here as an extra
  :class:`~backtrader.notifications.channels.ChannelSpec` so the core drives it
  through the generic driver.
- **WeCom application message** needs a token with a lifetime: it is fetched
  once, cached until ``expires_in - 300s``, and refreshed exactly once when the
  API reports an expired token - the single documented exception to the
  "no retry on auth errors" rule.
- **Email** goes over SMTP rather than HTTP, so it has its own driver and its own
  injectable sender.

Credential and token caches live on the driver instance and never touch disk.
"""

import json
import threading
import time
from typing import Dict
from urllib.parse import quote

from .channels import (
    Attempt,
    ChannelSpec,
    code_attempt,
    compose_text,
    escape_markdown_v2,
    normalize_level,
    parse_json,
    retry_after_from_header,
    status_attempt,
)
from .security import mask_text
from .transport import HttpRequest, SmtpEnvelope, SmtpError, TransportError

# Refresh this many seconds before the server-side token expiry.
TOKEN_REFRESH_MARGIN_SECONDS = 300.0


def _json_bytes(payload):
    """Serialise a payload to UTF-8 JSON bytes.

    Args:
        payload: JSON-serialisable object.

    Returns:
        bytes: Encoded body.
    """
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


# --- Telegram ---------------------------------------------------------------


def _build_telegram(notification, config, text):
    """Build a Telegram ``sendMessage`` request.

    Args:
        notification: Message being sent.
        config: Resolved credentials (``bot_token``, ``chat_id``).
        text: Adapted text, already MarkdownV2-escaped.

    Returns:
        HttpRequest: The request.
    """
    url = "https://api.telegram.org/bot{0}/sendMessage".format(
        quote(str(config["bot_token"]), safe="")
    )
    payload = {
        "chat_id": config["chat_id"],
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    return HttpRequest(
        method="POST",
        url=url,
        headers={"Content-Type": "application/json; charset=utf-8"},
        body=_json_bytes(payload),
    )


def _ok_telegram(response):
    """Classify a Telegram response.

    Telegram reports rate limits as HTTP 429 with ``parameters.retry_after``;
    that value is surfaced so the core can wait exactly as long as asked.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    retry_after = retry_after_from_header(response)
    data = parse_json(response)
    if retry_after is None:
        parameters = data.get("parameters")
        if isinstance(parameters, dict):
            value = parameters.get("retry_after")
            if isinstance(value, (int, float)):
                retry_after = float(value)
    attempt = status_attempt(response, retry_after=retry_after)
    if attempt is not None:
        return attempt
    if data.get("ok") is True:
        return Attempt(True)
    code = data.get("error_code")
    description = data.get("description", "")
    if code == 401:
        return Attempt(False, "auth", mask_text(str(description)))
    if code == 429:
        return Attempt(False, "rate_limit", mask_text(str(description)), retry_after=retry_after)
    return Attempt(
        False, "bad_request", mask_text(str(description) or "telegram rejected the request")
    )


def _escape_v2(text):
    """Escape Telegram MarkdownV2 in adapted text.

    Args:
        text: Adapted text.

    Returns:
        str: Escaped text.
    """
    return escape_markdown_v2(text)


TELEGRAM_SPEC = ChannelSpec(
    id="telegram",
    requires=("bot_token", "chat_id"),
    optional=(),
    rate_limit=(20, 1),
    max_length=4096,
    markdown=True,
    supports_at_all=False,
    build=_build_telegram,
    is_ok=_ok_telegram,
    transform=_escape_v2,
)


# --- WeCom application message ---------------------------------------------

_WECOM_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"  # nosec B105 - endpoint
_WECOM_SEND_URL = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
_WECOM_EXPIRED_CODES = (40014, 42001)

WECOM_APP_SPEC = ChannelSpec(
    id="wecom_app",
    requires=("corpid", "corpsecret", "agentid", "touser"),
    optional=(),
    rate_limit=(30, None),
    max_length=2048,
    byte_limited=True,
    markdown=True,
    supports_at_all=True,
)


class _TokenFailure:
    """Internal marker for a classified token-fetch failure."""

    __slots__ = ("category", "error")

    def __init__(self, attempt):
        """Copy the category and error from a failed attempt.

        Args:
            attempt: The classified token failure.
        """
        self.category = attempt.category
        self.error = attempt.error


def _agent_id(value):
    """Coerce an agent id to an int when possible.

    Args:
        value: Raw agent id.

    Returns:
        int or str: Numeric id when parseable, else the original value.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _classify_token_failure(response, data):
    """Classify a failed token fetch.

    Args:
        response: The HTTP response.
        data: Parsed JSON body.

    Returns:
        Attempt: The classified failure.
    """
    attempt = status_attempt(response)
    if attempt is not None:
        return attempt
    return code_attempt(
        data.get("errcode", 0),
        data.get("errmsg", "token request failed"),
        auth=(40001, 40013, 40056),
        rate=(45009,),
    )


class WecomAppDriver:
    """Deliver WeCom application messages with a cached access token."""

    def __init__(self, spec, config, transport, timeout=10.0):
        """Store config and prepare an empty token cache.

        Args:
            spec: The channel spec (metadata only).
            config: Resolved credentials.
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

    def __repr__(self):
        """Return a credential-free representation."""
        return "{0}(channel={1!r})".format(type(self).__name__, self._spec.id)

    @property
    def spec(self):
        """Return the channel spec."""
        return self._spec

    def _fetch_token(self, timeout):
        """Fetch a fresh access token and cache it with its expiry.

        Args:
            timeout: Request timeout in seconds.

        Returns:
            str or _TokenFailure: The token, or a classified failure.
        """
        url = "{0}?corpid={1}&corpsecret={2}".format(
            _WECOM_TOKEN_URL,
            quote(str(self._config["corpid"]), safe=""),
            quote(str(self._config["corpsecret"]), safe=""),
        )
        try:
            response = self._transport.send(HttpRequest(method="GET", url=url, timeout=timeout))
        except TransportError as exc:
            return _TokenFailure(Attempt(False, exc.kind, mask_text(str(exc))))
        data = parse_json(response)
        if (
            200 <= response.status < 300
            and data.get("errcode", 0) == 0
            and data.get("access_token")
        ):
            try:
                expires_in = float(data.get("expires_in", 7200))
            except (TypeError, ValueError):
                expires_in = 7200.0
            with self._lock:
                self._token = str(data["access_token"])
                self._expires_at = time.monotonic() + max(
                    0.0, expires_in - TOKEN_REFRESH_MARGIN_SECONDS
                )
            return self._token
        return _TokenFailure(_classify_token_failure(response, data))

    def _cached_token(self, timeout, force=False):
        """Return a usable token, fetching one when expired or forced.

        Args:
            timeout: Request timeout in seconds.
            force: Whether to bypass the cache.

        Returns:
            str or _TokenFailure: The token, or a classified failure.
        """
        with self._lock:
            if not force and self._token and time.monotonic() < self._expires_at:
                return self._token
        return self._fetch_token(timeout)

    def _invalidate_token(self):
        """Drop the cached token so the next call fetches a new one."""
        with self._lock:
            self._token = None
            self._expires_at = 0.0

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
        payload = {
            "touser": "@all" if notification.at_all else str(self._config["touser"]),
            "msgtype": "markdown",
            "agentid": _agent_id(self._config["agentid"]),
            "markdown": {"content": text},
        }
        url = "{0}?access_token={1}".format(_WECOM_SEND_URL, quote(str(token), safe=""))
        request = HttpRequest(
            method="POST",
            url=url,
            headers={"Content-Type": "application/json; charset=utf-8"},
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
        data = parse_json(response)
        code = data.get("errcode", 0)
        if code == 0:
            return Attempt(True, truncated=truncated)
        if code in _WECOM_EXPIRED_CODES:
            self._invalidate_token()
            return Attempt(False, "auth", mask_text(data.get("errmsg", "")), truncated=truncated)
        classified = code_attempt(
            code, data.get("errmsg", ""), auth=(40001, 40013), rate=(45009,), permission=(60011,)
        )
        return Attempt(
            classified.ok,
            classified.category,
            classified.error,
            classified.retry_after,
            truncated=truncated,
        )

    def deliver(self, notification, timeout=None):
        """Send one application message, refreshing an expired token once.

        Args:
            notification: Message to send.
            timeout: Per-call timeout override.

        Returns:
            Attempt: The outcome; failures are classified, never raised.
        """
        timeout = float(timeout if timeout is not None else self._timeout)
        text, truncated = compose_text(notification, self._spec)
        token = self._cached_token(timeout)
        if isinstance(token, _TokenFailure):
            return Attempt(False, token.category, token.error, truncated=truncated)
        attempt = self._send(token, notification, text, timeout, truncated)
        if attempt.ok or attempt.category != "auth":
            return attempt
        refreshed = self._cached_token(timeout, force=True)
        if isinstance(refreshed, _TokenFailure):
            return attempt
        return self._send(refreshed, notification, text, timeout, truncated)


# --- Email -----------------------------------------------------------------


EMAIL_SPEC = ChannelSpec(
    id="email",
    requires=("host", "port", "to"),
    optional=("user", "password", "sender", "ssl", "starttls", "html"),
    rate_limit=(None, None),
    max_length=None,
    markdown=False,
    supports_at_all=False,
)


class EmailDriver:
    """Deliver notifications over SMTP through an injectable sender."""

    def __init__(self, spec, config, sender, timeout=10.0):
        """Store config and the SMTP sender.

        Args:
            spec: The channel spec (metadata only).
            config: Resolved credentials (``host``, ``port``, ``to`` ...).
            sender: An object implementing ``send(envelope)``.
            timeout: Socket timeout in seconds.
        """
        self._spec = spec
        self._config = dict(config)
        self._sender = sender
        self._timeout = timeout

    def __repr__(self):
        """Return a credential-free representation."""
        return "{0}(channel={1!r})".format(type(self).__name__, self._spec.id)

    @property
    def spec(self):
        """Return the channel spec."""
        return self._spec

    def deliver(self, notification, timeout=None):
        """Send one email.

        Args:
            notification: Message to send.
            timeout: Per-call timeout override.

        Returns:
            Attempt: The outcome; SMTP failures are classified, never raised.
        """
        text, truncated = compose_text(notification, self._spec)
        subject = "[{0}] {1}".format(
            normalize_level(notification.level).upper(),
            notification.title or "backtrader",
        )
        recipients = tuple(str(item) for item in self._config["to"])
        user = str(self._config.get("user") or "")
        port = int(self._config["port"])
        envelope = SmtpEnvelope(
            host=str(self._config["host"]),
            port=port,
            user=user,
            password=str(self._config.get("password") or ""),
            sender=str(self._config.get("sender") or user),
            recipients=recipients,
            subject=subject,
            body=text,
            html=bool(self._config.get("html", False)),
            use_ssl=bool(self._config.get("ssl", port == 465)),
            use_starttls=bool(self._config.get("starttls", port == 587)),
            timeout=float(timeout if timeout is not None else self._timeout),
        )
        try:
            self._sender.send(envelope)
        except SmtpError as exc:
            return Attempt(False, exc.kind, mask_text(str(exc)), truncated=truncated)
        except Exception as exc:  # a sender failure must never break a backtest
            return Attempt(
                False,
                "unknown",
                mask_text("{0}: {1}".format(type(exc).__name__, exc)),
                truncated=truncated,
            )
        return Attempt(True, truncated=truncated)


ADAPTER_SPECS: Dict[str, ChannelSpec] = {
    "telegram": TELEGRAM_SPEC,
    "wecom_app": WECOM_APP_SPEC,
    "email": EMAIL_SPEC,
}


def build_adapter_driver(channel_id, spec, config, transport, smtp_sender, timeout=10.0):
    """Create the driver for a channel that needs custom delivery logic.

    Args:
        channel_id: Public channel id.
        spec: The channel spec.
        config: Resolved credentials.
        transport: HTTP transport (unused by the email driver).
        smtp_sender: SMTP sender (unused by HTTP drivers).
        timeout: Default request timeout in seconds.

    Returns:
        object or None: A driver exposing ``deliver``/``spec``; ``None`` when the
        channel is driven declaratively.
    """
    if channel_id == "wecom_app":
        return WecomAppDriver(spec, config, transport, timeout=timeout)
    if channel_id == "email":
        return EmailDriver(spec, config, smtp_sender, timeout=timeout)
    return None
