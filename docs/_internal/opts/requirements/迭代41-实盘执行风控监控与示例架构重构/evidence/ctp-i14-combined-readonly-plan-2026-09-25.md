# I14 同配置 TD→MD 只读候选设计（2026-09-25）

状态：**设计待实现；未创建或消耗 I14 marker，未访问 provider；`NO_WRITE / LIVE_NO_GO`。** 此候选只用于排查并验收真实 SimNow 只读会话，不包含报单、撤单或结算写入。

I14 使用唯一受保护的 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`。父进程只从密封的 canonical `ctp:` 中选择一组成对的 MD/TD 前置，并绑定配置摘要、登记摘要、候选索引及所选 pair 的摘要。TD 与 MD 分别在两个顺序启动的 Windows Job 子进程内运行；每个子进程重新密封同一配置，验证同一 pair，不重新选前置。只有 TD 身份、七项只读查询及原生关闭全部正面确认，才启动 MD Job。任何失败、未知或关闭未完成都停止流程。

单一 `time.monotonic()` 总预算从配置密封前开始，覆盖无凭据前置探测、制品元数据预检、一次性 latch、两个 Job、终止和清理；后续阶段只使用剩余预算。现有 supervisor 可传递绝对截止时间，但同步 Windows/Python 调用仍不能被该检查抢占，因此它**不是硬性整条命令期限证明**。普通 `bt-runtime preflight` 继续 fail-closed，待独立审阅和真实验收后再评估。

进入真实 I14 尝试前必须分别关闭以下门槛：

1. I11 的 MD 订阅 ACK 已观察到，但身份为 `identity_unverified`，匹配 tick 和同交易日均未正面确认；I14 必须要求这三项以及精确合约订阅的正面证据。SDK I13 候选的值脱敏回调观测接口须先经独立审阅、制品复现与隔离 pin 验证。
2. I12 历史尝试在 `sdk_artifact/runtime_policy_rejected` 结束，未建立 TD session；当前源码已修复一个确定的 Mapping→`CtpConfiguredFrontPair` 类型错误，但历史 child exception 未保留，不能认定它是唯一根因。I14 必须先在独立 Job 内完成自身固定制品的纯元数据预检，拒绝发生在凭据与 SDK 导入前。
3. 历次原生 `Join` 未完成。TD 与 MD 都必须分别提供正面的 Release、Join 返回和线程退出证据；Job empty 或 `client_stop_returned` 不替代原生关闭。TD 关闭未知时不得开始 MD。

候选应使用独立 I14 receipt、原因枚举、artifact pin、受控无 system-site-packages 解释器与一次性 marker，不能复用 I11/I12 的身份或已消耗 marker。公开回执仅允许固定枚举、布尔、有界计数、耗时和候选索引；不得输出前置、账号、凭据、合约、交易日、行情值、原始回调或异常文本。离线测试至少覆盖配置/pair 绑定、pin 拒绝先于凭据、跨阶段同一预算、Job 收拢、严格 TD/MD 成功谓词，以及 I11/I12/Join 未完成证据均不能产生成功。

2026-09-25 主仓完整离线 runtime suite 在 I12 共用预算与 Job 自然清空修复后为 `1579 passed, 26 skipped, 1 existing PytestConfigWarning in 80.87s`（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p no:asyncio tests/unit/runtime -q`）；Ruff 对相关修改文件通过。此前 `1576 passed, 26 skipped` 是 Job 自然清空修复前的 checkpoint。独立 I12/supervisor 首轮及修复增量复审均未发现 P1/P2；后者定向复核 4 项通过。该结果不代表真实会话、下单、撤单或生产准入。
