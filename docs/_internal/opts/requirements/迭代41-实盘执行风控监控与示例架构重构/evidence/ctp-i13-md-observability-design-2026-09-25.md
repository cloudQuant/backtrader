# CTP I13 MD 可观测性设计注记（2026-09-25）

状态：I13 SDK 值脱敏 hook、独立 wheel 审计和纯 Python 投影已完成；受监督 composition、独立 one-use marker 和真实 I13 provider 观察尚未验收。本页不授权写操作，默认状态继续为 `NO_WRITE / LIVE_NO_GO`。

## I13 已完成的离线候选（更新）

隔离 SDK 源分支冻结在 `c68bebe8631419801e7a24e13b98c42867df0beb`，新增不可变、值脱敏的 MD 一次性诊断 receipt，分别记录登录回调分类、订阅请求/响应/ACK、首个 tick 到达或待处理、终态原因。它不改变默认策略运行路径。两份独立干净 clone 在同一主机和工具链下构建出字节相同的 Windows CPython 3.11 wheel（5,415,541 字节，SHA-256 `c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d`）；独立审计复核了 86 个 wheel payload hash、隔离安装的 89 个带 hash RECORD 条目、venv 内的 import origin 和 `pip check`，未发现 P1/P2。已记录的 installed-wheel fake-only MD/login/shutdown 测试为 234 passed；审计复核了日志和测试来源，未重新执行该组测试。完整构建与审计证据在 `D:\temp\i13-final-wheel-repro-20260925\I13-final-wheel-repro-receipt.md`；两次构建同机同工具链，不证明跨机可复现或 provider 行为。

主仓 `ctp_i13_md_observability.py` 将 SDK receipt 与下游 adapter 接受/拒绝、TradingDay 和 native Join 状态分开投影；矛盾证据拒绝，未知保持未知。独立复审关闭两处 P2 后，13 项 fake-only 投影测试和 Ruff 通过。上述结果不等于 I13 Job/marker/真实 MD 登录、订阅 tick 或有序 native shutdown 已完成；本页下方的设计门槛仍适用于后续真实尝试。

## I11 观察与已知边界

I11 本次选中的 pair index 为 3，父/子配置摘要匹配，隔离 fixed-venv artifact pin 已验证。Child receipt 为 `login_identity_state=identity_unverified`、`subscription_acknowledged=true`、`matching_tick_observed=null`、`same_trading_day_observed=null`、`client_stop_returned=true`、`native_join_pending=true`、`probe_session_closed=null`。Windows Job 被终止并收拢，Job empty；交易与结算写入为零。

冻结 I10 SDK commit `a6253a58b1ebca11f58c8836fbed757d0daf7582` 的身份未验证路径只证明收到一个终态登录响应、request ID 关系为零、响应错误状态为零、BrokerID/UserID 原生定长字段为空且 TradingDay 形状可用；它不会设置 logged-in 或 active identity。源位置：冻结 checkout `src/bt_api_ctp/ctp/client.py` 约 3372–3704 行；SWIG 定长字段读法在 `src/bt_api_ctp/ctp/ctp.i` 约 128–146 行。空 identity 的来源仍未知，不应推断为凭据错误或认证成功。

I11 的 `subscription_acknowledged=true` 有单独正面证据：订阅请求返回 0，ACK request ID 为 0、last flag 为真、InstrumentID 精确匹配、响应错误状态为零，并且 generation/API/SPI 与当前会话匹配。冻结 SDK `client.py` 约 3754–3821 行；I10 adapter 回调验证约 525–564 行。它不证明登录身份或存在行情 tick。

`matching_tick_observed=null` 和 `same_trading_day_observed=null` 的准确含义是“未正面确认”，不是“已证明没有 tick”。I10 adapter 只在 tick 通过 generation、ACK、终态、TradingDay、InstrumentID、ExchangeID、正有限 LastPrice 与非负整数 Volume 的所有检查后置 true；见 `backtrader_runtime/ctp_i10_oneshot_md_readonly.py` 约 342–356、566–594 行，以及 `ctp_sdk_market_readonly.py` 约 784–797 行。现有 receipt 无法区分 SDK 丢弃/拒绝 tick、adapter 拒绝、回调未到达或 deadline 到期。

关闭方面，I10 helper 严格校验 stop receipt 与 generation、active callback 数，并在观察到 Join observer 线程仍存活时投影 `native_join_pending`；见 `ctp_i3_oneshot_md_readonly.py` 约 364–444 行、`ctp_sdk_market_readonly.py` 约 675–679 行及冻结 SDK `client.py` 约 156–188 行。I11 supervisor 看到 Join pending 后调用 `TerminateJobObject`（`ctp_readonly_job_supervisor.py` 约 1078–1085 行）。因此 Job empty 证明进程树退出，不能证明 native Join/Release 或会话 graceful close；若 child 最终 receipt 已报告 pending，该状态先于父进程的 Job kill。

I10 adapter 在 `CtpSdkMarketReadOnlyError.primary_reason` 中保留了部分底层 probe 分类（I10 adapter 约 671 行；错误字段在 `ctp_sdk_market_readonly.py` 约 82–106 行），但 I11 的通用 except 投影只保留 progress 四字段并在 Join pending 时将 reason 改为 `native_join_pending`（`ctp_i11_oneshot_md_diagnostic.py` 约 1299–1334 行）。因此本次 primary probe reason 丢失。此前 I10 fake tests 使用同步 fake callback（测试约 60–251 行），没有覆盖真实 callback 时序；这类 fake 成功不能补足 I11 未观察到的 SDK/adapter tick 路径。

**根因仍未知。** 现有证据只确认 ACK、身份未验证、未正面确认 matching tick/day、Join pending 和 Job containment。不能据此断言 front、账号、行情订阅、交易日、SDK callback 或 native shutdown 中哪一项是根因；也不能将 Job kill 说成 Join pending 的起因。

## I13 设计门槛

主仓新增的 `backtrader_runtime/ctp_i13_md_observability.py` 是独立离线投影器，不 import I10/I11、SDK、配置、凭据、marker、网络或 latch，当前没有接入任何运行入口。它只接受有界事件枚举和单调毫秒值，公开投影仅含固定 enum、非敏感计数及三态确认；未知/注入字段不回显。`primary_probe_reason` 与 `native_join_state` 分开：I11 的 `native_join_pending` 不会伪装成行情探测根因；只有观测 trace 足以说明事件类别，不足以决定真实根因。

下一次任何真实 MD-only 尝试前，I13 专用受监督 composition 与独立 one-use marker 候选必须完成定向测试和独立审查；主仓现有未注册初稿不能代替这项验收，也不能复用或重置 I10/I11 marker。必须在 marker 前验证固定隔离解释器与精确 artifact pin，child 重新密封并绑定同一 config digest/selected pair，在凭据解析、SDK/native 调用后全程位于硬期限 Job 内。需要保留值脱敏的原始 primary reason、login/subscribe submit/ACK、tick 到达、SDK 拒绝、adapter 拒绝/接受、ACK/tick 次序以及 Join/Release/stop receipt 的独立字段；借用的 SWIG tick 指针必须只在 callback 内验证并立即归约为 enum/布尔，不得保存指针或对象。deadline、callback 截止与最终关闭结果需要分别记录。

区分 SDK 在 native callback 层拒绝 tick 需要 pinned SDK 暴露固定的拒绝原因/事件 hook；冻结 I10 pin 不足以产生此观测，且不得原位修改。上文 I13 候选已经完成独立源码/制品审查和 fake callback-order 回归；主仓已有未注册的精确 pin 受监督接线初稿，但其定向测试与独立审查尚未完成，不能据此启动真实尝试。

即使 I13 worker 通过 Windows Job containment，它也只约束受支持 operator entry 的子进程；同一 OS 用户主动直接调用私有 Python/SDK 不由该 Job/marker 隔离。I11 父进程的凭据前无凭据 front TCP 探测也不是 45 秒 Job 中的 provider 阶段；该限制须在 I13 记录中保留。任何 I13 receipt 仍不得宣称 account-ready、trading-ready、settlement-ready 或打开默认 route。

## 本地验证范围

`tests/unit/runtime/test_ctp_i13_md_observability.py` 仅用合成 event trace 覆盖无 tick、SDK 拒绝、adapter 拒绝、ACK/tick 重排、Join pending、矛盾输入和敏感值不回显。它证明投影合同，不证明 I13 supervisor、native callback 或 provider 行为。精确 SDK observability artifact 已有独立离线审计；I13 supervised composition 尚未验收，真实诊断应保持 `NOT_RUN`，直到受监督接线、独立 marker 和全部门槛经过审查。
