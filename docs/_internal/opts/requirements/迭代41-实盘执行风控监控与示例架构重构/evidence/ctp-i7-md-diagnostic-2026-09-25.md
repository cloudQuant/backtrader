# I7 受监督 MD-only 诊断（2026-09-25）

本页记录两次 I7 只读的 CTP MD-only 诊断：首轮的脱敏 native-shape 字段因主仓投影遗漏而不可用；修复投影后的第二轮仍未接受登录，且没有订阅 ACK、匹配 tick、交易写入或结算写入。两轮均非完整 preflight、账户 readiness 或写入验收。

经独立复核的 one-shot supervisor 对本次进程返回 `containment_verified=true`：root process 以 exit code 3 退出，Windows Job 为空且无 descendant。这个结果只证明本次子进程 containment。SDK native shutdown 仍未完成：终态为 `incomplete / market_client_stop_failed`，native Join pending。

首轮报告的 native-shape 指标为 null；复查发现主仓 I3 failure-diagnostics helper 漏复制这些 enum，因此 null 仅表示观察投影缺字段。修复后第二轮的 value-free 观察为：一个登录 callback，disposition 为 identity rejected（`broker_id_mismatch`），request-ID relation 与 response error 均为零；Python getter 和 native BrokerID/UserID 字段形状均为空，TradingDay 形状有效。SDK wheel/callback getter 映射的本地 fake 验证通过（I3/I7 焦点集 68 项通过），第二轮据此排除简单 SWIG getter 丢值，但真实空身份来源仍未确定。官方 Mini API 手册未承诺 BrokerID/UserID 必须非空或回显；观察到空字段仅说明 SDK strict identity 校验失败、身份未证实，不能据此推断账号配置错误。任何后续 I8 诊断候选须固定单合约并取得订阅 ACK 与首 tick；即使取得，也不等于账号 readiness 或写权限。第二轮的 containment 也通过核验：`containment_verified=true`、root exit 3、Job empty、无 descendant。没有订阅 ACK 或 tick；native Join pending，交易和结算写入计数均为零。

这两次结果不证明完整 TD/MD preflight、账号身份就绪、结算能力、订单能力或安全的 native Release/Join 次序。I7 诊断仍未注册为 runtime/CLI route，也未开放 live/write。待办是解释真实 callback 为什么返回空 identity，并独立完成 native shutdown 与账户范围证据审查；当前仍为 `NO_WRITE / LIVE_NO_GO`。

[SimNow 官方产品页](https://www.simnow.com.cn/product.action)说明其 7x24 环境用于 CTP API 测试且不提供结算服务。TCP 可达或 login callback 不能替代实际业务回调和账户查询；若所选前置不具备相应交易/结算能力，相关验收保持未通过。本文不包含前置地址、账户值或认证材料。

## Native shutdown boundary

Independent review of the official Mini API manual and accompanying 6.7.7 MD/TD headers found Join described as waiting for API-thread exit and Release as deleting the API object. No Stop API or timed Join was found, and no guarantee was found for concurrent Release during pending Join or callback quiescence after `RegisterSpi(nullptr)`. Thus the I7 Job containment result does not prove SDK orderly-close. A future native route requires a supervised worker, account writer lease, and unknown-result recovery; force termination records the worker as abandoned. No such worker route is implemented or accepted.

References: [official SimNow Mini API manual](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf), [official API download page](https://www.simnow.com.cn/static/apiDownload.action).
