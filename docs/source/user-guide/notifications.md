# Notification Delivery

Backtrader's notification API delivers opt-in, human-facing alerts from a
strategy. It is intentionally separate from the logging API:

| Concern | Logging | Notifications |
| --- | --- | --- |
| Purpose | Local process records and diagnosis | Alert people through a configured channel |
| Default | Silent | Silent; no queue, worker, file, or network activity |
| Reliability | Local best effort | Best effort; do not treat it as durable delivery |

Configure notifications explicitly before running a strategy. The API never
automatically sends an order, trade, or error event.

## Quick start

```python
import os
import backtrader as bt

bt.configure_notifications([
    {
        "channel": "dingtalk",
        "access_token": os.environ["BT_DINGTALK_TOKEN"],
    },
    {
        "channel": "telegram",
        "bot_token": os.environ["BT_TELEGRAM_TOKEN"],
        "chat_id": os.environ["BT_TELEGRAM_CHAT_ID"],
    },
], dedup_cooldown=300.0)


class AlertingStrategy(bt.Strategy):
    def next(self):
        if self.signal[0] > 0:
            # The default is asynchronous and suitable for the strategy hot path.
            # Backtrader adds the strategy name, data name, and backtest timestamp.
            self.send_message(
                "entry signal",
                level="warning",
                dedup_key="entry-signal",
            )

    def stop(self):
        # Synchronize only from a low-frequency path when an immediate result matters.
        result = self.send_message("backtest complete", wait=True, timeout=3.0)
        print(result.outcomes)


results = cerebro.run()
# In a controlled shutdown, wait for queued asynchronous notifications.
bt.flush_notifications(timeout=10.0)
```

`Strategy.send_message()` is a convenience wrapper around
`bt.send_message()`. It adds strategy context, but both entry points return a
`SendResult` instead of raising delivery errors. Empty text, an invalid level,
or an unknown channel ID are programming errors and raise `ValueError`.

## Delivery model and shutdown

- A call without `wait=True` uses a non-blocking enqueue operation. Every
  channel instance has its own bounded queue and daemon worker, so retry or
  rate-limit waiting on one channel does not block another channel.
- `wait=True` performs synchronous delivery, returns the real per-channel
  result, and honors the optional per-request `timeout`. Do not use it in
  `next()` or a tick loop.
- `bt.flush_notifications(timeout=...)` waits for every configured queue to
  drain and returns `True` or `False`. Call it after `cerebro.run()` in a
  long-running or controlled-shutdown process.
- A normal Python interpreter exit has a best-effort inline drain for queued
  messages. It cannot make delivery durable: a crash, kill signal, process
  loss, or channel-side failure can still lose a message. Use multiple channels
  and local logs for important alerts.

`bt.notification_stats()` returns a read-only per-instance snapshot containing
`sent`, `failed`, `retried`, `dropped`, `deduped`, `rate_waited_ms`, and
`truncated`. In asynchronous mode, an `ok=True` outcome means the message was
accepted into that channel's queue; it is not a remote-delivery receipt.

## Supported channels and configuration

The public channel IDs are:

| Family | IDs |
| --- | --- |
| Webhook / bot | `dingtalk`, `wecom_bot`, `feishu_bot`, `telegram`, `webhook`, `slack`, `discord`, `ntfy`, `gotify`, `bark` |
| Account-based | `email`, `wecom_app` |
| Session-anchored | `wechat_clawbot`, `qq_bot` |

Use `channel_requires()` if a tool needs to discover required fields without
importing private implementation details:

```python
from backtrader.notifications import channel_requires

assert channel_requires("dingtalk") == ("access_token",)
assert channel_requires("email") == ("host", "port", "to")
```

For the full field matrix, content-format limits, and official-source evidence,
see the repository's [Notifications Guidelines](https://github.com/cloudQuant/backtrader/blob/dev/docs/NOTIFICATIONS_GUIDELINES.md).
Never put a token, secret, app password, or session-anchor file in version
control.

### Environment-variable setup

`configure_notifications_from_env()` makes a credential-free deployment
configuration possible. List channels with `BT_NOTIFY_CHANNELS`, then add each
channel's uppercase fields:

```bash
export BT_NOTIFY_CHANNELS=dingtalk,telegram
export BT_NOTIFY_DINGTALK_ACCESS_TOKEN='...'
export BT_NOTIFY_TELEGRAM_BOT_TOKEN='...'
export BT_NOTIFY_TELEGRAM_CHAT_ID='...'
```

```python
import backtrader as bt

bt.configure_notifications_from_env(dedup_cooldown=300.0)
```

Missing required fields fail at configuration time with `ValueError`, leaving a
previous valid configuration intact.

## Rate limits, deduplication, and failures

Use `dedup_key` to suppress repeated alerts during the configured
`dedup_cooldown`:

```python
self.send_message(
    "feed stalled",
    level="error",
    dedup_key="feed-stalled",
)
```

The library applies a local rate limit for each channel instance, with
`rate_limit_scale=0.75` by default. Queue overflow is isolated to the affected
channel (`drop_newest` by default, `drop_oldest` optional). Delivery failures
are returned as `ChannelOutcome.error_category`; common values are
`network`, `timeout`, `server`, `auth`, `permission`, `rate_limit`,
`not_bound`, `not_configured`, `deduped`, and `dropped`.

## WeChat ClawBot and QQ bots

WeChat ClawBot and QQ are not simple "token-only" push channels. Both require
an inbound relationship before an outbound message is allowed.

- **WeChat ClawBot:** complete QR/inbound binding with
  `bt.bind_wechat_clawbot()` and periodically call
  `bt.poll_clawbot_once()` in a long-running process to refresh the session
  anchor. The anchor is sensitive credential material and is stored under
  `~/.backtrader/notifications/` with restrictive permissions by default.
- **QQ bot:** explicitly register a user or group OpenID through
  `bt.bind_qq_bot(user_openid=...)` or `group_openid=...`. A WebSocket or
  public webhook is required to obtain event data automatically; this
  zero-dependency package does not create such a connection.

The framework has offline request/response coverage for both adapters. Actual
WeChat and QQ delivery still depends on your platform account, permissions,
and current platform behavior, so verify it with `scripts/notify_smoke.py` and
your own credentials before relying on it operationally.

## Multiprocessing

`cerebro.run(maxcpus>1)` child processes are silent by default to prevent an
optimization run from flooding a channel. If you explicitly set
`workers="send"`, configure the channels inside each child and remember that
local rate limiters are not shared across processes. Keeping notification
delivery in the parent process is usually safer.
