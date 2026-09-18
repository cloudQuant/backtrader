"""Notification delivery for backtrader (iteration 32).

Public entry points::

    import backtrader as bt

    bt.configure_notifications([
        {"channel": "dingtalk", "access_token": "...", "secret": "..."},
        {"channel": "telegram", "bot_token": "...", "chat_id": "..."},
    ])

    class MyStrategy(bt.Strategy):
        def next(self):
            if self.position.size == 0 and self.signal[0] > 0:
                self.send_message("entry signal", level="warning")

    bt.flush_notifications()          # long-running processes only

Design rules worth knowing before using this module:

- **Opt-in and silent by default.** Nothing is emitted, written, connected or
  started until :func:`configure_notifications` is called.
- **Asynchronous by default.** ``send_message`` enqueues and returns
  immediately; each channel instance has its own worker thread, so one throttled
  channel never delays another. Pass ``wait=True`` for a synchronous send.
- **Failures never reach the strategy.** Every result is classified into
  :data:`ERROR_CATEGORIES` and returned in a :class:`SendResult`.
- **Best effort, not guaranteed delivery.** Nothing is persisted across a crash;
  use multiple channels for alerts that must not be missed.
- **Zero new dependencies.** HTTP goes through the standard library shim,
  email through ``smtplib``.

See ``docs/NOTIFICATIONS_GUIDELINES.md`` for channel setup and troubleshooting.
"""

from .channels import LEVELS, Notification
from .config import (
    PUBLIC_CHANNELS,
    channel_requires,
    configure_notifications,
    configure_notifications_from_env,
    flush_notifications,
    get_notifier,
    notification_stats,
    reset_notifications,
    send_message,
    update_anchor,
)
from .core import ERROR_CATEGORIES, ChannelOutcome, SendResult
from .security import mask_text, mask_url
from .session import (
    bind_qq_bot as _bind_qq_bot,
    bind_wechat_clawbot as _bind_wechat_clawbot,
    default_anchor_path,
    load_anchor,
    persist_anchor,
)
from .transport import (
    HttpRequest,
    HttpResponse,
    SmtpEnvelope,
    SmtpError,
    SmtplibSender,
    TransportError,
    UrllibTransport,
)

__all__ = [
    "ERROR_CATEGORIES",
    "ChannelOutcome",
    "LEVELS",
    "Notification",
    "PUBLIC_CHANNELS",
    "SendResult",
    "HttpRequest",
    "HttpResponse",
    "SmtpEnvelope",
    "SmtpError",
    "SmtplibSender",
    "TransportError",
    "UrllibTransport",
    "bind_qq_bot",
    "bind_wechat_clawbot",
    "channel_requires",
    "configure_notifications",
    "configure_notifications_from_env",
    "default_anchor_path",
    "flush_notifications",
    "get_notifier",
    "load_anchor",
    "mask_text",
    "mask_url",
    "notification_stats",
    "persist_anchor",
    "poll_clawbot_once",
    "reset_notifications",
    "send_message",
    "update_anchor",
]


def _transport_for_binding():
    """Return the transport used to bind session channels.

    Returns:
        object: The notifier's transport when configured, else a default one.
    """
    notifier = get_notifier()
    if notifier is not None and getattr(notifier, "transport", None) is not None:
        return notifier.transport
    return UrllibTransport()


def bind_wechat_clawbot(
    qr_callback=None, persist_path=None, timeout=30.0, poll_interval=2.0, max_polls=150
):
    """Run the ClawBot QR login, persist the anchor and apply it live.

    Args:
        qr_callback: Optional ``callable(url)`` used to display the QR target.
        persist_path: Anchor file path; defaults to
            ``~/.backtrader/notifications/wechat_clawbot.json`` (mode ``0600``).
        timeout: Request timeout in seconds.
        poll_interval: Seconds between QR status polls.
        max_polls: Maximum number of status polls.

    Returns:
        dict: The anchor, or an empty dict when binding did not complete.

    Note:
        The iLink protocol is not officially documented (see the M0 evidence
        file); verify against a gray-release account before relying on it.
    """
    path = persist_path or default_anchor_path("wechat_clawbot")
    anchor = _bind_wechat_clawbot(
        _transport_for_binding(),
        qr_callback=qr_callback,
        persist_path=path,
        timeout=timeout,
        poll_interval=poll_interval,
        max_polls=max_polls,
    )
    if anchor:
        update_anchor("wechat_clawbot", anchor)
    return anchor


def bind_qq_bot(user_openid=None, group_openid=None, persist_path=None):
    """Register a QQ anchor explicitly and apply it live.

    Automatic binding needs an event subscription (WebSocket or a public
    webhook); the standard library has no WebSocket client and adding one would
    break the zero-dependency rule, so the anchor is supplied by the caller.

    Args:
        user_openid: Single-chat anchor.
        group_openid: Group-chat anchor.
        persist_path: Anchor file path; defaults to
            ``~/.backtrader/notifications/qq_bot.json`` (mode ``0600``).

    Returns:
        dict: The anchor mapping.

    Raises:
        ValueError: If neither anchor is supplied.
    """
    path = persist_path or default_anchor_path("qq_bot")
    anchor = _bind_qq_bot(user_openid=user_openid, group_openid=group_openid, persist_path=path)
    update_anchor("qq_bot", anchor)
    return anchor


def poll_clawbot_once(timeout=None):
    """Refresh WeChat ClawBot anchors from pending inbound messages.

    The refresh window (a new inbound message is required periodically) is not
    maintained by a background thread, so a long-running process should call
    this periodically - for example from ``Strategy.stop`` or a timer.

    Args:
        timeout: Request timeout override.

    Returns:
        int: Number of ClawBot instances successfully polled.
    """
    notifier = get_notifier()
    if notifier is None:
        return 0
    polled = 0
    for runtime in notifier.instances_for("wechat_clawbot"):
        poll_once = getattr(runtime.driver, "poll_once", None)
        if poll_once is None:
            continue
        if poll_once(timeout).ok:
            polled += 1
    return polled
