# I12 TD-only 受监督一次性尝试（2026-09-25）

状态：`REJECTED / runtime_policy_rejected / sdk_artifact`；I12 独立 marker 已消耗，不可重置或重试。默认 CTP route 仍未注册，保持 `NO_WRITE / LIVE_NO_GO`。

这次唯一受监督的 TD-only 尝试在 Windows Job 中启动 child。父进程确认 Job containment 且 Job empty；child 以 exit code `2` 结束。回执记录的阶段名为 `sdk_artifact`，reason 为 `runtime_policy_rejected`。这仅记录当时的阶段标记，**不表示已证明固定 wheel 的 installed-origin pin 本身无效**。

I12 marker 在尝试前 absent、尝试后 present；marker 内容与路径值不在本证据中记录。真实 child exception 原件没有保留。离线源码检查发现一处确定存在、且与旧回执阶段相吻合的类型边界缺陷：I12 composition 将 sealed-config `Mapping` 传给 `binding._route`，而 `_resolve_selected_front_pair` 要求 `CtpConfiguredFrontPair`。因此这是强可复现的候选原因；由于缺少 child exception 原件，不能声称它已被最终证明为这次运行的唯一根因。拒绝发生在凭据解析和登录前。该候选缺陷不证明账号错误或供应商故障，修复与回归验证应继续在离线环境完成。

脱敏进度为：login `not_observed`；所有 TD query 均 `unverified`；close `not_attempted`；`order_submission_authorized=false`、`settlement_confirmation_called=false`。未建立 TD session，也没有订单或结算写入。I12 marker 已消费，因此不得再执行 I12 one-shot 尝试。

本页只记录此次受监督运行及已确认的代码边界，不证明 SDK/native 登录、查询、关闭、结算或交易能力。I12 设计阶段的 fake-only 合同和限制另见[I12 离线设计复核](ctp-i12-td-readonly-design-review-2026-09-25.md)。

## 后续纯离线制品预检（不重试 I12）

在保留上述历史失败结果与已消耗 marker 的前提下，单独执行了 I12 生成的**纯元数据** artifact-preflight 命令。该命令在固定隔离解释器的 Windows Job 内运行，不读取私有 `config.yaml`、凭据或 marker，不导入 CTP SDK，也不进行网络/native/provider 操作。初次离线运行中，wheel 元数据与安装来源检查本身返回 `artifact_verified`、child exit 0、Job empty，但监督器在正常进程退出后的 Job 计数短暂非零时立即请求终止，导致严格的 `_i12_artifact_preflight_succeeded` 拒绝。

监督器随后改为：正常 child exit 先在剩余总预算和既有 grace 内有界等待 Job 自然清空；未清空才终止。pending native Join、超时与错误路径仍立即终止，I12 的接受谓词未放宽。修改后的同一纯元数据命令返回 `artifact_verified`，`sdk_imported=false`、`credential_resolver_invoked=false`、`native_join_pending=false`；进程创建/Job 分配/恢复/exit 0 均已观察，`job_termination_requested=false`、Job empty、containment verified、无 retained control，且严格 artifact predicate 为 true。监督器定向 fake 测试为 `20 passed`，Ruff 与 `py_compile` 通过。

这证明**当前离线制品预检路径**在本机可通过，不证明历史 child 原始异常的唯一根因，也不补做任何 TD 登录或查询。I12 一次性 marker 不可复用；真实 SimNow 会话、原生关闭和交易写入仍未验收。
