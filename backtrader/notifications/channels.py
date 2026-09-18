"""Declarative webhook channels and message adaptation (iteration 32, D32-03/D32-08).

This module owns everything that is *the same* across webhook-style channels:

- :class:`Notification` - the internal message object assembled from
  ``Strategy.send_message`` context.
- :class:`Attempt` - the internal per-send result (success, error category,
  optional retry hint, truncation flag).
- :class:`ChannelSpec` - one declarative entry per channel: required
  credentials, local rate limit, length limit, rich-text capability and the
  three hooks ``transform`` / ``build`` / ``is_ok``.
- :func:`compose_text` and friends - level prefixing, markdown downgrade,
  UTF-8-safe truncation and MarkdownV2 escaping.
- :class:`DeclarativeDriver` - builds, sends and classifies one request using a
  spec, so the core never has to know about payload shapes.

Channels whose behaviour does not fit "one JSON POST, look at the response code"
live elsewhere: ``adapters.py`` (email / Telegram / WeCom app) and ``session.py``
(WeChat ClawBot / QQ bot). Length limits are only set where the value could be
confirmed in M0; unconfirmed channels declare ``None`` and are not truncated
(see ``evidence/channel-facts.json``).
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote

from .security import mask_text, mask_url
from .signatures import dingtalk_sign, feishu_sign
from .transport import HttpRequest, HttpResponse, TransportError

# ---------------------------------------------------------------------------
# Internal message and result objects
# ---------------------------------------------------------------------------

LEVELS = ("info", "warning", "error", "critical")


@dataclass(frozen=True)
class Notification:
    """A message to deliver, with the context injected by the caller.

    Attributes:
        text: Body text.
        title: Optional title; defaults to the strategy name when sent from a
            strategy.
        level: One of :data:`LEVELS` (already normalised).
        at_time: Backtest timestamp (``Strategy.datetime.datetime()``), never
            wall clock.
        strategy: Strategy class name.
        data_name: ``data._name`` when available.
        dedup_key: Optional deduplication key.
        at_all: Whether the "mention everyone" hint should be attached; the core
            resolves this from the global option and the level.
    """

    text: str
    title: Optional[str] = None
    level: str = "info"
    at_time: Any = None
    strategy: Optional[str] = None
    data_name: Optional[str] = None
    dedup_key: Optional[str] = None
    at_all: bool = False


@dataclass(frozen=True)
class Attempt:
    """The outcome of one delivery attempt.

    Attributes:
        ok: Whether the channel accepted the message.
        category: Public error category (``None`` when ``ok``).
        error: Masked, readable diagnostic.
        retry_after: Seconds the channel asked us to wait (429 style).
        truncated: Whether the body had to be truncated.
    """

    ok: bool
    category: Optional[str] = None
    error: Optional[str] = None
    retry_after: Optional[float] = None
    truncated: bool = False


@dataclass(frozen=True)
class ChannelSpec:
    """Declarative description of one webhook-style channel.

    Attributes:
        id: Public channel id.
        requires: Required credential field names.
        optional: Optional credential field names.
        rate_limit: ``(per_minute, per_second)`` local limits; ``None`` means
            unlimited on that axis.
        max_length: Content limit, or ``None`` when not confirmed.
        byte_limited: Whether ``max_length`` counts UTF-8 bytes (vs characters).
        markdown: Whether the channel renders markdown.
        supports_at_all: Whether the channel can mention everyone.
        build: ``(notification, config, text) -> HttpRequest``; ``None`` for
            channels whose delivery is implemented by a custom driver.
        is_ok: ``(response) -> Attempt``; ``None`` when a custom driver
            classifies the response itself.
        transform: Optional text transform applied after adaptation.
    """

    id: str
    requires: Tuple[str, ...]
    optional: Tuple[str, ...]
    rate_limit: Optional[Tuple[Optional[int], Optional[float]]]
    max_length: Optional[int]
    markdown: bool
    supports_at_all: bool
    build: Optional[Callable[[Notification, Dict[str, Any], str], HttpRequest]] = None
    is_ok: Optional[Callable[[HttpResponse], Attempt]] = None
    byte_limited: bool = False
    transform: Optional[Callable[[str], str]] = None


# ---------------------------------------------------------------------------
# Text adaptation
# ---------------------------------------------------------------------------


def normalize_level(level):
    """Normalise and validate a level name.

    Args:
        level: Level as a string (any case).

    Returns:
        str: Lower-cased level name.

    Raises:
        ValueError: If the level is not one of :data:`LEVELS`.
    """
    if not isinstance(level, str):
        raise ValueError("level must be a string, got {0!r}".format(type(level).__name__))
    normalized = level.strip().lower()
    if normalized not in LEVELS:
        raise ValueError("level must be one of {0}, got {1!r}".format(LEVELS, level))
    return normalized


def level_prefix(level):
    """Return the ``[LEVEL]`` prefix for a normalised level.

    Args:
        level: Normalised level name.

    Returns:
        str: The bracketed prefix.
    """
    return "[{0}]".format(level.upper())


def strip_markdown(text):
    """Remove common markdown markers so plain-text channels stay readable.

    Args:
        text: Text that may contain markdown.

    Returns:
        str: Text with emphasis/heading/code/quote markers removed.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            line = stripped.lstrip("#").strip()
        if line.lstrip().startswith(">"):
            line = line.lstrip()[1:].strip()
        out.append(line)
    joined = "\n".join(out)
    for marker in ("**", "__", "`", "~~"):
        joined = joined.replace(marker, "")
    return joined


_ESCAPE_MDV2 = "_*[]()~`>#+-=|{}.!"


def escape_markdown_v2(text):
    """Escape Telegram MarkdownV2 special characters.

    Args:
        text: Plain text to escape.

    Returns:
        str: Escaped text safe for ``parse_mode=MarkdownV2``.
    """
    return "".join("\\" + ch if ch in _ESCAPE_MDV2 else ch for ch in text)


def truncate(text, limit, byte_limited=False):
    """Truncate ``text`` to ``limit`` and mark the result.

    Byte-limited channels are cut on a UTF-8 boundary so multi-byte characters
    are never split. The marker states how much was dropped.

    Args:
        text: Text to truncate.
        limit: Maximum length, or ``None`` to skip truncation.
        byte_limited: Whether ``limit`` counts UTF-8 bytes.

    Returns:
        tuple: ``(text, truncated)``.
    """
    if limit is None:
        return text, False
    if byte_limited:
        encoded = text.encode("utf-8")
        if len(encoded) <= limit:
            return text, False
        removed = 0
        keep = limit
        while keep > 0:
            try:
                head = encoded[:keep].decode("utf-8")
                break
            except UnicodeDecodeError:
                keep -= 1
        else:  # pragma: no cover - only reachable with limit <= 0
            head = ""
        removed = len(text) - len(head)
        return head + "\n…（已截断 {0} 字符）".format(removed), True
    if len(text) <= limit:
        return text, False
    removed = len(text) - limit
    return text[:limit] + "\n…（已截断 {0} 字符）".format(removed), True


def context_line(notification):
    """Render the injected context as one line under the title.

    The strategy class normally already sits in the title (``Strategy.send_message``
    defaults the title to the class name), so ``strategy=`` is only added when it
    would not repeat the title. ``data_name`` always renders: with several feeds it
    is the only way to tell which data produced the message.

    Args:
        notification: Message being sent.

    Returns:
        str: The context line, or an empty string when there is no context.
    """
    pieces = []
    if notification.at_time is not None:
        pieces.append(str(notification.at_time))
    if notification.strategy and notification.strategy not in (notification.title or ""):
        pieces.append("strategy={0}".format(notification.strategy))
    if notification.data_name:
        pieces.append("data={0}".format(notification.data_name))
    return " ".join(pieces)


def compose_text(notification, spec):
    """Build the channel-ready text for a notification.

    Applies the level prefix, an optional title line, the context line (backtest
    time / strategy / data name), the markdown downgrade for plain-text channels,
    the channel transform and truncation.

    Args:
        notification: Message being sent.
        spec: The target channel spec.

    Returns:
        tuple: ``(text, truncated)``.

    Raises:
        ValueError: If the message is empty or whitespace only.
    """
    text = notification.text
    if not isinstance(text, str) or not text.strip():
        raise ValueError("message text must be a non-empty string")
    parts = [level_prefix(notification.level)]
    if notification.title:
        parts[0] = "{0} {1}".format(parts[0], notification.title)
    context = context_line(notification)
    if context:
        parts.append(context)
    parts.append(text)
    composed = "\n".join(parts)
    if not spec.markdown:
        composed = strip_markdown(composed)
    if spec.transform is not None:
        composed = spec.transform(composed)
    return truncate(composed, spec.max_length, spec.byte_limited)


# ---------------------------------------------------------------------------
# Response classification helpers
# ---------------------------------------------------------------------------


def parse_json(response):
    """Parse a response body as a JSON object.

    Args:
        response: The HTTP response.

    Returns:
        dict: Parsed body, or an empty dict when the body is not a JSON object.
    """
    try:
        data = json.loads(response.text() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def retry_after_from_header(response):
    """Read a ``Retry-After`` header as seconds.

    Args:
        response: The HTTP response.

    Returns:
        float or None: Parsed delay.
    """
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def status_attempt(response, retry_after=None):
    """Classify a response by HTTP status alone.

    Args:
        response: The HTTP response.
        retry_after: Optional parsed retry hint.

    Returns:
        Attempt or None: An attempt for non-2xx statuses, ``None`` for 2xx.
    """
    if 200 <= response.status < 300:
        return None
    detail = mask_text("HTTP {0}".format(response.status))
    if response.status in (401, 403):
        return Attempt(False, "auth", detail)
    if response.status == 429:
        return Attempt(False, "rate_limit", detail, retry_after=retry_after)
    if response.status >= 500:
        return Attempt(False, "server", detail)
    return Attempt(False, "bad_request", detail)


def code_attempt(code, message="", auth=(), rate=(), permission=(), not_bound=()):
    """Classify a channel-specific error code.

    Args:
        code: The channel's error code.
        message: Channel-provided description.
        auth: Codes meaning "credentials rejected".
        rate: Codes meaning "rate limited".
        permission: Codes meaning "not permitted / user disabled".
        not_bound: Codes meaning "session anchor missing".

    Returns:
        Attempt: The classified attempt.
    """
    detail = mask_text(str(message) or "code={0}".format(code))
    if code in auth:
        return Attempt(False, "auth", detail)
    if code in rate:
        return Attempt(False, "rate_limit", detail)
    if code in permission:
        return Attempt(False, "permission", detail)
    if code in not_bound:
        return Attempt(False, "not_bound", detail)
    return Attempt(False, "bad_request", detail)


def _json_request(method, url, payload, headers=None):
    """Build a JSON :class:`HttpRequest`.

    Args:
        method: HTTP verb.
        url: Target URL.
        payload: JSON-serialisable body.
        headers: Extra headers.

    Returns:
        HttpRequest: The request.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    merged = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        merged.update(headers)
    return HttpRequest(method=method, url=url, headers=merged, body=body)


# ---------------------------------------------------------------------------
# Channel specs
# ---------------------------------------------------------------------------


def _build_dingtalk(notification, config, text):
    """Build a DingTalk custom-robot request.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text (markdown).

    Returns:
        HttpRequest: The request.
    """
    token = quote(str(config["access_token"]), safe="")
    url = "https://oapi.dingtalk.com/robot/send?access_token={0}".format(token)
    secret = config.get("secret")
    if secret:
        timestamp, sign = dingtalk_sign(secret)
        url = "{0}&timestamp={1}&sign={2}".format(url, timestamp, sign)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": notification.title or "backtrader", "text": text},
    }
    if notification.at_all:
        payload["at"] = {"isAtAll": True}
    return _json_request("POST", url, payload)


def _ok_dingtalk(response):
    """Classify a DingTalk response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response)
    if attempt is not None:
        return attempt
    data = parse_json(response)
    code = data.get("errcode", 0)
    if code == 0:
        return Attempt(True)
    return code_attempt(
        code,
        data.get("errmsg", ""),
        auth=(300001, 310000, 400013),
        rate=(130101, 410100),
    )


def _build_wecom_bot(notification, config, text):
    """Build a WeCom group-robot request.

    ``markdown`` is used by default; the mention form switches to ``text``
    because WeCom only supports mentions on text messages.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text (markdown).

    Returns:
        HttpRequest: The request.
    """
    key = quote(str(config["key"]), safe="")
    url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={0}".format(key)
    if notification.at_all:
        payload = {
            "msgtype": "text",
            "text": {"content": strip_markdown(text), "mentioned_list": ["@all"]},
        }
    else:
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
    return _json_request("POST", url, payload)


def _ok_wecom(response):
    """Classify a WeCom group-robot response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response)
    if attempt is not None:
        return attempt
    data = parse_json(response)
    code = data.get("errcode", 0)
    if code == 0:
        return Attempt(True)
    return code_attempt(code, data.get("errmsg", ""), auth=(93000, 40001), rate=(45009,))


def _build_feishu_bot(notification, config, text):
    """Build a Feishu custom-robot request.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text (plain, since the text message type does not render
            markdown - see ``evidence/channel-facts.json``).

    Returns:
        HttpRequest: The request.
    """
    url = "https://open.feishu.cn/open-apis/bot/v2/hook/{0}".format(
        quote(str(config["token"]), safe="")
    )
    payload = {"msg_type": "text", "content": {"text": text}}
    secret = config.get("secret")
    if secret:
        timestamp, sign = feishu_sign(secret)
        payload["timestamp"] = str(timestamp)
        payload["sign"] = sign
    return _json_request("POST", url, payload)


def _ok_feishu(response):
    """Classify a Feishu custom-robot response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response, retry_after=retry_after_from_header(response))
    if attempt is not None:
        return attempt
    data = parse_json(response)
    code = data.get("code", data.get("StatusCode", 0))
    if code in (0, None):
        return Attempt(True)
    return code_attempt(
        code, data.get("msg", data.get("StatusMessage", "")), auth=(19001, 19021), rate=(11232,)
    )


def _build_slack(notification, config, text):
    """Build a Slack incoming-webhook request.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text.

    Returns:
        HttpRequest: The request.
    """
    return _json_request("POST", str(config["webhook_url"]), {"text": text})


def _ok_slack(response):
    """Classify a Slack response (HTTP 200 with body ``ok``).

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response, retry_after=retry_after_from_header(response))
    if attempt is not None:
        return attempt
    if response.text().strip() == "ok":
        return Attempt(True)
    return Attempt(False, "bad_request", mask_text(response.text()[:200]))


def _build_discord(notification, config, text):
    """Build a Discord webhook request.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text.

    Returns:
        HttpRequest: The request.
    """
    return _json_request("POST", str(config["webhook_url"]), {"content": text})


def _ok_discord(response):
    """Classify a Discord response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    retry_after = retry_after_from_header(response)
    if retry_after is None:
        data = parse_json(response)
        value = data.get("retry_after")
        if isinstance(value, (int, float)):
            retry_after = float(value)
    attempt = status_attempt(response, retry_after=retry_after)
    if attempt is not None:
        return attempt
    return Attempt(True)


def _build_ntfy(notification, config, text):
    """Build an ntfy publish request.

    A JSON publish body is used instead of the header/path form because HTTP
    header values cannot carry non-ASCII text (see the M0 evidence file).

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text.

    Returns:
        HttpRequest: The request.
    """
    base = str(config.get("base_url") or "https://ntfy.sh").rstrip("/")
    payload = {"topic": config["topic"], "message": text}
    if notification.title:
        payload["title"] = notification.title
    if config.get("token"):
        payload["token"] = config["token"]
    return _json_request("POST", base + "/", payload)


def _ok_ntfy(response):
    """Classify an ntfy response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response, retry_after=retry_after_from_header(response))
    return attempt if attempt is not None else Attempt(True)


def _build_gotify(notification, config, text):
    """Build a Gotify message request.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text.

    Returns:
        HttpRequest: The request.
    """
    base = str(config["base_url"]).rstrip("/")
    url = "{0}/message?token={1}".format(base, quote(str(config["token"]), safe=""))
    payload = {
        "title": notification.title or "backtrader",
        "message": text,
        "priority": int(config.get("priority", 5)),
    }
    return _json_request("POST", url, payload)


def _ok_gotify(response):
    """Classify a Gotify response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response)
    return attempt if attempt is not None else Attempt(True)


def _build_bark(notification, config, text):
    """Build a Bark push request.

    Args:
        notification: Message being sent.
        config: Resolved credentials.
        text: Adapted text.

    Returns:
        HttpRequest: The request.
    """
    base = str(config.get("base_url") or "https://api.day.app").rstrip("/")
    payload = {
        "device_key": config["device_key"],
        "title": notification.title or "backtrader",
        "body": text,
    }
    return _json_request("POST", base + "/push", payload)


def _ok_bark(response):
    """Classify a Bark response.

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response)
    if attempt is not None:
        return attempt
    data = parse_json(response)
    code = data.get("code")
    if code in (200, None):
        return Attempt(True)
    return code_attempt(code, data.get("message", ""))


def render_template(template, notification, text):
    """Render a user body template with ``{text}``/``{title}``/``{level}``.

    ``{{`` and ``}}`` escape literal braces so messages containing braces are
    not mangled.

    Args:
        template: The template string.
        notification: Message being sent.
        text: Adapted text.

    Returns:
        str: The rendered body.
    """
    sentinel_open, sentinel_close = "\x00", "\x01"
    rendered = template.replace("{{", sentinel_open).replace("}}", sentinel_close)
    rendered = rendered.replace("{text}", text)
    rendered = rendered.replace("{title}", notification.title or "")
    rendered = rendered.replace("{level}", notification.level)
    return rendered.replace(sentinel_open, "{").replace(sentinel_close, "}")


def render_value(value, notification, text):
    """Substitute placeholders recursively inside a JSON structure.

    Used for ``body_json`` payloads: because the structure is serialised with
    ``json.dumps`` afterwards, newlines and quotes in the message are escaped
    correctly and a JSON body cannot be broken by message content.

    Args:
        value: Mapping, sequence, string or scalar.
        notification: Message being sent.
        text: Adapted text.

    Returns:
        object: The rendered structure.
    """
    if isinstance(value, dict):
        return {key: render_value(item, notification, text) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [render_value(item, notification, text) for item in value]
    if isinstance(value, str):
        return render_template(value, notification, text)
    return value


def _build_webhook(notification, config, text):
    """Build a user-defined webhook request.

    Three body forms are supported, in priority order:

    1. ``body_json`` - a structure whose string values are substituted and then
       serialised with ``json.dumps`` (safe for messages containing newlines).
    2. ``body_template`` - a raw template string; the caller owns escaping and
       may use ``{{``/``}}`` for literal braces.
    3. neither - the adapted text is sent as ``text/plain``.

    Args:
        notification: Message being sent.
        config: Resolved credentials (``url``, optional ``method``, ``headers``,
            ``body_json``, ``body_template``, ``content_type``).
        text: Adapted text.

    Returns:
        HttpRequest: The request.
    """
    method = str(config.get("method") or "POST").upper()
    headers = dict(config.get("headers") or {})
    body_json = config.get("body_json")
    template = config.get("body_template")
    if body_json is not None:
        rendered = render_value(body_json, notification, text)
        body = json.dumps(rendered, ensure_ascii=False).encode("utf-8")
        headers.setdefault(
            "Content-Type", str(config.get("content_type") or "application/json; charset=utf-8")
        )
    elif template is not None:
        body = render_template(str(template), notification, text).encode("utf-8")
        headers.setdefault(
            "Content-Type", str(config.get("content_type") or "application/json; charset=utf-8")
        )
    else:
        body = text.encode("utf-8")
        headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    return HttpRequest(method=method, url=str(config["url"]), headers=headers, body=body)


def _ok_webhook(response):
    """Classify a user-defined webhook response (2xx by default).

    Args:
        response: The HTTP response.

    Returns:
        Attempt: The outcome.
    """
    attempt = status_attempt(response, retry_after=retry_after_from_header(response))
    return attempt if attempt is not None else Attempt(True)


CHANNEL_SPECS: Dict[str, ChannelSpec] = {
    "dingtalk": ChannelSpec(
        id="dingtalk",
        requires=("access_token",),
        optional=("secret",),
        rate_limit=(20, None),
        max_length=None,
        markdown=True,
        supports_at_all=True,
        build=_build_dingtalk,
        is_ok=_ok_dingtalk,
    ),
    "wecom_bot": ChannelSpec(
        id="wecom_bot",
        requires=("key",),
        optional=(),
        rate_limit=(20, None),
        max_length=2048,
        byte_limited=True,
        markdown=True,
        supports_at_all=True,
        build=_build_wecom_bot,
        is_ok=_ok_wecom,
    ),
    "feishu_bot": ChannelSpec(
        id="feishu_bot",
        requires=("token",),
        optional=("secret",),
        rate_limit=(100, 5),
        max_length=None,
        markdown=False,
        supports_at_all=False,
        build=_build_feishu_bot,
        is_ok=_ok_feishu,
    ),
    "slack": ChannelSpec(
        id="slack",
        requires=("webhook_url",),
        optional=(),
        rate_limit=(None, 1),
        max_length=4000,
        markdown=True,
        supports_at_all=False,
        build=_build_slack,
        is_ok=_ok_slack,
    ),
    "discord": ChannelSpec(
        id="discord",
        requires=("webhook_url",),
        optional=(),
        rate_limit=(None, 2.5),
        max_length=2000,
        markdown=True,
        supports_at_all=False,
        build=_build_discord,
        is_ok=_ok_discord,
    ),
    "ntfy": ChannelSpec(
        id="ntfy",
        requires=("topic",),
        optional=("token", "base_url"),
        rate_limit=(None, None),
        max_length=None,
        markdown=False,
        supports_at_all=False,
        build=_build_ntfy,
        is_ok=_ok_ntfy,
    ),
    "gotify": ChannelSpec(
        id="gotify",
        requires=("base_url", "token"),
        optional=("priority",),
        rate_limit=(None, None),
        max_length=None,
        markdown=False,
        supports_at_all=False,
        build=_build_gotify,
        is_ok=_ok_gotify,
    ),
    "bark": ChannelSpec(
        id="bark",
        requires=("device_key",),
        optional=("base_url",),
        rate_limit=(None, None),
        max_length=None,
        markdown=False,
        supports_at_all=False,
        build=_build_bark,
        is_ok=_ok_bark,
    ),
    "webhook": ChannelSpec(
        id="webhook",
        requires=("url",),
        optional=(
            "method",
            "headers",
            "body_json",
            "body_template",
            "content_type",
            "max_length",
        ),
        rate_limit=(None, None),
        max_length=None,
        markdown=False,
        supports_at_all=False,
        build=_build_webhook,
        is_ok=_ok_webhook,
    ),
}


# ---------------------------------------------------------------------------
# Generic driver
# ---------------------------------------------------------------------------


class DeclarativeDriver:
    """Deliver notifications through a :class:`ChannelSpec`.

    Holds no credentials in its ``repr`` and performs exactly one HTTP request
    per :meth:`deliver` call; retries and rate limiting belong to the core.
    """

    def __init__(self, spec, config, transport, timeout=10.0):
        """Store the spec, resolved config and transport.

        Args:
            spec: The channel spec.
            config: Resolved credential/config mapping.
            transport: HTTP transport to use.
            timeout: Per-request timeout in seconds.

        Raises:
            ValueError: If the spec has no declarative build/is_ok hooks.
        """
        if spec.build is None or spec.is_ok is None:
            raise ValueError(
                "channel {0!r} has no declarative build/is_ok; use its custom driver".format(
                    spec.id
                )
            )
        self._spec = spec
        self._config = dict(config)
        self._transport = transport
        self._timeout = timeout

    def __repr__(self):
        """Return a credential-free representation."""
        return "{0}(channel={1!r})".format(type(self).__name__, self._spec.id)

    @property
    def spec(self):
        """Return the channel spec."""
        return self._spec

    def deliver(self, notification, timeout=None):
        """Send one notification.

        Args:
            notification: Message to send.
            timeout: Per-call timeout override.

        Returns:
            Attempt: The outcome; transport failures are classified, never
            raised.
        """
        text, truncated = compose_text(notification, self._spec)
        build, is_ok = self._spec.build, self._spec.is_ok
        if build is None or is_ok is None:  # pragma: no cover - guarded in __init__
            raise ValueError("channel {0!r} has no declarative build/is_ok".format(self._spec.id))
        request = build(notification, self._config, text)
        request = HttpRequest(
            method=request.method,
            url=request.url,
            headers=request.headers,
            body=request.body,
            timeout=float(timeout if timeout is not None else self._timeout),
        )
        try:
            response = self._transport.send(request)
        except TransportError as exc:
            return Attempt(False, exc.kind, mask_text(str(exc)), truncated=truncated)
        attempt = is_ok(response)
        if truncated and attempt.ok:
            return Attempt(True, truncated=True)
        if truncated:
            return Attempt(
                attempt.ok, attempt.category, attempt.error, attempt.retry_after, truncated=True
            )
        return attempt


def masked_request_summary(request):
    """Return a loggable one-line summary of a request.

    Args:
        request: The request to summarise.

    Returns:
        str: ``METHOD masked-url``.
    """
    return "{0} {1}".format(request.method, mask_url(request.url))
