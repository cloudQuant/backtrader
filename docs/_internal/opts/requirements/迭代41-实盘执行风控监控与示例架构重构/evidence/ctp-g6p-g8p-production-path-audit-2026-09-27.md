# G6-P / G8-P 实盘路径源码审计（2026-09-27）

裁决：`G6-P F14_STRICT_BLOCKED / G8-P NOT_RUN / NO_WRITE / LIVE_NO_GO`。本轮只读审计，没有运行测试或访问账户、凭据、SDK 会话、provider、网络。

独立审查报告 SHA-256 为 `4ca15880a75407a029bd6ddeea0d9873f62d44d419fb07e753bcec314c7c818b`，14 份相关源码/测试/矩阵的哈希清单 SHA-256 为 `44016e5e7a676678d087bf84d87a07561437ff9abf7c215c965349aef7fd8620`。root 重新逐项核对当前树中的 14 份文件大小和 SHA-256，并将报告、清单与相应源码封存于[原始归档](ctp-g6p-g8p-production-path-audit-2026-09-27.raw.zip)；16 项内部摘要及 ZIP 完整性通过，归档 SHA-256 为 `c8a8665a122f883806a8b3923145be200ffd4567c81ef96e79fcfd25c836f982`。

默认 013_3 注册仅有零写 sandbox profile，live profile 仍声明 unavailable。共享 runner 能生成非授权计划；production session opener 在前置探测、凭据解析、SDK 导入及原生客户端创建前拒绝。现有 F14 外部准入协议与签名收据验证器没有接入共享 runner、Store 或最终派发；验签结果只是收据形状观察，不是账户写者排他或真实同版本完整快照。

真实 G6-P/G8-P 还依赖仓库外的受信账户 actor 或券商网关：它必须独占该账户的凭据和 CTP session 路径，控制跨主机、旧进程与旁路客户端，提供受同一 fence 保护的资金、全委托、成交、持仓共同版本快照，并在服务端原子执行最后的逐动作派发门。若只签发 token，却让 Backtrader 进程继续直接持有凭据并调用 `ReqOrderInsert`/`ReqOrderAction`，无法关闭旁路写者与撤销竞态。仓库可先补一项跨模块“已验签仍零副作用”的合成负测；真实服务身份、部署 pin、账户排他和最终派发事实须由外部提供与独立验收。

## 后续离线回归补充

主仓新增 `tests/unit/runtime/test_ctp_f14_shared_runtime_guard.py`，最终隔离版 SHA-256 `43ef7060ef065842d8e26f97b881c8d39084edf03a5919c32b6014cde0554d30`。它在独立子进程用临时 Ed25519 密钥对生成有效签名的合成收据，验证结果仅是 `CtpF14ReceiptContractObservation`；将其传入最终 action claim 或共享 live opener 均在派发前拒绝，正确类型的生产 adapter 也保持关闭。前置探测、凭据解析、SDK 导入、模拟盘邻接钩子及原生派发的计数均为零，默认 013_3 live-unavailable 声明仍在。初版测试在 pytest 进程中导入 PyYAML 原生模块，影响其他依赖封存测试；改为独立子进程后，作者和 root 均复跑生产守卫加该依赖测试的两文件组合 `2 passed`，Ruff 通过。pytest 禁用全局插件自动加载以避开环境中的 pytest-asyncio 收集异常，仍有一项既有配置警告。完整 runtime suite 尚有既存测试进程模块状态污染，另行处理；此补充不改变上面的只读审计原始归档，也不构成 G6-P/G8-P 正面验收。
