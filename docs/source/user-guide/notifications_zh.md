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

## 投递模型与退出

- 未传 `wait=True` 时，调用仅进行非阻塞入队。每个渠道实例有独立的有界队列和
  daemon worker，因此一个渠道的限流或重试不会阻塞另一个渠道。
- `wait=True` 会同步投递、返回各渠道真实结果，并使用可选的单请求 `timeout`。
  不要在 `next()` 或 tick 热路径里使用它。
- `bt.flush_notifications(timeout=...)` 等待所有已配置队列排空，返回 `True` 或
  `False`。长驻或受控退出的进程应在 `cerebro.run()` 后调用它。
- 正常 Python 解释器退出时会尽力以内联方式排空队列；这不能让通知持久化：
  崩溃、kill 信号、进程丢失或渠道侧失败仍可能丢消息。关键告警应多渠道发送并
  保留本地日志。

`bt.notification_stats()` 返回每个实例的只读统计，包括 `sent`、`failed`、
`retried`、`dropped`、`deduped`、`rate_waited_ms` 和 `truncated`。异步模式下
`ok=True` 仅表示已被该渠道队列接收，不是远端送达回执。

## 支持渠道与配置

公开渠道 ID：

| 类型 | ID |
| --- | --- |
| Webhook / Bot | `dingtalk`、`wecom_bot`、`feishu_bot`、`telegram`、`webhook`、`slack`、`discord`、`ntfy`、`gotify`、`bark` |
| 账户型 | `email`、`wecom_app` |
| 会话锚定 | `wechat_clawbot`、`qq_bot` |

若工具需要读取必填字段，请使用公开能力查询，不要导入私有实现：

```python
from backtrader.notifications import channel_requires

assert channel_requires("dingtalk") == ("access_token",)
assert channel_requires("email") == ("host", "port", "to")
```

完整字段矩阵、内容长度限制和官方证据见仓库的
[Notifications Guidelines](https://github.com/cloudQuant/backtrader/blob/dev/docs/NOTIFICATIONS_GUIDELINES.md)。
token、secret、授权码与会话锚点文件都不能提交到版本库。

### 环境变量配置

`configure_notifications_from_env()` 支持无凭据配置文件的部署方式。先使用
`BT_NOTIFY_CHANNELS` 列出渠道，再设置每个渠道的大写字段：

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

缺少必填字段时会在配置阶段抛出 `ValueError`，既有的有效配置不会被破坏。

## 限流、去重与失败

使用 `dedup_key` 可以抑制 `dedup_cooldown` 窗口内的重复告警：

```python
self.send_message(
    "feed stalled",
    level="error",
    dedup_key="feed-stalled",
)
```

库会为每个渠道实例做本地限流，默认 `rate_limit_scale=0.75`。队列溢出只影响
对应渠道（默认 `drop_newest`，也可选 `drop_oldest`）。投递失败通过
`ChannelOutcome.error_category` 返回；常见分类包括 `network`、`timeout`、
`server`、`auth`、`permission`、`rate_limit`、`not_bound`、`not_configured`、
`deduped` 与 `dropped`。

## 微信 ClawBot 与 QQ 机器人

微信 ClawBot 和 QQ 不是只填 token 就能推送的渠道：都必须先建立入站关系，才可
主动外发。

- **微信 ClawBot：** 用 `bt.bind_wechat_clawbot()` 完成二维码/入站绑定；长驻进程
  周期调用 `bt.poll_clawbot_once()` 刷新会话锚点。锚点属于敏感凭据，默认位于
  `~/.backtrader/notifications/`，并使用受限文件权限。
- **QQ 机器人：** 通过 `bt.bind_qq_bot(user_openid=...)` 或
  `group_openid=...` 显式登记单聊或群聊锚点。自动获得事件需要 WebSocket 或公网
  Webhook；本包遵守零新增依赖约束，不会自行建立这种连接。

框架对两种适配器均有离线请求/响应覆盖。微信与 QQ 的真实送达仍取决于你的平台
账号、权限和当前平台行为；上线前请用自己的凭据运行
`scripts/notify_smoke.py` 手动验证。

## 多进程

`cerebro.run(maxcpus>1)` 的子进程默认静默，防止参数优化把告警渠道淹没。若明确
指定 `workers="send"`，每个子进程必须自行配置渠道，且本地限流器不会跨进程共享。
通常更安全的方案是只在父进程发送汇总通知。
