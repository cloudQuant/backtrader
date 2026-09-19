# 通知外发使用规范 (Notifications Guidelines)

迭代 32 新增。本规范面向"要在策略里把消息发到手机/团队群"的使用者，以及排查"消息为什么没到"的运维者。

日志与通知的分工（不要混用）：

| | 日志（迭代 29） | 通知（迭代 32） |
| --- | --- | --- |
| 目的 | 本地过程记录与排错 | 对人可见的事件送达 |
| 落地 | `logs/<脚本>/<日期>/{error,warning,info}.log` | 钉钉/企微/飞书/Telegram/邮件/微信/QQ 等终端 |
| 可靠性 | 尽力写入本地，可回溯 | **尽力而为，不保证送达**；进程崩溃即丢 |
| 入口 | `bt.configure_logging()` + `get_logger()` | `bt.configure_notifications()` + `self.send_message()` |

**关键定位：通知是"尽力而为"的告警通道，不是送达保证。** 需要不漏的告警请同时配多个渠道（例如钉钉 + 邮件），并在关键场景保留本地日志。

## 快速开始

```python
import backtrader as bt

bt.configure_notifications([
    {"channel": "dingtalk", "access_token": "...", "secret": "..."},
    {"channel": "telegram", "bot_token": "123:ABC", "chat_id": "42"},
])

class MyStrategy(bt.Strategy):
    def next(self):
        if self.position.size == 0 and self.signal[0] > 0:
            self.send_message("entry signal", level="warning")

bt.flush_notifications()          # 长驻进程：run 之后显式等一次
```

设计要点：

- **opt-in 且默认静默**：不调用 `configure_notifications` 时无渠道、无线程、无队列、无网络。
- **默认异步**：`send_message` 只入队，立即返回。每个渠道实例一个 worker 线程，同渠道内串行保序，**跨渠道互不阻塞**（被限流的钉钉不会拖住紧急的 Telegram）。
- **失败不外抛**：所有结果以 `SendResult.outcomes` 返回，`error_category` 取值见 `bt.ERROR_CATEGORIES`。
- **零新增第三方依赖**：HTTP 走标准库（复用 `py3.urlopen` 的 30s 默认超时），邮件走 `smtplib`。

## 渠道配置清单

字段名即配置字典的键；`必填` 缺失会在 `configure_notifications` 阶段直接 `ValueError`。

| 渠道 id | 必填字段 | 可选字段 | 消息形态 | 官方限流 | 证据等级 |
| --- | --- | --- | --- | --- | --- |
| `dingtalk` | `access_token` | `secret`（加签） | markdown | 20 条/分钟 | A |
| `wecom_bot` | `key` | — | markdown；`@所有人` 时自动切 text | 20 条/分钟 | A |
| `feishu_bot` | `token` | `secret`（签名） | **纯文本**（自定义机器人 text 不渲染 markdown） | 100 次/分且 5 次/秒 | A |
| `telegram` | `bot_token`、`chat_id` | — | MarkdownV2（自动转义） | 本地按每会话 20/分 + 1/秒 | A/C |
| `email` | `host`、`port`、`to`（列表） | `user`、`password`、`sender`、`ssl`、`starttls`、`html` | 纯文本或 HTML | 由服务商决定 | A |
| `wecom_app` | `corpid`、`corpsecret`、`agentid`、`touser` | — | markdown | 每成员 30 次/分 | A |
| `webhook` | `url` | `method`、`headers`、`body_json`、`body_template`、`content_type` | 自定义 | 无 | A |
| `slack` | `webhook_url` | — | 文本（`text` 字段） | 约 1 条/秒 | A/C |
| `discord` | `webhook_url` | — | markdown（≤2000 字符） | 5 次/2 秒 | A |
| `ntfy` | `topic` | `token`、`base_url` | 纯文本（JSON publish） | 自建无限 | A/C |
| `gotify` | `base_url`、`token` | `priority` | 纯文本 | 自建 | A |
| `bark` | `device_key` | `base_url` | 纯文本 | 官方/自建 | A/C |
| `wechat_clawbot` | `bot_token`、`to_user_id` | `context_token`、`base_url` | 纯文本 | **会话锚定，见下节** | B/C |
| `qq_bot` | `appid`、`appsecret` | `user_openid`、`group_openid`、`sandbox` | 纯文本 | 20/qpm（单关系，保守） | A |

证据等级：**A** = 官方文档明确；**B/C** = 官方 SDK 存在但字段未公开文档 / 社区实测。完整来源与未复核项见 `docs/_internal/opts/requirements/迭代32-发送信息功能/evidence/channel-facts.json`。

**未确认长度上限的渠道不做截断**（`dingtalk`/`feishu_bot`/`ntfy`/`gotify`/`bark`/`webhook`）：宁可不截断，也不按猜测的字节数切错。已确认的会按 UTF-8 安全截断并追加「已截断 N 字符」。

### 同渠道多实例

同一渠道可以配多条，用于多个群/多个目标，实例按出现顺序编号（`dingtalk#1`、`dingtalk#2`），统计、限流、队列、去重**按实例隔离**：

```python
bt.configure_notifications([
    {"channel": "dingtalk", "access_token": "...", "secret": "..."},   # dingtalk#1
    {"channel": "wecom_bot", "key": "..."},                            # wecom_bot
    {"channel": "wecom_bot", "key": "..."},                            # wecom_bot#2
])
```

### webhook 的三种请求体

```python
# 1) 结构化 JSON（推荐）：换行/引号由 json.dumps 负责转义，消息内容不会破坏 JSON
{"channel": "webhook", "url": "https://...", "body_json": {"text": "{text}", "level": "{level}"}}

# 2) 原始模板：自己负责转义；{{ }} 表示字面大括号
{"channel": "webhook", "url": "https://...",
 "body_template": "level={level} text={text} raw={{literal}}",
 "content_type": "text/plain; charset=utf-8"}

# 3) 都不给：把处理后的文本作为 text/plain 发送
{"channel": "webhook", "url": "https://..."}
```

占位符：`{text}`（含等级前缀与标题的正文）、`{title}`、`{level}`。

## 同步与异步

```python
self.send_message("...")              # 默认异步：入队即返回（next() 里就该这样）
self.send_message("...", wait=True, timeout=3.0)  # 同步：逐调用覆盖请求超时
bt.flush_notifications(timeout=5.0)   # 等待队列排空，返回是否排空
```

- **`wait=True` 会阻塞网络 I/O，且多渠道串行**：总耗时 ≈ Σ（重试 × 超时 + 退避 + 限流等待）。`timeout=` 是该次同步 HTTP 请求的覆盖值；省略时使用 `configure_notifications(request_timeout=...)` 的配置值。只在 `stop()` 等低频路径使用，**不要在 `next()`/tick 级路径使用**。
- 异步模式下 `SendResult.outcomes` 是**入队结果**（`ok=True` 表示已入队，不代表已送达）；确认真实送达要 `wait=True` 或查 `bt.notification_stats()`。
- 队列满时默认丢最新（`overflow="drop_newest"`），`drop_oldest` 可选；丢弃计入统计并经日志告警，只在**该渠道**生效。

## 限流、重试与去重

- **本地限流**：按渠道官方阈值 × `rate_limit_scale`（默认 0.75）留余量，命中后等待窗口恢复再投递（不丢消息）。等待超过 `rate_limit_wait_timeout`（默认 30s）记 `rate_limit` 失败并继续处理后续消息。
- **重试**：只重试可恢复错误（`network`/`timeout`/`tls`/`server`/`rate_limit`，默认最多 2 次，指数退避 + 抖动）。`auth`/`permission`/`bad_request`/`not_bound` **不重试**。Telegram 429 按响应里的 `retry_after` 精确等待。
- **去重**：`dedup_key` + `dedup_cooldown`，同一 `(渠道实例, key)` 在窗口内只实际投递一次；被抑制的调用返回 `error_category="deduped"`（不计失败）。适用于"同一异常每 bar 触发一次"的场景。

```python
bt.configure_notifications([...], dedup_cooldown=300.0)
self.send_message("feed stalled", level="error", dedup_key="feed-stalled")
```

## 会话锚定渠道（微信 ClawBot / QQ 机器人）

这两条通道**不能只靠 token 推送**：必须先收到过用户的一条消息，才能回推。

**微信 ClawBot（iLink）**

```bash
# 1) 先配置（bot_token 可留到绑定后由 update_anchor 补上）
#    或直接跑绑定流程：二维码 → 扫码 → 自动持久化锚点
python -c "import backtrader as bt; print(bt.bind_wechat_clawbot(qr_callback=print))"
# 2) 之后周期性刷新（刷新窗口需要新的入站消息）
python -c "import backtrader as bt; print(bt.poll_clawbot_once())"
```

- 锚点文件默认 `~/.backtrader/notifications/wechat_clawbot.json`，权限 `0600`，目录 `0700` —— **含可直接发消息的凭据，务必加入 `.gitignore`**。
- 主动推送有窗口限制：约每 10 条需要一条新的入站消息刷新（本实现提前到 8 条停止并要求刷新）。窗口耗尽时返回 `not_bound` 与"refresh window exhausted"提示，**不会静默丢弃**。
- **单个 ClawBot 同时只能连一个 agent 实例**：如果它已经接给其他助手，backtrader 的轮询会与之互斥。建议为交易通知单独创建一个 ClawBot。
- 协议细节（端点/请求头/必填字段）来自社区对官方 npm 包的反推，**未经官方文档确认**；实测请先用固定消息验证。

**QQ 机器人**

```python
bt.bind_qq_bot(user_openid="...")     # 或 group_openid="..."
```

- `openid` 按 bot 隔离，需要从事件订阅中获得。自动订阅需要 WebSocket 或公网 Webhook，而标准库没有 WebSocket 客户端，因此本迭代采用**显式注册**（不自建长连接、不引入新依赖）。
- 用户在 QQ 客户端可关闭"允许主动发送"，关闭后必然失败（分类为 `permission`，不重试）。
- 首期只支持消息列表单聊与群聊，**不含"频道"**。正式环境需提审上线、配置 IP 白名单；沙箱环境不受这两项限制。

## 多进程与长驻进程

- `cerebro.run(maxcpus>1)` 参数优化：子进程默认**不外发**（`error_category="worker_silent"`），避免上千个参数组合变成消息轰炸。确实需要在子进程发送时显式 `workers="send"`，且子进程要自己 `configure_notifications`。注意：开启后**每个子进程各自持有独立的本地限流器**（跨进程不聚合），几十个子进程同时外发时合计速率可能超过渠道官方阈值——请自行把各进程的 `rate_limit_scale` 调小分摊额度，或仅让主进程外发。
- `cerebro.run()` 返回**不保证**消息已送达。长驻进程请在 run 之后调用 `bt.flush_notifications()`。
- **脚本退出由 `atexit` 兜底**（复核轮补齐）：该钩子在调用线程内**内联发送**剩余消息——CPython 在跑 `atexit` 之前已冻结 daemon worker，只「等 worker 排空」会耗尽超时后照样丢消息。此路径是尽力而为：**宁可重复也不丢**（极小窗口内一条消息可能重发一次）。
- 子进程按设计默认 `worker_silent`：optimize 子进程里的消息不入队，因此也不存在退出兜底；要在子进程发送必须 `workers="send"` 且由子进程自行 `configure_notifications`。
- `bt.reset_notifications()` 会停止 worker、**丢弃**剩余队列（计入 `dropped` 统计）、清空统计与绑定缓存。测试与长驻进程重启配置时使用。

## 排查"消息没到"

| 现象 | 先看什么 |
| --- | --- |
| 完全没有输出 | 是否调用了 `configure_notifications`？未配置时只在 stderr 提示一次 |
| `reason="not_configured"` | 同上；或渠道列表为空（`reason="no_channels"`） |
| `reason="worker_silent"` | 在 optimize 子进程里；确认是否需要 `workers="send"` |
| `error_category="dropped"` | 队列满：发送频率远超渠道限额，或 `queue_size` 太小 |
| `error_category="rate_limit"` | 本地限流等待超时（默认 30s）；检查渠道额度或降频 |
| `error_category="auth"` | 凭据/签名问题：钉钉加签、企微 key、飞书签名、token 过期 |
| `error_category="permission"` | 机器人无权限：QQ 主动消息被关闭、企微应用可见范围 |
| `error_category="not_bound"` | 会话锚定未完成或刷新窗口耗尽（微信/QQ） |
| `error_category="server"` | 渠道端 5xx，已按策略重试 |
| 消息显示不完整 | 渠道长度上限截断（正文会带「已截断 N 字符」标记） |
| 显示成纯文本/markdown 失效 | 该渠道不渲染 markdown（如 `feishu_bot`、`ntfy`），正文已自动去标记 |

统计与真实发送验证：

```python
bt.notification_stats()
# {'dingtalk': {'sent': 3, 'failed': 1, 'retried': 2, 'dropped': 0,
#               'deduped': 0, 'rate_waited_ms': 0.0, 'truncated': 0}}

# 本地手动冒烟（真实联网，仅本地执行，不入 CI）
python scripts/notify_smoke.py --channels dingtalk,telegram
python scripts/notify_smoke.py --list-unverified
```

冒烟脚本从 `BT_NOTIFY_<渠道>_<字段>` 读取凭据（如 `BT_NOTIFY_TELEGRAM_BOT_TOKEN`），并会把仓库根加入 `sys.path`，确保测的是工作树而不是 site-packages 里的旧副本。

## 安全注意事项

- **凭据不要进版本库**：用环境变量（`BT_NOTIFY_*`）或 gitignore 的配置文件；锚点文件权限必须是 `0600`。
- 所有日志、`SendResult.error`、`repr(Notifier)` 都经过脱敏（`token`/`key`/`secret`/`sign`/`Bearer`/`QQBot` → `***`，URL 只保留 `scheme://host/path`）。新增渠道请复用 `backtrader/notifications/security.py`。
- 通知内容会离开本机：不要推送账号、密钥、身份证等敏感信息。

## 查询渠道的必填字段

```python
from backtrader.notifications import channel_requires

channel_requires("dingtalk")   # ('access_token',)
channel_requires("email")      # ('host', 'port', 'to')
```

自检脚本与配置生成工具应当用这个公开入口，不要 import 私有符号（`scripts/notify_smoke.py` 即如此实现）。

## 扩展新渠道

1. 在 `backtrader/notifications/channels.py` 的 `CHANNEL_SPECS` 增加一条声明式条目（`requires`/`rate_limit`/`max_length`/`markdown`/`supports_at_all` + `build`/`is_ok`）。
2. 形态特殊的（需要 token 生命周期、SMTP、会话锚点）放到 `adapters.py` 或 `session.py`，并在 `config.py` 的渠道注册入口登记（`ADAPTER_SPECS`/`SESSION_SPECS`，随 `_spec_for` 一起解析）。
3. 加两条测试：请求构造（断言 URL/header/body）与成功/失败分类；长度与 markdown 能力变化时补一条适配测试。
