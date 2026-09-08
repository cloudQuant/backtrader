---
id: SPEC-ITER21-CROSS-VENUE-PERPETUAL-ARBITRAGE
version: 1.2
status: implemented_with_research_rejection_and_open_acceptance_gaps
created: 2026-09-07
updated: 2026-09-08
companions:
  - 需求文档.md
  - 设计文档.md
  - 验收文档.md
  - 任务.md
  - 追踪矩阵.md
---

# 迭代21：跨所永续套利原生能力重构与策略重审

## Why

迭代开始时，012_1、012_2 示例把约 1200 行策略与运行逻辑集中在
`examples/cross_exchange_arbitrage_support/`，两个示例本身只剩导入与参数覆盖；同时
012_2 没有独立高频逻辑，`entry_zscore` 也没有参与交易决策。这个结构既掩盖了
`bt_api_py`、`BtApiStore`、`BtApiFeed`、`BtApiBroker` 的真实能力边界，也无法证明两个
套利假设在成本、延迟和双腿风险下成立。本迭代先重审策略与职责，再用正式公共接口承载
通用能力，使示例保持自包含、可审计和可迁移到模拟交易。实施结果证明原有策略经济假设
无法覆盖四笔 taker 费用，因此工程候选保留为 replay/shadow 研究样例，不进入
paper/demo 写入。

## Current disposition

- `examples/cross_exchange_arbitrage_support` 已移除，没有兼容转发包；两个最终目录为
  `012_1_midfreq_cross_exchange` 和 `012_2_event_driven_cross_exchange`。
- 双 venue L2 训练校准屏属于 `PRE_R1_CALIBRATION_TRAINING_SCREEN`；149,387 个因果
  往返评估在四笔、每笔 6 bps taker 费后无正样本，两候选均为
  `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN`。
- 预留 OOS/holdout 为 `NOT_CONSUMED`，不将该训练筛选冒充 `R1`；`paper-live`
  和 `demo` 订单写操作为 `PROHIBITED`，只读 public/shadow 与 demo preflight 可继续。
- 012_2 的 HFT Gate 为 `FAIL/NOT_ADMITTED`；它只是事件驱动研究候选。
- schema 3 candidate manifest 已冻结为 `RESEARCH_REJECTED_DEMO_PROHIBITED`；两候选只允许
  `replay`/`shadow`。v7 构建时的 manifest SHA-256 为
  `ace39424097ad7667034b0cac7feaeeebc7dbe25ba1b37ec3c30be6ccaf96f94`；新候选源文件变更后
  必须重新计算，不能复用该收据。
- 动态资金费快照、TTL 和 fail-closed 路径已实现；统一、分页完整且绑定账户身份的
  typed `FundingCashflow` 仍缺失，精确状态为
  `PRODUCTION_BLOCKED_ACTUAL_FUNDING_CASHFLOW_LEDGER`。数据静默 watchdog 已通过
  `notify_idle` 路径实现；相关源码态/安装态回归均为 727 passed，生产级网络结论仍需 G4。
- v7 的五个 wheel、隔离安装、base wheel 强制重装、退役模块检查和 repo 外 replay 已有
  新鲜收据；源码 SDK contract 为 559 passed，相关源码/安装态集均为 727 passed。因此 G3 的
  制品消费者门为 `PASS`。它不替代 G1 独立终审、真实 funding cashflow、G4 或 G5。G4 保持
  `NOT_RUN`。

## Evidence index

| 证据 | 角色 | 当前结论 |
|---|---|---|
| `evidence/G0-document-gate.md` | 文档/ID/基线门 | `G0 PASS` |
| `evidence/support-disposition.md` | support 逐对象归属、用户资产与删除记录 | 源码删除与 v7 安装 parity PASS |
| `evidence/2026-09-08-v7-build-install-receipt.md` | 当前五 wheel、重装、隔离消费与 replay 收据 | G3 artifact consumer PASS；不授权 demo/live |
| `evidence/research-preregistration.md` | 历史 V1 研究冻结 | 原 hash 保留；不作当前候选收据 |
| `evidence/research-preregistration-v2.md` | 历史 V2 候选/OOS 协议 | 原 hash 保留；OOS 未消费 |
| `evidence/strategy-economic-screen-v3.json` | 训练校准成本前置屏结构化摘要 | 两候选研究否决 |
| `evidence/strategy-economic-screen-v3.md` | 前置屏可读解释与限制 | `PRE_R1`，OOS `NOT_CONSUMED` |
| `examples/strategy-candidate-manifest.json` | 候选路径、hash、研究与模式准入 | schema 3 已冻结，两候选研究否决 |
| `evidence/sdk-v2-adversarial-review.md` | 历史 SDK V2 反例 | 历史快照，保留不回写 |
| `evidence/strategy-v1-adversarial-review.md` | 历史策略 V1 反例 | 历史快照，保留不回写 |
| `evidence/strategy-v2-adversarial-review.md` | 历史策略 V2 反例 | 历史快照，保留不回写 |
| `.git/iter21-evidence/2026-09-08-cross-venue-layer-v7/` | wheel、隔离安装、base 重装的本地原始收据 | 本地 ignored 证据；hash 摘要由 v7 build receipt 固化 |
| `evidence/final-implementation-review.md` | 当前候选实施、门禁和生产阻断终审 | 总体 `FAIL`，写操作 `PROHIBITED` |

## Capabilities

### CAP-1 原生依赖边界

- **intent**：两个 012 示例只依赖 Backtrader 公共 API、`bt_api_py` 公共 API、声明的依赖和各自目录内的策略装配代码。
- **success**：示例之间无跨目录导入，活动代码、测试和用户文档不再存在或引用
  `cross_exchange_arbitrage_support`，也不新增 `_btapi_client.py`、`_btapi_crypto.py` 等第二套
  交易客户端；历史迭代审计可保留路径文字。

### CAP-2 统一 SDK 合约

- **intent**：`bt_api_py` 统一处理 OKX/Binance 的模拟环境、认证、合约元数据、数量单位、订单请求、私有事件和不确定订单对账。
- **success**：同步与非阻塞写操作都通过带类型、归一化、幂等和执行会话保护的公共 `BtApi`
  合约完成；账户持仓模式只经公共 `set_position_mode` 变更，且必须同时通过 provider
  acknowledgement 与随后账户 readback；未知结果使缓存失效并锁住所有加密货币下单入口，直到
  fresh normalized read 收敛。持仓快照用 `Decimal` 保留精确零语义：query 只过滤
  `quantity_known=true` 且 `quantity_exact_zero=true` 的行，event 零量仍作为平仓 tombstone
  交付。Backtrader 不包含交易所请求字段映射。

### CAP-3 Backtrader 原生适配

- **intent**：只通过现有 `BtApiStore`、`BtApiFeed`、`BtApiBroker` 把 SDK 数据和订单状态映射为 Backtrader 语义。
- **success**：行情回调不执行网络阻塞 I/O；订单、成交、账户、持仓、断线和盘口连续性事件可观测。
  `BtApiStore`/`BtApiBroker` 只读验证 position mode 并 fail closed，不更改账户模式；账户变更只由
  SDK 公共接口完成，runner 不保存 venue schema 或私有 mapper。源码安装与重新安装后
  的行为一致。

### CAP-4 中低频策略重写

- **intent**：012_1 实现经成本约束的跨所永续合约基差均值回归，而不是只观察 z-score 或只判断瞬时价差。
- **success**：同步可执行报价、均值偏离、预期收敛、四笔交易费用、滑点、资金费、持仓期限和止损都真实参与开平仓决策，并有无前视的样本外证据。

### CAP-5 高频候选策略准入

- **intent**：012_2 采用独立的事件驱动套利假设，是否继续称为“高频”由数据和执行能力决定。
- **success**：策略不继承 012_1 的信号实现；具备盘口序列、陈旧/时钟偏差、深度、延迟与不利选择保护。若已执行的非阻塞路径或延迟门槛未通过，则明确降级命名并把 HFT 目标标为 `FAIL`；外部数据不可得才标 `BLOCKED`，不以调小参数冒充高频。

### CAP-6 双向持仓与双腿安全

- **intent**：OKX、Binance 永续合约全程使用 `dual_side`/hedge 语义，分别保留 long/short 腿，并处理跨所非原子执行。
- **success**：只读 preflight 发现账户模式不一致时零订单写入失败；任何独立的模式配置工具
  只能调用 SDK 公共 `set_position_mode`，不可调用 provider 私有方法。部分成交、拒单、超时、
  重复事件、断线和第二腿失败都进入确定状态机，未知结果阻止加仓，结束时可证明无挂单、
  无未知订单和目标净敞口归零。

### CAP-7 配置、凭据与运行模式

- **intent**：支持 replay、public paper/shadow 和 authenticated demo 三种清晰模式，凭据只从环境变量或被忽略的本地 `.env` 读取。
- **success**：环境与交易权限预检可阻断错误写入；日志、异常、报告和配置快照不含 API key、secret、passphrase、签名、listen key 或私有 URL 参数。

### CAP-8 可证伪的收益研究

- **intent**：用真实成本、无前视回放和公开行情观察评估策略，而不是承诺盈利或用人工盈利样本替代证据。
- **success**：分别报告机制正确性、样本外研究结果、public shadow 机会质量、demo 执行正确性和 demo 观察性 PnL；任何单次正收益都不能单独通过发布门禁。

### CAP-9 安装与消费端一致性

- **intent**：改进后的 `bt_api_py` 和 Backtrader 可从源码构建、重新安装并由实际消费端运行。
- **success**：记录源码 SHA、wheel SHA、安装位置和版本；本地源码测试与隔离安装测试均通过，且安装环境无法导入被禁止的第二客户端模块。

### CAP-10 支持目录退役

- **intent**：对支持目录逐项判定保留、重写、提升到公共 API、迁移到测试夹具或删除，不能机械搬迁整包代码。
- **success**：每项能力已有新归属和测试后才原子删除目录；删除后两个示例、核心回归和安装态验收全部通过。

## Constraints

- 候选源码可继续本地、隔离安装和只读网络验证；当前研究状态禁止
  `paper-live` 和 `demo` 订单写操作。
- 交易范围限定 OKX 与 Binance 的 USDT 本位永续合约模拟环境；实盘资金运行需另立迭代和人工放行。
- 策略及 broker 必须显式使用 `dual_side`；不接受 net/one-way 自动降级。
- SDK 保持对数字货币交易所、CTP、MT5 等统一接口的兼容，不把 Backtrader 专用概念写入交易所插件公共域模型。
- Backtrader 侧优先扩展现有 `backtrader/stores/btapistore.py`、`backtrader/feeds/btapifeed.py`、`backtrader/brokers/btapibroker.py`；交易所协议和认证仍归 `bt_api_py`。
- `BtApiStore`/`BtApiBroker` 和两个策略 runner 只验证已读到的 position mode；不得在启动流程中自动变更账户，
  也不得维护 OKX/Binance 私有变更字段。需变更时由独立管理步骤显式调用 `BtApi.set_position_mode`，
  随后再用只读 preflight 确认。
- 通用能力只有在存在稳定公共语义和至少两个合理消费者时才提升到框架；策略假设、阈值和配对状态保留在示例策略中。
- 同一 demo 账户只能有一个权威 execution ledger 和一个有效 writer lease；策略 ID 只作分区，
  不能把旧共享 unknown intent 拆给多个恢复者。
- 所有 Python 命令使用 `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python ...` 或该环境中的模块入口。
- 本轮不读取、打印、提交或复制真实凭据；后续迁移只允许不解析内容的字节级备份/复制与
  hash 校验，示例源码只提交变量名和占位模板。

## Non-goals

- 不保证模拟或实盘盈利，也不把 demo 成交质量等同于真实队列位置、流动性和延迟。
- 不在本迭代接入更多交易所、现货、交割合约、CTP 或 MT5 套利策略。
- 不构建独立交易终端、第二套 SDK 客户端或 examples 级公共框架。
- 不以 maker 排队模型作为首版默认执行；maker-taker 只有在队列、撤单延迟和成交概率数据充分时另行准入。
- 不要求跨交易所原子成交；系统必须显式管理腿风险和补偿。
- 不因现有文件或类名存在就承诺保留其内容、参数或算法。

## Success signal

迭代只有在需求追踪矩阵中的所有 P0/P1 自动化门禁、源码态与安装态门禁、两套独立策略语义门禁、两套策略各自的 `STRATEGY_APPROVED_FOR_DEMO`、两家模拟账户的只读预检和最小订单生命周期门禁均取得新鲜证据后，才可标记 `PASS`。外部账号、权限、合格数据或交易所环境不可用记为 `BLOCKED`；未执行记为 `NOT_RUN`；经济假设被数据否决记为 `RESEARCH_REJECTED`，对应策略与总体目标不得 PASS。当前两个必交付候选均在训练成本筛选被否决，所以总体策略目标已为 `FAIL`；后续工程或安装门禁即使通过也不能覆盖该结论。收益研究与工程子门禁分别报告，也不能把任何工程 `PASS` 描述为可实盘盈利。

## Assumptions

- 首选研究标的是两家交易所共同提供、合约规则可精确对齐且深度充足的 USDT 本位永续合约；最终标的由实施时的元数据与流动性审计确定。
- 第一版执行研究以 taker-taker IOC 为基线，原因是成交状态更容易验证；该冻结候选已被训练成本屏否决，不再进入 OOS 或 demo。
- 候选路径、runner、strategy、config、qualification 和 economic screen 已由 schema 3 manifest
  冻结；只有绑定这些 hash 的收据可以改变对应 Gate。

## Open questions

- 两个模拟账号的实际费率档位、资金费口径、最小下单量、杠杆和可交易标的需要在不泄露凭据的预检中重新读取。
- 012_2 的 taker-taker 基线已在训练校准成本屏中被否决，HFT 命名已取消；新假设必须使用新 candidate ID、新预注册和未见 holdout。
- 是否值得建立通用多腿订单协调器需要先找到第二个非 012 消费者；否则本迭代允许两个策略各自保留小型状态机。
