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
import backtrader as bt

bt.configure_notifications(
    [
        {"channel": "dingtalk", "access_token": "...", "secret": "..."},
        {"channel": "telegram", "bot_token": "123:ABC", "chat_id": "42"},
    ],
    dedup_cooldown=300.0,
)


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

Nothing is created until `configure_notifications()` runs: no channel object,
no worker thread, no queue, no file, and no socket. The same process can
reconfigure at any time; an invalid new configuration raises `ValueError` and
leaves the previous working configuration in place.

## Delivery model and shutdown

- A call without `wait=True` uses a non-blocking enqueue operation. Every
  channel instance has its own bounded queue and daemon worker, so retry or
  rate-limit waiting on one channel does not block another channel. Ordering is
  preserved inside one channel instance.
- `wait=True` performs synchronous delivery, returns the real per-channel
  result, and honors the optional per-request `timeout`. Channels are then
  visited sequentially, so the worst-case duration is roughly the sum of
  `attempts x timeout + backoff + rate-limit wait`. Do not use it in `next()`
  or a tick loop.
- `bt.flush_notifications(timeout=...)` waits for every configured queue to
  drain and returns `True` or `False`. Call it after `cerebro.run()` in a
  long-running or controlled-shutdown process.
- A normal Python interpreter exit has a best-effort inline drain for queued
  messages. It cannot make delivery durable: a crash, kill signal, process
  loss, or channel-side failure can still lose a message. Use multiple channels
  and local logs for important alerts.

## Configuration

### Inline channel entries

`configure_notifications()` takes a sequence of dictionaries. Each dictionary
needs a `channel` key; the remaining keys are that channel's credentials:

```python
bt.configure_notifications(
    [
        {"channel": "wecom_bot", "key": "..."},
        {"channel": "email", "host": "smtp.example.com", "port": 465,
         "ssl": True, "user": "bot@example.com", "password": "...",
         "to": ["you@example.com"]},
    ],
    queue_size=500,
    request_timeout=8.0,
)
```

Missing required credentials fail at configuration time with a `ValueError`
that names the channel and the missing fields. An empty sequence is valid and
means "configured, but no channels"; sending then returns
`reason="no_channels"`.

The same channel may appear more than once to target several groups or
destinations. When a channel is configured more than once, every instance gets
a numeric suffix in configuration order (`dingtalk#1`, `dingtalk#2`); a single
instance keeps the plain channel ID (`wecom_bot`). Statistics, rate limits,
queues, and deduplication are isolated per instance.

### Environment-variable configuration

`configure_notifications_from_env()` makes a credential-free deployment
configuration possible. The channel list comes from `BT_NOTIFY_CHANNELS`
(comma separated); each field comes from
`BT_NOTIFY_<CHANNEL>_<FIELD>` with the channel ID and field name upper-cased:

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

Field name to variable name, for example:

| Channel | Field | Environment variable |
| --- | --- | --- |
| `dingtalk` | `access_token` | `BT_NOTIFY_DINGTALK_ACCESS_TOKEN` |
| `feishu_bot` | `secret` | `BT_NOTIFY_FEISHU_BOT_SECRET` |
| `email` | `to` | `BT_NOTIFY_EMAIL_TO` (comma separated) |
| `wecom_app` | `agentid` | `BT_NOTIFY_WECOM_APP_AGENTID` |
| `webhook` | `url` | `BT_NOTIFY_WEBHOOK_URL` |
| `wechat_clawbot` | `bot_token` | `BT_NOTIFY_WECHAT_CLAWBOT_BOT_TOKEN` |
| `qq_bot` | `appsecret` | `BT_NOTIFY_QQ_BOT_APPSECRET` |

Environment values are coerced to the types the channel expects:

- integer fields: `port`, `agentid`, `priority`, `max_length`;
- `to` is split on commas into a list;
- boolean fields accept `1`/`true`/`yes`/`on`: `ssl`, `starttls`, `sandbox`,
  `html`;
- everything else stays a string.

Use `prefix=` for a different namespace (for example one prefix per
deployment). An empty or missing `<prefix>CHANNELS` raises `ValueError`.

### Options

All options are keyword arguments of `configure_notifications()` (and are
accepted by `configure_notifications_from_env()` as well). Unknown names or
out-of-range values raise `ValueError`.

| Option | Default | Meaning |
| --- | --- | --- |
| `default_wait` | `False` | Default for `send_message(wait=...)`; `False` means enqueue. |
| `queue_size` | `1000` | Per channel-instance queue capacity. |
| `overflow` | `"drop_newest"` | Queue-full policy; `"drop_oldest"` is the other choice. |
| `rate_limit_scale` | `0.75` | Fraction of the channel's official rate used locally, leaving headroom. Must be in `(0, 1]`. |
| `dedup_cooldown` | `0.0` | Seconds during which the same `(instance, dedup_key)` is suppressed. `0` disables deduplication. |
| `max_retries` | `2` | Retries for recoverable failures. |
| `retry_backoff` | `0.5` | Base seconds for exponential backoff with jitter. |
| `request_timeout` | `10.0` | Per-request timeout used by channel drivers. |
| `rate_limit_wait_timeout` | `30.0` | Maximum wait for a local rate-limit window before the message is reported as `rate_limit`. |
| `at_all` | `False` | Allow `@all` on channels that support it, and only for `level="critical"`. |
| `log_events` | `True` | Emit notification lifecycle records through the logging API. |
| `workers` | `"silent"` | Child-process behaviour; `"silent"` blocks sends, `"send"` allows them. |

## Channel reference

The public channel IDs are:

| Family | IDs |
| --- | --- |
| Webhook / bot | `dingtalk`, `wecom_bot`, `feishu_bot`, `telegram`, `webhook`, `slack`, `discord`, `ntfy`, `gotify`, `bark` |
| Account-based | `email`, `wecom_app` |
| Session-anchored | `wechat_clawbot`, `qq_bot` |

| Channel | Required fields | Optional fields | Body format | Local rate limit | Max length |
| --- | --- | --- | --- | --- | --- |
| `dingtalk` | `access_token` | `secret` (signed robots) | markdown | 20/min | not truncated |
| `wecom_bot` | `key` | — | markdown; text when `at_all` applies | 20/min | 2048 bytes |
| `feishu_bot` | `token` | `secret` (signature) | plain text | 100/min and 5/s | not truncated |
| `telegram` | `bot_token`, `chat_id` | — | MarkdownV2 (auto-escaped) | 20/min and 1/s | 4096 chars |
| `email` | `host`, `port`, `to` (list) | `user`, `password`, `sender`, `ssl`, `starttls`, `html` | plain text or HTML | provider-defined | not truncated |
| `wecom_app` | `corpid`, `corpsecret`, `agentid`, `touser` | — | markdown; text when `at_all` applies | 30/min | 2048 bytes |
| `webhook` | `url` | `method`, `headers`, `body_json`, `body_template`, `content_type`, `max_length` | caller-defined | none | `max_length` if given |
| `slack` | `webhook_url` | — | text | 1/s | 4000 chars |
| `discord` | `webhook_url` | — | markdown | 1 per 2.5 s | 2000 chars |
| `ntfy` | `topic` | `token`, `base_url` | plain text | self-hosted | not truncated |
| `gotify` | `base_url`, `token` | `priority` | plain text | self-hosted | not truncated |
| `bark` | `device_key` | `base_url` | plain text | provider-defined | not truncated |
| `wechat_clawbot` | `bot_token`, `to_user_id` | `context_token`, `base_url` | plain text | session-anchored | not truncated |
| `qq_bot` | `appid`, `appsecret` | `user_openid`, `group_openid`, `sandbox` | plain text | 20/min | not truncated |

The rate limits are local guard rails, not a promise that the remote service
accepts that volume. They are multiplied by `rate_limit_scale`.

Use `channel_requires()` if a tool needs to discover required fields without
importing private implementation details:

```python
from backtrader.notifications import channel_requires

assert channel_requires("dingtalk") == ("access_token",)
assert channel_requires("email") == ("host", "port", "to")
```

### Chat bots

```python
bt.configure_notifications([
    {"channel": "dingtalk", "access_token": "...", "secret": "..."},
    {"channel": "wecom_bot", "key": "..."},
    {"channel": "feishu_bot", "token": "...", "secret": "..."},
    {"channel": "telegram", "bot_token": "123:ABC", "chat_id": "42"},
])
```

- `dingtalk`: `secret` is only needed for signed robots; both the access token
  and the signing secret come from the robot's own configuration page.
- `wecom_bot`: group robot webhook key. The custom robot receives markdown, but
  `@all` is only available in the text form, which the driver selects
  automatically when `at_all` applies.
- `feishu_bot`: custom bot webhook token. The `text` message type does not
  render markdown, so the driver sends plain text (markup is stripped).
- `telegram`: MarkdownV2 is escaped automatically, so ordinary text with
  `*`, `_` or `[` cannot break the message. `chat_id` may be a private chat,
  group, or channel ID that the bot can post to.

### Mail and enterprise WeChat app

```python
bt.configure_notifications([
    {
        "channel": "email",
        "host": "smtp.example.com",
        "port": 465,
        "ssl": True,                     # or starttls=True on port 587
        "user": "bot@example.com",
        "password": "...",               # prefer an app password
        "sender": "bot@example.com",     # defaults to user
        "to": ["you@example.com"],       # must be a list, not a string
        "html": False,
    },
    {
        "channel": "wecom_app",
        "corpid": "...",
        "corpsecret": "...",
        "agentid": 1000002,
        "touser": "@all",                # or "user1|user2"
    },
])
```

`port` must be an integer and `to` must be a non-empty list; both are validated
at configuration time. Use either `ssl=True` or `starttls=True`, not both.

### Generic webhook

`webhook` covers any HTTP endpoint and offers three body modes:

```python
# 1) structured JSON (recommended): json.dumps escapes the text for you
{"channel": "webhook", "url": "https://...",
 "body_json": {"text": "{text}", "level": "{level}"}}

# 2) raw template: you own the escaping; {{ and }} mean literal braces
{"channel": "webhook", "url": "https://...",
 "body_template": "level={level} text={text} raw={{literal}}",
 "content_type": "text/plain; charset=utf-8"}

# 3) neither: the rendered text is sent as text/plain
{"channel": "webhook", "url": "https://..."}
```

Placeholders are `{text}` (body including the level prefix and title),
`{title}`, and `{level}`. `method` defaults to `POST`; `headers` adds or
overrides request headers; `max_length` enables truncation for endpoints with
their own limit.

### Relay and push services

```python
bt.configure_notifications([
    {"channel": "slack", "webhook_url": "https://hooks.slack.com/services/..."},
    {"channel": "discord", "webhook_url": "https://discord.com/api/webhooks/..."},
    {"channel": "ntfy", "topic": "backtrader", "base_url": "https://ntfy.sh"},
    {"channel": "gotify", "base_url": "https://gotify.example.com",
     "token": "...", "priority": 5},
    {"channel": "bark", "device_key": "...", "base_url": "https://api.day.app"},
])
```

`ntfy` and `bark` default to their public services when `base_url` is omitted;
set it for a self-hosted server. `gotify` requires `base_url` and an
application token, and accepts an integer `priority`.

### Session-anchored channels

WeChat ClawBot and QQ are not simple "token-only" push channels. Both require
an inbound relationship before an outbound message is allowed, so a fresh
installation returns `not_bound` until you bind.

**WeChat ClawBot (iLink)**

```python
import backtrader as bt

# 1) Bind once: print the QR payload, scan it, and the anchor is persisted.
anchor = bt.bind_wechat_clawbot(qr_callback=print)
print(anchor["to_user_id"])

# 2) Configure the channel (bot_token can come from the anchor).
bt.configure_notifications([{
    "channel": "wechat_clawbot",
    "bot_token": anchor["bot_token"],
    "to_user_id": anchor["to_user_id"],
}])

# 3) In a long-running process, refresh the window from inbound messages.
bt.poll_clawbot_once()
```

- The anchor file defaults to `~/.backtrader/notifications/wechat_clawbot.json`
  (see `default_anchor_path()`); pass `persist_path=` to override it.
- Each outbound push consumes a relationship window of roughly ten messages.
  This implementation stops after eight and requires a new inbound message,
  after which `poll_clawbot_once()` refreshes the anchor. When the window is
  exhausted the result is `not_bound` with an explicit "refresh window
  exhausted" text; nothing is silently discarded.
- One ClawBot can be connected to a single agent instance at a time. If the
  bot is already bound to another assistant, polling is mutually exclusive;
  create a dedicated ClawBot for trading alerts.
- The endpoint/header/field details come from the community reverse
  engineering of the official npm package and are not confirmed by public
  documentation. Verify with a fixed message before relying on it.

**QQ bot**

```python
bt.bind_qq_bot(user_openid="...")     # direct message
bt.bind_qq_bot(group_openid="...")    # group message
```

The OpenID is issued per bot and is normally obtained from event
subscriptions. Automatic subscription requires a WebSocket or a public
webhook, which this zero-dependency package does not create, so registration is
explicit. Add `"sandbox": True` to the channel configuration to use the
sandbox base URL. A user can disable "allow active messages" in the QQ client;
that failure is classified as `permission` and is not retried.

## Sending messages

```python
bt.send_message(
    "text",                  # required, non-empty
    title="Daily report",    # optional heading (prefixes the body)
    level="warning",         # info | warning | error | critical
    channels=["telegram"],   # optional subset; all instances by default
    wait=False,              # override default_wait
    timeout=3.0,             # per-request timeout, only with wait=True
    dedup_key="daily-report",
)
```

`@all` behaviour: it is attached only when `at_all=True` was configured, the
level is `critical`, and the channel supports it (`dingtalk`, `wecom_bot`,
`wecom_app`). Other channels ignore it.

`channels=[...]` accepts public channel IDs only (`dingtalk`, not
`dingtalk#2`; an instance name raises `ValueError`). When a channel has several
instances, a plain ID resolves to its **first** instance, so omit `channels`
(the default) to reach every instance. `ChannelOutcome.channel` reports the
instance name actually used (`dingtalk#1`).

## Results, statistics, and failures

`SendResult` fields:

| Field | Meaning |
| --- | --- |
| `accepted` | The message was accepted for delivery (queued in async mode). |
| `mode` | `"async"` or `"sync"`. |
| `outcomes` | One `ChannelOutcome` per attempted channel instance. |
| `dropped` | The message could not be enqueued at all (for example overflow). |
| `reason` | High-level outcome: `ok`, `queue_full`, `failed` (sync), `not_configured`, `no_channels`, or `worker_silent`. |

`ChannelOutcome` fields: `channel`, `ok`, `error_category`, `error`
(redacted), `attempts`, `elapsed_ms`.

`error_category` values are the members of `bt.ERROR_CATEGORIES`:

| Category | Meaning |
| --- | --- |
| `network`, `timeout`, `tls` | Transport failure; retried. |
| `server` | Remote 5xx; retried. |
| `rate_limit` | Local rate-limit wait expired or the remote asked to slow down. |
| `auth` | Missing/expired credentials or a bad signature; not retried. |
| `permission` | The account or bot may not post here; not retried. |
| `bad_request` | The channel rejected the payload shape; not retried. |
| `not_bound` | Session anchor missing or its window exhausted. |
| `not_configured` | `configure_notifications()` was never called. |
| `deduped`, `dropped`, `worker_silent`, `unknown` | Local outcomes; see below. |

`bt.notification_stats()` returns a read-only per-instance snapshot containing
`sent`, `failed`, `retried`, `dropped`, `deduped`, `rate_waited_ms`, and
`truncated`. In asynchronous mode, an `ok=True` outcome means the message was
accepted into that channel's queue; it is not a remote-delivery receipt.

## Rate limits, deduplication, and truncation

Use `dedup_key` to suppress repeated alerts during the configured
`dedup_cooldown`:

```python
self.send_message("feed stalled", level="error", dedup_key="feed-stalled")
```

The library applies a local rate limit for each channel instance, with
`rate_limit_scale=0.75` by default, so a burst is spread over time instead of
being rejected. Queue overflow is isolated to the affected channel
(`drop_newest` by default, `drop_oldest` optional) and is counted in
`dropped`.

Length limits are enforced only where the channel's limit is confirmed:
`wecom_bot` and `wecom_app` (2048 bytes), `telegram` (4096 characters),
`slack` (4000), `discord` (2000), and `webhook` when `max_length` is set.
Byte-limited channels are cut on a UTF-8 boundary, and every truncated body
gets the literal marker `…（已截断 N 字符）` on a new line; because the marker is
appended after the cut, the final body can exceed the limit by its length.
Other channels are never truncated, because guessing a limit would cut messages
in the wrong place.

## Verifying a channel

Credentials normally live in environment variables (never in the repository),
which makes the bundled smoke script the fastest end-to-end check. It performs
real network I/O, so it is a manual tool and never runs in CI.

```bash
# What is still missing? Prints the required fields per channel and exits 0.
python scripts/notify_smoke.py --list-unverified

# Send one real message through the channels that have credentials.
python scripts/notify_smoke.py

# Send only through the named channels, with custom text and level.
python scripts/notify_smoke.py --channels dingtalk,telegram \
    --message "backtrader smoke" --level warning
```

The script reads `BT_NOTIFY_<CHANNEL>_<FIELD>` (override the prefix with
`--prefix`), prints a credential-free `SendResult`, and exits:

- `0` — every attempted channel reported `ok=True`;
- `1` — at least one channel failed, or no requested channel had complete
  credentials;
- `2` — unknown channel ID or a configuration error.

Sample output:

```text
mode=sync accepted=True reason=None
  dingtalk         ok=True  category=-              attempts=1 elapsed_ms=182 error=-
  telegram         ok=False category=auth           attempts=1 elapsed_ms=340 error=...
not attempted (no credentials): wecom_bot, feishu_bot, ...
```

For a channel with `wait=True`, `ok=True` means the remote endpoint accepted
the request; it still cannot prove that a human read the message.

## Troubleshooting

| Symptom | Check first |
| --- | --- |
| Nothing happens at all | `configure_notifications()` was never called; the library only warns once on stderr. |
| `reason="not_configured"` | Same as above, or the channel list is empty (`reason="no_channels"`). |
| `reason="worker_silent"` | The call runs in an optimization child process; set `workers="send"` there if it really must send. |
| `error_category="dropped"` | The queue is full: the send rate is far above the channel limit, or `queue_size` is too small. |
| `error_category="rate_limit"` | The local wait exceeded `rate_limit_wait_timeout`; lower the rate or raise the budget. |
| `error_category="auth"` | Wrong token, expired token, or a signature mismatch (DingTalk signing, Feishu signature, bot token). |
| `error_category="permission"` | The bot/account may not post there: QQ active messages disabled, WeCom app visibility scope. |
| `error_category="not_bound"` | The session anchor is missing or its refresh window is exhausted (WeChat/QQ). |
| `error_category="server"` | Remote 5xx; already retried according to `max_retries`. |
| Message is cut off | Channel length limit (see above); the body carries a truncation marker. |
| Markdown shows as raw text | That channel does not render markdown (`feishu_bot`, `ntfy`, ...); markup is stripped by the driver. |
| Anchor file is unreadable/partial | The process was killed during an in-place update; rebind or call `update_anchor()` again. |

## Multiprocessing and long-running processes

`cerebro.run(maxcpus>1)` child processes are silent by default to prevent an
optimization run from flooding a channel: sends return
`reason="worker_silent"` and nothing is queued. If you explicitly set
`workers="send"`, configure the channels inside each child and remember that
local rate limiters are not shared across processes. Keeping notification
delivery in the parent process is usually safer.

`cerebro.run()` returning does not guarantee delivery. Long-running processes
should call `bt.flush_notifications()` afterwards, and
`bt.reset_notifications()` stops the workers, discards queued messages, and
clears statistics when reconfiguring.

## Security

- Never put a token, secret, app password, or session-anchor file in version
  control. Prefer environment variables (`BT_NOTIFY_*`) or a git-ignored
  configuration file.
- On POSIX the anchor file is written `0600` inside a `0700` directory. Windows
  has no meaningful mode bits, so the implementation installs a protected DACL
  with exactly one access-control entry for the current account (shown as
  `(F)` by `icacls`), no inheritance, and no external grant. Anchors may only
  live on a local fixed volume with persistent ACLs; UNC paths, removable
  media, and unknown volumes fail closed.
- Anchor updates use the same handle in place rather than an atomic rename. A
  process killed mid-write can leave partial JSON; rebind or call
  `update_anchor()` with a fresh anchor to repair it.
- Logs, `SendResult.error`, and `repr(Notifier)` are redacted: query values
  whose key contains `token`/`key`/`secret`/`sign`/`password`, `Bearer`/`Basic`/
  `QQBot` credentials, URL passwords, and `key: value` credential pairs become
  `***`.
- Notification bodies leave the machine: do not send account numbers, keys, or
  identity documents.

## Public API summary

| Symbol | Module | Purpose |
| --- | --- | --- |
| `configure_notifications(channels, **options)` | `backtrader` | Configure channels and options; returns the notifier. |
| `configure_notifications_from_env(prefix="BT_NOTIFY_", **options)` | `backtrader` | Configure from environment variables. |
| `send_message(text, ...)` | `backtrader` | Send one message; returns `SendResult`. |
| `Strategy.send_message(text, ...)` | `backtrader` | Strategy-aware wrapper that adds run context. |
| `flush_notifications(timeout=5.0)` | `backtrader` | Wait for queues to drain. |
| `notification_stats()` | `backtrader` | Per-instance counters. |
| `reset_notifications()` | `backtrader` | Stop workers and clear state. |
| `bind_wechat_clawbot(...)` / `poll_clawbot_once(...)` | `backtrader` | Bind and refresh the WeChat ClawBot anchor. |
| `bind_qq_bot(user_openid=..., group_openid=...)` | `backtrader` | Register a QQ anchor. |
| `update_anchor(channel_id, anchor)` | `backtrader` | Apply a fresh anchor to live instances. |
| `default_anchor_path(channel_id)` / `load_anchor(path)` | `backtrader` | Anchor file location and reader. |
| `channel_requires(channel_id)` | `backtrader.notifications` | Required field names for a channel. |
| `PUBLIC_CHANNELS` / `ERROR_CATEGORIES` | `backtrader.notifications` / `backtrader` | Channel IDs and failure categories. |
| `persist_anchor(path, data)` / `get_notifier()` | `backtrader.notifications` | Low-level anchor writer and singleton accessor. |

For the field matrix's official-source evidence and the extension checklist,
see the repository's
[Notifications Guidelines](https://github.com/cloudQuant/backtrader/blob/dev/docs/NOTIFICATIONS_GUIDELINES.md).
