# CTP I11 受监督 MD-only 一次性诊断（2026-09-25）

状态：`INCOMPLETE / NATIVE_JOIN_PENDING / I11_MARKER_CONSUMED / NO_WRITE / LIVE_NO_GO`。本页只记录脱敏的受监督结果，不含地址、账户值、认证值或 marker 内容。I11 是未注册候选，不改变默认运行路由。

## 前置核验

固定隔离 venv 中的 I10 base/CTP installed-artifact provenance Job 返回 verified，父进程确认 Job empty。父进程对同一密封配置的五组已配置 MD/TD pair 做无凭据 TCP 探测：零基索引 3 的 MD 与 TD 均为 3/3 可达，其余四组均为 0/3。该探测证明当时的 TCP 可达性，不证明 SDK 登录身份、行情数据或账户可用。

## Child 观察

I11 专用 marker 在 worker 启动前已预留；本次之后 marker 仍存在，I11 不可重试。child fresh 校验的 effective config digest 与父进程匹配，并使用父进程选中的 `pair_3`。child 确认调用了 credential resolver 并导入 SDK。

MD 回执记录：

- `login_identity_state=identity_unverified`
- `subscription_acknowledged=true`
- `matching_tick_observed=null`
- `same_trading_day_observed=null`
- `client_stop_returned=true`
- `close_state=native_join_pending`
- `native_join_pending=true`
- `probe_session_closed=null`

订阅 ACK 只证明订阅确认回调已被观察；它不证明登录身份、匹配 tick、同交易日行情、原生关闭或账户就绪。Tick 与交易日字段为 null，表示没有正面确认，不应改写为已观察或已证明不存在。

## Process containment 与边界

父进程报告 `status=incomplete`、`reason=native_join_pending`。Windows Job 的 process assignment、process exit 和 Job empty 均已确认；containment 为 verified。由于 child 报告 native Join pending，父进程请求终止 Job，终止调用成功，进程退出码为 `60965`（Job kill code）。整个受监督尝试约 28.3 秒。

Job empty 证明进程树已被收拢，不证明 SDK native Release/Join 或会话有序关闭。`client_stop_returned=true` 也不能覆盖 `native_join_pending`；本次关闭状态没有通过。

`account_ready=false`、`trading_ready=false`、`order_submission_authorized=false`，`trading_writes=zero`、`settlement_writes=zero`。I11 只构造 MD-only 诊断路径，没有调用下单、撤单或结算接口。本次不是完整 preflight、账号登录验收或交易验收。

该尝试使用独立 I11 marker，不复用或重置 I10 marker。marker 已消耗，不做重试。候选仍未注册，默认 CTP sandbox 只读边界不变，写入及 live 路由继续关闭，保持 `NO_WRITE / LIVE_NO_GO`。该 one-shot 只约束受支持 operator entry，不是针对同一用户权限下任意 Python/SDK 调用的安全沙箱。
