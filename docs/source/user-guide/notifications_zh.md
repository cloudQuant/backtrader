# 通知外发

Backtrader 的通知 API 用于从策略中发送**显式配置**的、面向人的告警。它与日志
体系刻意分离：

| 关注点 | 日志 | 通知 |
| --- | --- | --- |
| 目的 | 本地过程记录与排错 | 通过已配置渠道向人告警 |
| 默认行为 | 静默 | 静默；不创建队列、worker、文件或网络请求 |
| 可靠性 | 本地尽力写入 | 尽力而为；不能视为持久化送达 |

通知必须在策略运行前显式配置；框架不会自动把订单、成交或错误事件外发。

## 快速开始

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
            # 默认异步，可在策略热路径中调用。
            # 框架会自动附加策略名、数据源名和回测时间。
            self.send_message(
                "entry signal",
                level="warning",
                dedup_key="entry-signal",
            )

    def stop(self):
        # 只有需要立即获得结果的低频路径才使用同步发送。
        result = self.send_message("backtest complete", wait=True, timeout=3.0)
        print(result.outcomes)


results = cerebro.run()
# 在受控退出前，等待已经入队的异步通知。
bt.flush_notifications(timeout=10.0)
```

`Strategy.send_message()` 是 `bt.send_message()` 的策略内便捷封装，会补充策略
上下文；两种入口均返回 `SendResult`，不会把投递类错误抛进策略。空正文、非法
`level` 或未知渠道 ID 属于编程错误，仍会抛出 `ValueError`。

调用 `configure_notifications()` 之前不会创建任何东西：没有渠道对象、没有
worker 线程、没有队列、没有文件、也没有 socket。进程内可以随时重新配置；新配置
非法时抛 `ValueError`，**原来可用的配置保持不变**。

## 投递模型与退出

- 未传 `wait=True` 时，调用仅进行非阻塞入队。每个渠道实例有独立的有界队列和
  daemon worker，因此一个渠道的限流或重试不会阻塞另一个渠道；单个渠道实例内
  保持消息顺序。
- `wait=True` 会同步投递、返回各渠道真实结果，并使用可选的单请求 `timeout`。
  此时渠道是**串行**访问的，最坏耗时约为 Σ（重试次数 × 超时 + 退避 + 限流等待）。
  不要在 `next()` 或 tick 热路径里使用它。
- `bt.flush_notifications(timeout=...)` 等待所有已配置队列排空，返回 `True` 或
  `False`。长驻或受控退出的进程应在 `cerebro.run()` 后调用它。
- 正常 Python 解释器退出时会尽力以内联方式排空队列；这不能让通知持久化：
  崩溃、kill 信号、进程丢失或渠道侧失败仍可能丢消息。关键告警应多渠道发送并
  保留本地日志。

## 配置方式

### 直接传入渠道字典

`configure_notifications()` 接收一组字典。每个字典必须有 `channel` 键，其余键是
该渠道的凭据：

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

缺少必填字段时会在配置阶段抛 `ValueError`，错误信息会指出渠道和缺失字段。传入
空序列是合法的，表示“已配置但没有渠道”；此时发送返回 `reason="no_channels"`。

同一渠道可以配多条，用于多个群或多个目标。当某渠道配置了多条时，所有实例都会
带上按配置顺序编号的后缀（`dingtalk#1`、`dingtalk#2`）；只配一条时保留纯渠道 ID
（`wecom_bot`）。统计、限流、队列和去重**按实例隔离**。

### 环境变量配置

`configure_notifications_from_env()` 支持无凭据配置文件的部署方式。渠道列表来自
`BT_NOTIFY_CHANNELS`（逗号分隔），每个字段来自
`BT_NOTIFY_<渠道ID>_<字段名>`（渠道 ID 和字段名均为大写）：

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

字段名到变量名的对应示例：

| 渠道 | 字段 | 环境变量 |
| --- | --- | --- |
| `dingtalk` | `access_token` | `BT_NOTIFY_DINGTALK_ACCESS_TOKEN` |
| `feishu_bot` | `secret` | `BT_NOTIFY_FEISHU_BOT_SECRET` |
| `email` | `to` | `BT_NOTIFY_EMAIL_TO`（逗号分隔） |
| `wecom_app` | `agentid` | `BT_NOTIFY_WECOM_APP_AGENTID` |
| `webhook` | `url` | `BT_NOTIFY_WEBHOOK_URL` |
| `wechat_clawbot` | `bot_token` | `BT_NOTIFY_WECHAT_CLAWBOT_BOT_TOKEN` |
| `qq_bot` | `appsecret` | `BT_NOTIFY_QQ_BOT_APPSECRET` |

环境值会按渠道期望的类型转换：

- 整数字段：`port`、`agentid`、`priority`、`max_length`；
- `to` 按逗号拆分为列表；
- 布尔字段接受 `1`/`true`/`yes`/`on`：`ssl`、`starttls`、`sandbox`、`html`；
- 其余保持字符串。

可用 `prefix=` 使用自己的命名空间（例如每套部署一个前缀）。`<prefix>CHANNELS`
为空或不存在时抛 `ValueError`。

### 核心选项

以下都是 `configure_notifications()` 的关键字参数（`configure_notifications_from_env()`
同样接受）。未知选项或越界值会抛 `ValueError`。

| 选项 | 默认值 | 含义 |
| --- | --- | --- |
| `default_wait` | `False` | `send_message(wait=...)` 的默认值；`False` 表示只入队。 |
| `queue_size` | `1000` | 单个渠道实例的队列长度。 |
| `overflow` | `"drop_newest"` | 队列满时的策略；另一个可选值是 `"drop_oldest"`。 |
| `rate_limit_scale` | `0.75` | 本地按官方速率的一定比例发送，留出余量；取值 `(0, 1]`。 |
| `dedup_cooldown` | `0.0` | 同一 `(实例, dedup_key)` 被抑制的秒数；`0` 表示不去重。 |
| `max_retries` | `2` | 可恢复失败的重试次数。 |
| `retry_backoff` | `0.5` | 指数退避的基准秒数（带抖动）。 |
| `request_timeout` | `10.0` | 渠道驱动使用的单请求超时。 |
| `rate_limit_wait_timeout` | `30.0` | 等待本地限流窗口的最长秒数，超过则记为 `rate_limit`。 |
| `at_all` | `False` | 是否允许 `@all`；仅对支持该能力的渠道且 `level="critical"` 时生效。 |
| `log_events` | `True` | 是否通过日志体系输出通知生命周期记录。 |
| `workers` | `"silent"` | 子进程行为；`"silent"` 禁止外发，`"send"` 允许。 |

## 渠道清单

公开渠道 ID：

| 类型 | ID |
| --- | --- |
| Webhook / Bot | `dingtalk`、`wecom_bot`、`feishu_bot`、`telegram`、`webhook`、`slack`、`discord`、`ntfy`、`gotify`、`bark` |
| 账户型 | `email`、`wecom_app` |
| 会话锚定 | `wechat_clawbot`、`qq_bot` |

| 渠道 | 必填字段 | 可选字段 | 正文形态 | 本地限流 | 长度上限 |
| --- | --- | --- | --- | --- | --- |
| `dingtalk` | `access_token` | `secret`（加签机器人） | markdown | 20 条/分 | 不截断 |
| `wecom_bot` | `key` | — | markdown；`@all` 时切 text | 20 条/分 | 2048 字节 |
| `feishu_bot` | `token` | `secret`（签名） | 纯文本 | 100 次/分且 5 次/秒 | 不截断 |
| `telegram` | `bot_token`、`chat_id` | — | MarkdownV2（自动转义） | 20 条/分且 1 条/秒 | 4096 字符 |
| `email` | `host`、`port`、`to`（列表） | `user`、`password`、`sender`、`ssl`、`starttls`、`html` | 纯文本或 HTML | 由服务商决定 | 不截断 |
| `wecom_app` | `corpid`、`corpsecret`、`agentid`、`touser` | — | markdown；`@all` 时切 text | 30 条/分 | 2048 字节 |
| `webhook` | `url` | `method`、`headers`、`body_json`、`body_template`、`content_type`、`max_length` | 自定义 | 无 | 配置了 `max_length` 才截断 |
| `slack` | `webhook_url` | — | 文本 | 1 条/秒 | 4000 字符 |
| `discord` | `webhook_url` | — | markdown | 每 2.5 秒 1 条 | 2000 字符 |
| `ntfy` | `topic` | `token`、`base_url` | 纯文本 | 自建不限 | 不截断 |
| `gotify` | `base_url`、`token` | `priority` | 纯文本 | 自建不限 | 不截断 |
| `bark` | `device_key` | `base_url` | 纯文本 | 由服务商决定 | 不截断 |
| `wechat_clawbot` | `bot_token`、`to_user_id` | `context_token`、`base_url` | 纯文本 | 会话锚定 | 不截断 |
| `qq_bot` | `appid`、`appsecret` | `user_openid`、`group_openid`、`sandbox` | 纯文本 | 20 条/分 | 不截断 |

表中的限流是**本地保护阈值**，不代表远端一定接受这个量级；实际阈值还会乘以
`rate_limit_scale`。

若工具需要读取必填字段，请使用公开能力查询，不要导入私有实现：

```python
from backtrader.notifications import channel_requires

assert channel_requires("dingtalk") == ("access_token",)
assert channel_requires("email") == ("host", "port", "to")
```

### 聊天机器人

```python
bt.configure_notifications([
    {"channel": "dingtalk", "access_token": "...", "secret": "..."},
    {"channel": "wecom_bot", "key": "..."},
    {"channel": "feishu_bot", "token": "...", "secret": "..."},
    {"channel": "telegram", "bot_token": "123:ABC", "chat_id": "42"},
])
```

- `dingtalk`：只有加签机器人需要 `secret`，两者都来自机器人配置页。
- `wecom_bot`：群机器人 webhook 的 key。自定义机器人接收 markdown，但 `@all`
  只在 text 形态可用，驱动会在 `at_all` 生效时自动切换。
- `feishu_bot`：自定义机器人 webhook token。`text` 消息类型不渲染 markdown，
  因此驱动按纯文本发送（会去掉标记）。
- `telegram`：MarkdownV2 会自动转义，正文里出现 `*`、`_`、`[` 也不会破坏消息；
  `chat_id` 可以是机器人有权发言的私聊、群或频道 ID。

### 邮件与企业微信应用

```python
bt.configure_notifications([
    {
        "channel": "email",
        "host": "smtp.example.com",
        "port": 465,
        "ssl": True,                     # 或用 starttls=True 走 587
        "user": "bot@example.com",
        "password": "...",               # 建议使用应用专用密码
        "sender": "bot@example.com",     # 省略时等于 user
        "to": ["you@example.com"],       # 必须是列表，不能是字符串
        "html": False,
    },
    {
        "channel": "wecom_app",
        "corpid": "...",
        "corpsecret": "...",
        "agentid": 1000002,
        "touser": "@all",                # 或 "user1|user2"
    },
])
```

`port` 必须是整数、`to` 必须是非空列表，两者都在配置阶段校验。`ssl` 与
`starttls` 二选一，不要同时开启。

### 通用 webhook

`webhook` 可对接任意 HTTP 端点，提供三种请求体形态：

```python
# 1) 结构化 JSON（推荐）：换行/引号由 json.dumps 负责转义
{"channel": "webhook", "url": "https://...",
 "body_json": {"text": "{text}", "level": "{level}"}}

# 2) 原始模板：自己负责转义；{{ }} 表示字面大括号
{"channel": "webhook", "url": "https://...",
 "body_template": "level={level} text={text} raw={{literal}}",
 "content_type": "text/plain; charset=utf-8"}

# 3) 都不给：把处理后的文本作为 text/plain 发送
{"channel": "webhook", "url": "https://..."}
```

占位符：`{text}`（含等级前缀与标题的正文）、`{title}`、`{level}`。`method`
默认 `POST`；`headers` 用于追加或覆盖请求头；`max_length` 可为有自身长度限制的
端点开启截断。

### 推送与中继服务

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

`ntfy` 与 `bark` 省略 `base_url` 时分别使用公共的 `https://ntfy.sh` 与
`https://api.day.app`；自建服务需显式填写。`gotify` 必须给出 `base_url` 和应用
token，可选整数 `priority`。

### 会话锚定渠道

微信 ClawBot 和 QQ 不是只填 token 就能推送的渠道：都必须先建立入站关系，才可
主动外发。全新环境在绑定前发送会返回 `not_bound`。

**微信 ClawBot（iLink）**

```python
import backtrader as bt

# 1) 绑定一次：打印二维码内容，扫码后自动持久化锚点。
anchor = bt.bind_wechat_clawbot(qr_callback=print)
print(anchor["to_user_id"])

# 2) 配置渠道（bot_token 可直接取自锚点）。
bt.configure_notifications([{
    "channel": "wechat_clawbot",
    "bot_token": anchor["bot_token"],
    "to_user_id": anchor["to_user_id"],
}])

# 3) 长驻进程内，用新的入站消息刷新推送窗口。
bt.poll_clawbot_once()
```

- 锚点默认位于 `~/.backtrader/notifications/wechat_clawbot.json`（见
  `default_anchor_path()`），可用 `persist_path=` 覆盖。
- 每次主动推送会消耗大约十条的会话窗口。本实现在第 8 条就停止并要求新的入站
  消息，之后由 `poll_clawbot_once()` 刷新锚点。窗口耗尽时返回 `not_bound` 并
  给出 "refresh window exhausted" 提示，**不会静默丢弃**。
- 单个 ClawBot 同时只能连一个 agent 实例。如果它已经接给其他助手，backtrader
  的轮询会与之互斥；建议为交易通知单独创建一个 ClawBot。
- 端点/请求头/字段来自社区对官方 npm 包的反推，**未经官方文档确认**；上线前
  请先用固定消息验证。

**QQ 机器人**

```python
bt.bind_qq_bot(user_openid="...")     # 单聊
bt.bind_qq_bot(group_openid="...")    # 群聊
```

OpenID 按 bot 隔离，通常需要从事件订阅中获得。自动订阅需要 WebSocket 或公网
Webhook，而本包遵守零新增依赖约束、不会自建这类连接，因此采用**显式注册**。
渠道配置里加 `"sandbox": True` 可指向沙箱域名。用户可以在 QQ 客户端关闭
"允许主动发送"，这类失败归类为 `permission` 且不重试。

## 发送消息

```python
bt.send_message(
    "text",                  # 必填，非空
    title="每日汇总",         # 可选标题（作为正文前缀）
    level="warning",         # info | warning | error | critical
    channels=["telegram"],   # 可选子集；默认发往所有实例
    wait=False,              # 覆盖 default_wait
    timeout=3.0,             # 单请求超时，仅 wait=True 生效
    dedup_key="daily-report",
)
```

`@all` 的生效条件是：配置了 `at_all=True`、消息等级为 `critical`、且渠道支持
该能力（`dingtalk`、`wecom_bot`、`wecom_app`）。其他渠道会忽略它。

`channels=[...]` 只接受公开渠道 ID（`dingtalk`；传实例名 `dingtalk#2` 会抛
`ValueError`）。某渠道有多个实例时，纯 ID 解析到**第一个**实例；要发往全部实例
请省略 `channels`（默认行为）。实际使用的实例名会出现在
`ChannelOutcome.channel` 里（如 `dingtalk#1`）。

## 结果、统计与失败分类

`SendResult` 字段：

| 字段 | 含义 |
| --- | --- |
| `accepted` | 消息已被接受（异步模式下指已入队）。 |
| `mode` | `"async"` 或 `"sync"`。 |
| `outcomes` | 每个尝试过的渠道实例一条 `ChannelOutcome`。 |
| `dropped` | 完全没能入队（例如队列溢出）。 |
| `reason` | 总体结果：`ok`、`queue_full`、`failed`（同步）、`not_configured`、`no_channels` 或 `worker_silent`。 |

`ChannelOutcome` 字段：`channel`、`ok`、`error_category`、`error`（已脱敏）、
`attempts`、`elapsed_ms`。

`error_category` 取自 `bt.ERROR_CATEGORIES`：

| 分类 | 含义 |
| --- | --- |
| `network`、`timeout`、`tls` | 传输层失败；会重试。 |
| `server` | 远端 5xx；会重试。 |
| `rate_limit` | 本地限流等待超时，或远端要求降速。 |
| `auth` | 凭据缺失/过期或签名错误；不重试。 |
| `permission` | 账号或机器人无权在该目标发言；不重试。 |
| `bad_request` | 渠道拒绝了请求形态；不重试。 |
| `not_bound` | 会话锚点缺失或推送窗口耗尽。 |
| `not_configured` | 从未调用 `configure_notifications()`。 |
| `deduped`、`dropped`、`worker_silent`、`unknown` | 本地结果，见下文。 |

`bt.notification_stats()` 返回每个实例的只读统计，包括 `sent`、`failed`、
`retried`、`dropped`、`deduped`、`rate_waited_ms` 和 `truncated`。异步模式下
`ok=True` 仅表示已被该渠道队列接收，不是远端送达回执。

## 限流、去重与截断

使用 `dedup_key` 可以抑制 `dedup_cooldown` 窗口内的重复告警：

```python
self.send_message("feed stalled", level="error", dedup_key="feed-stalled")
```

库会为每个渠道实例做本地限流，默认 `rate_limit_scale=0.75`：突发消息会被摊开
到时间窗口内，而不是直接被拒。队列溢出只影响对应渠道（默认 `drop_newest`，
也可选 `drop_oldest`），并计入 `dropped`。

长度上限只在**已确认**的渠道上执行：`wecom_bot` 与 `wecom_app`（2048 字节）、
`telegram`（4096 字符）、`slack`（4000）、`discord`（2000），以及显式配置了
`max_length` 的 `webhook`。按字节限制的渠道在 UTF-8 边界切分，并在正文末尾另起
一行追加固定标记 `…（已截断 N 字符）`；标记是在切分后追加的，因此最终正文可能比
上限多出标记本身的长度。其余渠道不做截断——按猜测的字节数切会把消息切错位置。

## 验证渠道是否可用

凭据通常放在环境变量里（绝不入库），因此仓库自带的冒烟脚本是最快的端到端检查。
它会发起**真实网络请求**，属于手动工具，永远不在 CI 中运行。

```bash
# 还缺什么？按渠道列出缺失字段后退出 0。
python scripts/notify_smoke.py --list-unverified

# 用已有凭据的渠道各发一条真实消息。
python scripts/notify_smoke.py

# 只发指定渠道，并自定义正文与等级。
python scripts/notify_smoke.py --channels dingtalk,telegram \
    --message "backtrader smoke" --level warning
```

脚本读取 `BT_NOTIFY_<渠道>_<字段>`（可用 `--prefix` 改前缀），打印已脱敏的
`SendResult`，退出码含义：

- `0`：所有尝试过的渠道都 `ok=True`；
- `1`：至少一个渠道失败，或没有任何被请求的渠道具备完整凭据；
- `2`：渠道 ID 未知或配置错误。

输出示例：

```text
mode=sync accepted=True reason=None
  dingtalk         ok=True  category=-              attempts=1 elapsed_ms=182 error=-
  telegram         ok=False category=auth           attempts=1 elapsed_ms=340 error=...
not attempted (no credentials): wecom_bot, feishu_bot, ...
```

对使用 `wait=True` 的渠道，`ok=True` 表示远端接受了请求；它仍然不能证明有人
真的读了这条消息。

## 排查"消息没到"

| 现象 | 先看什么 |
| --- | --- |
| 完全没有输出 | 是否调用了 `configure_notifications`？未配置时只在 stderr 提示一次 |
| `reason="not_configured"` | 同上；或渠道列表为空（`reason="no_channels"`） |
| `reason="worker_silent"` | 在参数优化子进程里；确有必要时设置 `workers="send"` |
| `error_category="dropped"` | 队列满：发送频率远超渠道限额，或 `queue_size` 太小 |
| `error_category="rate_limit"` | 本地限流等待超过 `rate_limit_wait_timeout`；降低频率或放宽预算 |
| `error_category="auth"` | 凭据/签名问题：钉钉加签、企微 key、飞书签名、token 过期 |
| `error_category="permission"` | 机器人无权限：QQ 主动消息被关闭、企微应用可见范围 |
| `error_category="not_bound"` | 会话锚定未完成或刷新窗口耗尽（微信/QQ） |
| `error_category="server"` | 渠道端 5xx，已按 `max_retries` 重试 |
| 消息显示不完整 | 渠道长度上限截断（正文会带「已截断 N 字符」标记） |
| 显示成纯文本/markdown 失效 | 该渠道不渲染 markdown（如 `feishu_bot`、`ntfy`），正文已自动去标记 |
| 锚点文件读不出/内容不全 | 进程在**原地更新**中被强杀；重新绑定或再次调用 `update_anchor()` |

## 多进程与长驻进程

`cerebro.run(maxcpus>1)` 的子进程默认静默，防止参数优化把告警渠道淹没：发送
返回 `reason="worker_silent"`，也不会入队。若明确指定 `workers="send"`，每个
子进程必须自行配置渠道，且本地限流器不会跨进程共享。通常更安全的方案是只在父
进程发送汇总通知。

`cerebro.run()` 返回**不保证**消息已送达；长驻进程请在之后调用
`bt.flush_notifications()`。`bt.reset_notifications()` 会停止 worker、丢弃剩余
队列并清空统计，适合在重新配置时使用。

## 安全注意事项

- 凭据不要进版本库：用环境变量（`BT_NOTIFY_*`）或 gitignore 的配置文件；会话
  锚点文件同样属于凭据。
- POSIX 下锚点文件权限为 `0600`、目录 `0700`。Windows 上 `chmod`/mode 位无
  意义，实现改为**只授予当前账户**的受保护 DACL（`icacls` 显示 `(F)`，仅一条
  显式 ACE、无继承、无外部授权）；锚点只能落在**盘符本地卷**且该卷支持持久
  ACL，UNC 网络路径、可移动盘、未知卷一律失败关闭。
- 锚点更新是**同句柄原地写入**（不是原子替换）：进程若在写入中途被强杀，可能
  留下不完整的 JSON，重新绑定或调用 `update_anchor()` 写入新锚点即可恢复。
- 所有日志、`SendResult.error`、`repr(Notifier)` 都经过脱敏：查询串中键名含
  `token`/`key`/`secret`/`sign`/`password` 的值、`Bearer`/`Basic`/`QQBot`
  凭据、URL 内嵌密码，以及 `key: value` 形式的凭据对，一律替换为 `***`。
- 通知内容会离开本机：不要推送账号、密钥、身份证等敏感信息。

## 公开 API 一览

| 符号 | 模块 | 用途 |
| --- | --- | --- |
| `configure_notifications(channels, **options)` | `backtrader` | 配置渠道与选项，返回 notifier。 |
| `configure_notifications_from_env(prefix="BT_NOTIFY_", **options)` | `backtrader` | 从环境变量配置。 |
| `send_message(text, ...)` | `backtrader` | 发送一条消息，返回 `SendResult`。 |
| `Strategy.send_message(text, ...)` | `backtrader` | 补充策略上下文的便捷封装。 |
| `flush_notifications(timeout=5.0)` | `backtrader` | 等待队列排空。 |
| `notification_stats()` | `backtrader` | 每个实例的计数器。 |
| `reset_notifications()` | `backtrader` | 停止 worker 并清空状态。 |
| `bind_wechat_clawbot(...)` / `poll_clawbot_once(...)` | `backtrader` | 绑定并刷新微信 ClawBot 锚点。 |
| `bind_qq_bot(user_openid=..., group_openid=...)` | `backtrader` | 登记 QQ 锚点。 |
| `update_anchor(channel_id, anchor)` | `backtrader` | 把新锚点应用到运行中的实例。 |
| `default_anchor_path(channel_id)` / `load_anchor(path)` | `backtrader` | 锚点文件位置与读取。 |
| `channel_requires(channel_id)` | `backtrader.notifications` | 查询渠道必填字段。 |
| `PUBLIC_CHANNELS` / `ERROR_CATEGORIES` | `backtrader.notifications` / `backtrader` | 渠道 ID 与失败分类。 |
| `persist_anchor(path, data)` / `get_notifier()` | `backtrader.notifications` | 底层锚点写入与单例访问。 |

字段矩阵的官方来源证据与扩展渠道步骤见仓库的
[Notifications Guidelines](https://github.com/cloudQuant/backtrader/blob/dev/docs/NOTIFICATIONS_GUIDELINES.md)。
