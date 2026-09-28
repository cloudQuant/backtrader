"""Configuration entry point and process-wide notifier singleton (D32-04).

Mirrors ``backtrader.utils.log_message.configure_logging`` in spirit:

- **opt-in and silent by default** - until ``configure_notifications`` is called
  there is no channel, no worker thread, no queue, no file and no network;
- **transactional** - the new :class:`~backtrader.notifications.core.Notifier` is
  built (and its channels validated) before the old one is replaced, so an
  invalid reconfigure never damages a working configuration;
- **process aware** - child processes default to ``worker_silent`` so
  ``cerebro.run(maxcpus>1)`` parameter sweeps cannot turn into a message storm.
"""

import atexit
import multiprocessing
import os
import threading
from typing import Any, Dict, Optional, Tuple

from .adapters import ADAPTER_SPECS, build_adapter_driver
from .channels import LEVELS, ChannelSpec, Notification, normalize_level
from .core import (
    ERROR_CATEGORIES,
    OVERFLOW_DROP_NEWEST,
    OVERFLOW_DROP_OLDEST,
    Notifier,
    SendResult,
    no_channels_result,
    silent_outcomes,
)
from .session import (
    CLAWBOT_SPEC,
    QQ_BOT_SPEC,
    QqBotDriver,
    WechatClawbotDriver,
)
from .transport import SmtplibSender, UrllibTransport

# Public channel ids in documentation order.
PUBLIC_CHANNELS: Tuple[str, ...] = (
    "dingtalk",
    "wecom_bot",
    "feishu_bot",
    "telegram",
    "email",
    "wecom_app",
    "webhook",
    "slack",
    "discord",
    "ntfy",
    "gotify",
    "bark",
    "wechat_clawbot",
    "qq_bot",
)

SESSION_SPECS: Dict[str, ChannelSpec] = {
    "wechat_clawbot": CLAWBOT_SPEC,
    "qq_bot": QQ_BOT_SPEC,
}

DEFAULT_OPTIONS: Dict[str, Any] = {
    "default_wait": False,
    "queue_size": 1000,
    "rate_limit_scale": 0.75,
    "dedup_cooldown": 0.0,
    "workers": "silent",
    "max_retries": 2,
    "retry_backoff": 0.5,
    "request_timeout": 10.0,
    "rate_limit_wait_timeout": 30.0,
    "at_all": False,
    "log_events": True,
    "overflow": OVERFLOW_DROP_NEWEST,
}

# Bounded grace period for the interpreter-shutdown flush; a throttled channel
# must not be able to hang process exit.
ATEXIT_FLUSH_TIMEOUT = 5.0

_CONFIG_LOCK = threading.RLock()
_warned_failures = set()
_notifier: Optional[Notifier] = None
_options: Optional[Dict[str, Any]] = None
_child_process_flag: Optional[bool] = None


def _warn_once(key, message):
    """Report a configuration problem without raising or repeating.

    Args:
        key: Deduplication key.
        message: Text to print on stderr.
    """
    if key in _warned_failures:
        return
    _warned_failures.add(key)
    try:
        import sys

        print("backtrader: " + message, file=sys.stderr)
    except Exception:  # nosec B110 - no remaining safe diagnostic sink
        pass


def _spec_for(channel_id):
    """Return the spec for a channel id.

    Args:
        channel_id: Public channel id.

    Returns:
        ChannelSpec: The channel spec.

    Raises:
        ValueError: If the id is not a known channel.
    """
    if channel_id in SESSION_SPECS:
        return SESSION_SPECS[channel_id]
    if channel_id in ADAPTER_SPECS:
        return ADAPTER_SPECS[channel_id]
    from .channels import CHANNEL_SPECS

    if channel_id in CHANNEL_SPECS:
        return CHANNEL_SPECS[channel_id]
    raise ValueError(
        "unknown notification channel {0!r}; known channels: {1}".format(
            channel_id, ", ".join(PUBLIC_CHANNELS)
        )
    )


def channel_requires(channel_id):
    """Return the credential field names a channel needs.

    Public capability query: tools (for example ``scripts/notify_smoke.py``) and
    user code can discover what to configure without touching private helpers.

    Args:
        channel_id: Public channel id.

    Returns:
        tuple: Required credential field names.

    Raises:
        ValueError: If the id is not a known channel.
    """
    return tuple(_spec_for(channel_id).requires)


def _build_options(overrides):
    """Merge and validate core options.

    Args:
        overrides: Caller-supplied option overrides.

    Returns:
        dict: The validated option mapping.

    Raises:
        ValueError: If an option is unknown or out of range.
    """
    options = dict(DEFAULT_OPTIONS)
    unknown = sorted(set(overrides) - set(DEFAULT_OPTIONS))
    if unknown:
        raise ValueError("unknown option(s): {0}".format(", ".join(unknown)))
    options.update(overrides)
    if options["workers"] not in ("silent", "send"):
        raise ValueError("workers must be 'silent' or 'send'")
    if options["overflow"] not in (OVERFLOW_DROP_NEWEST, OVERFLOW_DROP_OLDEST):
        raise ValueError(
            "overflow must be {0!r} or {1!r}".format(OVERFLOW_DROP_NEWEST, OVERFLOW_DROP_OLDEST)
        )
    if isinstance(options["queue_size"], bool) or not isinstance(options["queue_size"], int):
        raise ValueError("queue_size must be a positive integer")
    if options["queue_size"] <= 0:
        raise ValueError("queue_size must be a positive integer")
    if isinstance(options["max_retries"], bool) or not isinstance(options["max_retries"], int):
        raise ValueError("max_retries must be a non-negative integer")
    if options["max_retries"] < 0:
        raise ValueError("max_retries must be a non-negative integer")
    for name in ("rate_limit_scale", "dedup_cooldown", "retry_backoff", "rate_limit_wait_timeout"):
        value = options[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("{0} must be a number".format(name))
        if options[name] < 0:
            raise ValueError("{0} must be non-negative".format(name))
    if not 0 < options["rate_limit_scale"] <= 1:
        raise ValueError("rate_limit_scale must be in (0, 1]")
    if options["request_timeout"] <= 0:
        raise ValueError("request_timeout must be positive")
    for name in ("default_wait", "at_all", "log_events"):
        if not isinstance(options[name], bool):
            raise ValueError("{0} must be a bool".format(name))
    return options


def _validate_channel_config(channel_id, spec, config):
    """Validate one channel's credentials.

    Args:
        channel_id: Public channel id.
        spec: The channel spec.
        config: Credential mapping (without the ``channel`` key).

    Raises:
        ValueError: If a required credential is missing or malformed.
    """
    missing = [name for name in spec.requires if config.get(name) in (None, "")]
    if missing:
        raise ValueError(
            "channel {0!r} is missing required credential(s): {1}".format(
                channel_id, ", ".join(missing)
            )
        )
    if channel_id == "email":
        recipients = config.get("to")
        if isinstance(recipients, str) or not isinstance(recipients, (list, tuple)):
            raise ValueError("channel 'email' requires 'to' to be a list of addresses")
        if not recipients:
            raise ValueError("channel 'email' requires a non-empty 'to' list")
        try:
            int(config["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError("channel 'email' requires an integer 'port'") from exc
    if "max_length" in config and config["max_length"] is not None:
        value = config["max_length"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(
                "channel {0!r} max_length must be a positive integer".format(channel_id)
            )


def _build_driver(channel_id, spec, config, transport, smtp_sender, timeout):
    """Create the driver for one channel instance.

    Args:
        channel_id: Public channel id.
        spec: The channel spec.
        config: Validated credential mapping.
        transport: HTTP transport.
        smtp_sender: SMTP sender.
        timeout: Default request timeout in seconds.

    Returns:
        object: A driver exposing ``deliver(notification, timeout)``.
    """
    if channel_id == "wechat_clawbot":
        return WechatClawbotDriver(spec, config, transport, timeout=timeout)
    if channel_id == "qq_bot":
        return QqBotDriver(spec, config, transport, timeout=timeout)
    adapter = build_adapter_driver(
        channel_id, spec, config, transport, smtp_sender, timeout=timeout
    )
    if adapter is not None:
        return adapter
    from .channels import DeclarativeDriver

    return DeclarativeDriver(spec, config, transport, timeout=timeout)


def _resolve_channels(channel_entries, transport, smtp_sender, options):
    """Validate and resolve every channel entry.

    Args:
        channel_entries: Sequence of ``{"channel": id, ...credentials}``.
        transport: HTTP transport.
        smtp_sender: SMTP sender.
        options: Resolved core options.

    Returns:
        list: Resolved mappings with ``name``, ``spec`` and ``driver``.

    Raises:
        ValueError: On a malformed entry, an unknown channel or missing
            credentials.
    """
    entries = list(channel_entries)
    counts: Dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "channel" not in entry:
            raise ValueError("each channel entry must be a dict with a 'channel' key")
        channel_id = entry["channel"]
        if not isinstance(channel_id, str):
            raise ValueError("channel id must be a string")
        counts[channel_id] = counts.get(channel_id, 0) + 1
    seen: Dict[str, int] = {}
    resolved = []
    for entry in entries:
        channel_id = entry["channel"]
        spec = _spec_for(channel_id)
        config = {key: value for key, value in entry.items() if key != "channel"}
        _validate_channel_config(channel_id, spec, config)
        seen[channel_id] = seen.get(channel_id, 0) + 1
        if counts[channel_id] > 1:
            name = "{0}#{1}".format(channel_id, seen[channel_id])
        else:
            name = channel_id
        driver = _build_driver(
            channel_id, spec, config, transport, smtp_sender, options["request_timeout"]
        )
        resolved.append({"name": name, "spec": spec, "driver": driver, "channel": channel_id})
    return resolved


def configure_notifications(channels, **overrides):
    """Configure the notification channels (opt-in).

    Args:
        channels: Sequence of ``{"channel": <id>, ...credentials}``. An empty
            sequence is valid and means "configured with no channels".
        **overrides: Core options; see :data:`DEFAULT_OPTIONS`. Two extra keys
            are accepted for testing: ``transport`` and ``smtp_sender``.

    Returns:
        Notifier: The configured notifier.

    Raises:
        ValueError: On an unknown channel, missing credential, malformed entry
            or out-of-range option. On failure the previous configuration stays
            in place and usable.
    """
    if channels is None or isinstance(channels, (str, bytes)):
        raise ValueError("channels must be a sequence of dicts")
    transport = overrides.pop("transport", None)
    smtp_sender = overrides.pop("smtp_sender", None)
    options = _build_options(overrides)
    transport = transport if transport is not None else UrllibTransport()
    smtp_sender = smtp_sender if smtp_sender is not None else SmtplibSender()
    resolved = _resolve_channels(list(channels), transport, smtp_sender, options)
    new_notifier = Notifier(resolved, options, transport, smtp_sender)
    global _notifier, _options
    with _CONFIG_LOCK:
        previous = _notifier
        _notifier = new_notifier
        _options = options
    if previous is not None:
        previous.stop(options["request_timeout"])
    return new_notifier


def configure_notifications_from_env(prefix="BT_NOTIFY_", **overrides):
    """Configure channels from environment variables.

    Channel ids come from ``<prefix>CHANNELS`` (comma separated); each channel's
    credentials come from ``<prefix><ID>_<FIELD>`` (upper-cased), for example
    ``BT_NOTIFY_CHANNELS=dingtalk,telegram`` with
    ``BT_NOTIFY_DINGTALK_ACCESS_TOKEN`` and ``BT_NOTIFY_TELEGRAM_BOT_TOKEN``.

    Args:
        prefix: Environment variable prefix.
        **overrides: Core options passed through to
            :func:`configure_notifications`.

    Returns:
        Notifier: The configured notifier.

    Raises:
        ValueError: If no channel is requested or a required credential is
            missing.
    """
    raw = os.environ.get(prefix + "CHANNELS", "").strip()
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    if not ids:
        raise ValueError("{0}CHANNELS is empty; nothing to configure".format(prefix))
    entries = []
    for channel_id in ids:
        spec = _spec_for(channel_id)
        base = "{0}{1}_".format(prefix, channel_id.upper())
        entry = {"channel": channel_id}
        for field in tuple(spec.requires) + tuple(spec.optional):
            value = os.environ.get(base + field.upper())
            if value is not None and value != "":
                entry[field] = _coerce_env_value(field, value)
        entries.append(entry)
    return configure_notifications(entries, **overrides)


_ENV_INT_FIELDS = ("port", "agentid", "priority", "max_length")


def _coerce_env_value(field, value):
    """Coerce one environment value to the type a channel field expects.

    Args:
        field: Credential field name.
        value: Raw string value.

    Returns:
        object: ``int`` for numeric fields, a list for ``to``/``headers``-style
        comma separated values, else the original string.
    """
    if field in _ENV_INT_FIELDS:
        try:
            return int(value)
        except ValueError:
            return value
    if field == "to":
        return [item.strip() for item in value.split(",") if item.strip()]
    if field in ("ssl", "starttls", "sandbox", "html"):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return value


def get_notifier():
    """Return the configured notifier, if any.

    Returns:
        Notifier or None: The active notifier.
    """
    return _notifier


def _options_snapshot():
    """Return a copy of the active options.

    Returns:
        dict or None: Active options.
    """
    return None if _options is None else dict(_options)


def _in_child_process():
    """Return whether this process is a child of a multiprocessing parent.

    Returns:
        bool: ``True`` inside a spawned/forked worker.
    """
    global _child_process_flag
    if _child_process_flag is None:
        try:
            _child_process_flag = multiprocessing.parent_process() is not None
        except Exception:  # nosec B110 - absence of the API means "main process"
            _child_process_flag = False
    return _child_process_flag


def _child_sending_allowed():
    """Return whether sending is permitted in the current child process.

    Returns:
        bool: ``True`` when running in the main process, or in a child whose
        configuration explicitly opted in with ``workers="send"``.
    """
    if not _in_child_process():
        return True
    options = _options
    return bool(options and options["workers"] == "send" and _notifier is not None)


def send_message(
    text,
    *,
    title=None,
    level="info",
    channels=None,
    wait=None,
    timeout=None,
    dedup_key=None,
    strategy=None,
    data_name=None,
    at_time=None,
):
    """Send one notification (asynchronous by default).

    Args:
        text: Message body; must be a non-empty string.
        title: Optional title.
        level: ``info``/``warning``/``error``/``critical`` (any case).
        channels: Optional subset of channel ids.
        wait: ``True`` sends synchronously and returns delivery results;
            ``None`` uses the configured default.
        timeout: Per-request timeout, only honoured when ``wait`` is true.
        dedup_key: Deduplication key.
        strategy: Strategy class name (injected by ``Strategy.send_message``).
        data_name: Data feed name (injected by ``Strategy.send_message``).
        at_time: Backtest timestamp (injected by ``Strategy.send_message``).

    Returns:
        SendResult: Never raises for delivery problems; programming errors
        (empty text, unknown level, unknown channel id) raise ``ValueError``.

    Raises:
        ValueError: On empty text, invalid level or unknown channel id.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("message text must be a non-empty string")
    normalized_level = normalize_level(level)
    if channels is not None and not isinstance(channels, (list, tuple)):
        raise ValueError("channels must be a list of channel ids or None")
    requested = None
    if channels is not None:
        requested = []
        for name in channels:
            _spec_for(name)
            requested.append(name)
    if not _child_sending_allowed():
        return SendResult(
            accepted=False,
            mode="async",
            outcomes=silent_outcomes(requested, "worker_silent", "child process does not send"),
            dropped=False,
            reason="worker_silent",
        )
    notifier = _notifier
    if notifier is None:
        _warn_once(
            "not-configured",
            "notifications are not configured; call bt.configure_notifications(...) first",
        )
        return SendResult(
            accepted=False, mode="async", outcomes=(), dropped=False, reason="not_configured"
        )
    if not notifier.instance_names():
        return no_channels_result()
    options = _options or DEFAULT_OPTIONS
    notification = Notification(
        text=text,
        title=title,
        level=normalized_level,
        at_time=at_time,
        strategy=strategy,
        data_name=data_name,
        dedup_key=dedup_key,
        at_all=bool(options["at_all"] and normalized_level == "critical"),
    )
    effective_wait = options["default_wait"] if wait is None else bool(wait)
    if effective_wait:
        return notifier.send_now(notification, requested, timeout)
    return notifier.enqueue(notification, requested)


def flush_notifications(timeout=5.0):
    """Wait for queued notifications to be delivered.

    Args:
        timeout: Maximum seconds to wait.

    Returns:
        bool: ``True`` when every queue drained (or nothing is configured).
    """
    notifier = _notifier
    if notifier is None:
        return True
    return notifier.flush(timeout)


def reset_notifications():
    """Stop every worker, discard queued messages and clear statistics."""
    global _notifier, _options
    with _CONFIG_LOCK:
        notifier = _notifier
        _notifier = None
        _options = None
    if notifier is not None:
        notifier.stop()
    _warned_failures.clear()


def notification_stats():
    """Return a read-only snapshot of per-channel statistics.

    Returns:
        dict: Instance name to statistic mapping (empty when unconfigured).
    """
    notifier = _notifier
    if notifier is None:
        return {}
    return notifier.stats()


def update_anchor(channel_id, anchor):
    """Apply a freshly bound session anchor to live channel instances.

    Args:
        channel_id: ``wechat_clawbot`` or ``qq_bot``.
        anchor: Mapping returned by ``bind_wechat_clawbot``/``bind_qq_bot``.

    Returns:
        int: Number of channel instances updated.
    """
    notifier = _notifier
    if notifier is None:
        return 0
    updated = 0
    for runtime in notifier.instances_for(channel_id):
        apply_anchor = getattr(runtime.driver, "apply_anchor", None)
        if apply_anchor is None:
            continue
        apply_anchor(anchor)
        updated += 1
    return updated


def _after_fork():
    """Reset fork-unsafe state in the child process.

    Worker threads do not survive ``fork``; keeping a stale reference would make
    the child believe a worker exists while nothing can ever be delivered.
    """
    global _CONFIG_LOCK, _notifier, _child_process_flag, _warned_failures
    _CONFIG_LOCK = threading.RLock()
    _notifier = None
    _child_process_flag = None
    _warned_failures = set()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def _atexit_flush():
    """Flush pending notifications when the interpreter shuts down (D32-04 边界 6).

    Worker threads are daemons, and CPython stops them before ``atexit``
    callbacks run - so this must send inline (``drain_and_deliver``) rather than
    wait for the queues (``flush``), which would burn the timeout and still drop
    the messages. Without this hook a script that queues messages and then exits
    loses them silently - the common "run a backtest, send a summary" case.
    """
    notifier = _notifier
    if notifier is None:
        return
    try:
        notifier.drain_and_deliver(ATEXIT_FLUSH_TIMEOUT)
    except Exception:  # nosec B110 - at shutdown stderr/logging may be gone already
        pass


atexit.register(_atexit_flush)

# Re-exported so callers can assert the contract without importing two modules.
__all__ = [
    "PUBLIC_CHANNELS",
    "ERROR_CATEGORIES",
    "LEVELS",
    "channel_requires",
    "configure_notifications",
    "configure_notifications_from_env",
    "flush_notifications",
    "get_notifier",
    "notification_stats",
    "reset_notifications",
    "send_message",
    "update_anchor",
]
