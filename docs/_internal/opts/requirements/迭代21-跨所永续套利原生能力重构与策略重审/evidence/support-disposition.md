# `cross_exchange_arbitrage_support` 逐对象处置记录

> 日期：2026-09-07；处置快照更新：2026-09-08
> 决策：不迁移整包；由 SDK/Core/独立策略替代，不保留兼容转发包。
> 当前状态：`SOURCE_REMOVAL_PASS`；`G3_INSTALLED_PARITY_PASS`（v7 epoch）

## 处置表

| 旧对象 | 决策 | 目标责任层 | 完成条件 |
|---|---|---|---|
| `.env.example` | `REWRITE` | 两个 example | 每个目录只有变量名模板 |
| ignored `.env` | `PRESERVE_BYTES` | 两个 example runtime asset | 复制后 mode/size/hash 相等且被 ignore；不解析内容 |
| `.gitignore` | `REWRITE` | 两个 example | 忽略 `.env`、报告、journal、lock、receipt |
| `__init__.py` | `DROP` | 无 | 活动源码、测试和用户文档零引用 |
| `Quote` | `PROMOTE/REPLACE` | Backtrader 标准事件 | 标准 orderbook 带时间、连续性和深度 |
| `VenueRules` | `PROMOTE/REPLACE` | `bt_api_py.InstrumentSpec` | Decimal 规则、fingerprint 和格点合同通过 |
| `RiskConfig` | `REWRITE` | 每个 strategy | 两策略各自冻结风险配置，不共享 alpha/state |
| `AccountSnapshot` | `PROMOTE/REPLACE` | `bt_api_py`/Broker | 标准账户、readiness 和 position cache 通过 |
| `Intent` | `REWRITE` | 每个 strategy | 独立 pair intent 和补偿状态机通过 |
| quantity/price helpers | `PROMOTE/REPLACE` | SDK quantization + 正式 Decimal oracle | 无 float fallback；边界 fixture 通过 |
| `SpreadSignal` | `DROP_AND_REWRITE` | 012_1/012_2 | 012_1 z-score 真正门控；012_2 独立事件信号 |
| `strategy_defaults` | `DROP_AND_REWRITE` | 两个 config | 参数具单位、来源和冻结状态 |
| `configuration.py` | `SPLIT` | SDK environment/readiness；各 runner CLI | examples 不含 vendor endpoint/schema |
| `entrypoint.py` | `DROP_AND_REWRITE` | 两个 `run.py` | runner 自包含且 import 白名单通过 |
| synthetic replay builders | `MOVE_TO_TESTS` | strategy tests | 六类机制 fixture 不计入收益研究 |
| `ReplayClient` | `MOVE_TO_TESTS/REPLACE` | 标准 Feed fixture | example runtime 不依赖私有 replay client |
| `run_network.py` preflight | `PROMOTE/REPLACE` | SDK typed readiness + Store/Broker | 两所统一合同，删除 OKX 专属分支 |
| `run_network.py` orchestration | `REWRITE` | 两个 `run.py` | replay/shadow/paper-live/demo 模式语义通过 |
| `DeadlineShutdownController` | `PROMOTE/REPLACE` | Broker 通用 winddown；策略 pair 补偿 | 关停撤单、平腿、最终对账通过 |
| `MidFrequencyArbitrageStrategy` | `DROP_AND_REWRITE` | 012_1 | AC-MID-001~010 通过 |
| `HighFrequencyArbitrageStrategy` | `DROP_AND_REWRITE` | `012_2_event_driven_cross_exchange` | 不继承 012_1；HFT Gate `FAIL/NOT_ADMITTED` |
| cost logic | `PROMOTE/REPLACE` | `bt_api_py.cross_venue` | 两策略和独立报告重算调用同一无状态 typed Decimal oracle；不含 pair 协调 |
| ignored reports | `ARCHIVE_THEN_RELOCATE` | ignored evidence/new per-example reports | 字节快照完整；历史证据不混入新候选结果 |
| journal | `DECLARATIVE_MIGRATION_OR_NONE` | SDK account ledger | 每条 intent 唯一 claim；本次扫描无旧 journal 文件 |
| `.lock` | `ARCHIVE_THEN_RECREATE` | SDK account ledger | 不复制旧 lock；新 writer 创建新 inode/lease |

## 已执行的资产保护

- 旧 support 用户资产共 22 个文件已保存到 checkout-local ignored evidence；逐字节复核为
  `22/22` 一致。
- 旧 `.env` 已分别复制到 012_1 和 012_2；两个副本权限均为 `0600`，size/hash 与旧文件
  相等，并由各自 `.gitignore` 忽略。
- 审计没有发现正在写 support 的进程，也没有发现实际旧 order journal；存在的零字节 lock
  只归档，不会复制成新 ledger lock。
- 上述检查没有解析或输出凭据值。

## 最终处置记录

| 删除门项 | 状态 | 证据边界 |
|---|---|---|
| SDK typed contract/account ledger/async execution | `IMPLEMENTED_WITH_TEST_EVIDENCE` | SDK contract 套件 559 passed；真实 funding cashflow 为 `PRODUCTION_BLOCKED_ACTUAL_FUNDING_CASHFLOW_LEDGER`，不恢复 support 或在 Backtrader 硬编码 |
| Store/Feed/Broker 原生替代 | `G2_ENGINEERING_PASS` | 使用既有三个类；优先队列、对账、funding cache 和 `notify_idle` 已实施；策略单测 134 passed，pair/mode 合同 54 passed |
| 两个 example/测试无 support import | `PASS` | 最终路径为 012_1 和 `012_2_event_driven_cross_exchange`；没有示例级运行支持包 |
| candidate manifest | `PASS` | schema 3，状态 `RESEARCH_REJECTED_DEMO_PROHIBITED`；v7 SHA-256 `ace39424097ad7667034b0cac7feaeeebc7dbe25ba1b37ec3c30be6ccaf96f94`；两候选只允许 replay/shadow |
| 用户资产 | `PASS` | checkout-local ignored evidence 中 22/22 个文件一致；两份 `.env` 均为 `0600`，size/hash 与原文件一致；未解析或输出凭据值 |
| 活动源码引用与目录 | `PASS` | `examples/cross_exchange_arbitrage_support` 已不存在；活动运行引用为零；历史文档保留路径文字 |
| source/isolated-install replay parity | `PASS` | v7 五 wheel、隔离安装、base wheel 强制重装、repo 外两 replay 与相关源码/安装态集各 727 passed |

目录已在源码态删除，不再恢复一个已知不合理的 examples 运行框架。v7 G3 收据位于
`.git/iter21-evidence/2026-09-08-cross-venue-layer-v7/`；Backtrader wheel SHA-256 为
`689146eb2acb084b2787af5e25de8b61c31697b575c6f5232ab27819200c4621`，bt_api_py wheel SHA-256
为 `f5e4ceb8442f06d13f231bad05adc06138d1b7a614161ac496216fa1269f7ded`。初始 v5 wheel 的生成目录
残留已被拒绝，v7 已验证两个旧 Backtrader utils 不可导入。完整收据见
`evidence/2026-09-08-v7-build-install-receipt.md`。后续若再发现安装态漏包或残留引用，应修复
正式 SDK/Core/策略归属，不重建 support 兼容包。
