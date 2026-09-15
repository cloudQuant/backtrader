# Iteration 21 候选实施终审

> 审查日期：2026-09-08
> 审查范围：`bt_api_py`、Backtrader 原生 `BtApiStore`/`BtApiFeed`/`BtApiBroker`、
> 012_1、012_2、support 处置、研究证据与 Gate 边界
> 总体策略结论：`FAIL`
> 写操作结论：`paper-live/demo PROHIBITED`
> 实盘结论：`NO-GO`

## 1. 结论与理由

本迭代已把交易所协议、市场/账户读模型、typed order 与执行恢复保留在 `bt_api_py`，
Backtrader 只由既有 Store/Feed/Broker 映射框架语义。`examples/cross_exchange_arbitrage_support`
已移除，没有被 `_btapi_client.py`、`_btapi_crypto.py` 或新的 examples 支持框架替代。
最终示例是：

- `examples/012_1_midfreq_cross_exchange`；
- `examples/012_2_event_driven_cross_exchange`。

两个策略已分开实现统计/事件信号和腿状态，但“策略可实现模拟盈利”的必交付
目标被数据否决。训练校准窗口的 149,387 个因果往返在四笔、每笔 6 bps taker
费后正样本为 0，最佳结果仍为 -1.14246520 USDT，而且还未扣不利 funding、网络
延迟、失败腿损失与模型误差。这是对候选有利的上界否决。

因此，两候选均为 `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN`，证据级别是
`PRE_R1_CALIBRATION_TRAINING_SCREEN`。OOS/holdout 保持
`NOT_CONSUMED_TRAINING_SCREEN_FAILED`，不存在 R1 收益通过或模拟账户准入。

## 2. 已实现的原生能力

| 责任层 | 已实现候选 | 证据边界 |
|---|---|---|
| `bt_api_py` | typed order/cancel/query、durable intent/canonical client ID、unknown reconcile、账户级累计损失 latch、typed funding snapshot，以及无状态 `cross_venue` Decimal 规划原语 | `bt_api_contract` 559 passed；v7 隔离安装 PASS；不代表联网 PASS |
| Binance funding schedule | canonical symbol 唯一匹配；优先 `fundingInfo`，否则由公开 funding-rate history 推导 interval；无 8h 默认 | history 是费率/周期证据，不是认证账户 cashflow |
| `BtApiStore` | 有界优先命令队列，cancel/reconcile/risk-reducing 优先；独立 funding 单并发刷新通道、合并、TTL/结算边界、generation fence；typed SDK facade | v7 相关源码/安装态集各 727 passed；G2 工程 PASS |
| Feed/Broker idle risk | `notify_idle` 在无 bar 时推进数据静默风险，TickBroker/MixBroker 启用安全轮询 | 聚焦回归 2 passed，已纳入 G2 工程 PASS；网络现场证据属 G4 |
| 012_1 | 方向绑定的稳定性/半衰期资格、时间对齐 L2 VWAP、Decimal 成本 oracle、资金费窗口、失败腿补偿 | 机制可测试；经济候选被否决 |
| 012_2 | 独立 event path model、direction/first-leg/fee/depth 绑定、p99 路径、markout/CVaR、不利选择 reserve、补偿/对账 | 机制可测试；经济候选被否决；HFT `FAIL/NOT_ADMITTED` |
| candidate approval | 012 清单、离线签名收据与运行时溯源绑定 | 位于 `examples/strategy_candidate_approval.py`；wheel 无 Git build attestation 时拒绝 demo receipt |

## 3. 研究证据审核

`evidence/strategy-economic-screen-v3.json`（SHA-256
`306a701b33493c1f4c39ff91a2e4abcf3b6f863e4a1c2183b5a4ea70d321cff3`）记录数据 SHA、完整
报告 SHA `631b9b0771b5e0ef824bc7d3f3fdf0b4050963ccacbae8800fd0fc7af1d04d10`、数量、费率、时距和
限制。其方法使用当时已知的对所最新完整快照，不用未来对所行情决定入场；开平仓
均以目标数量 L2 可执行 VWAP 评估。这足以作为乐观成本前置屏，但约 15 分钟记录
无法覆盖多市场状态、资金费结算周期、私有 ACK/fill、队列位置或实盘延迟。

JSON schema-v3 中的历史状态字符串 `RESEARCH_REJECTED_CALIBRATION_ECONOMIC_SCREEN`
与本文的 `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN` 表示同一结论；为保持证据 hash，
不回写原 JSON。

历史 `research-preregistration*.md` 中的 hash 原样保留。后续 dynamic funding TTL、identity 校验和
fail-closed 窗口是工程/风控配置变化，没有改变 alpha 假设、训练数据或费后否决。

## 4. 生产阻断与反例保留

### P0：缺统一认证 `FundingCashflow` primitive

**状态**：`PRODUCTION_BLOCKED_ACTUAL_FUNDING_CASHFLOW_LEDGER`

Binance 底层 `get_income` 和 OKX trading-account `get_bills` 当前都只是单页 raw
能力，SDK 没有统一且满足下列要求的公共 primitive：

- 分页全量覆盖与窗口边界证明；
- provider/environment/account identity 绑定；
- canonical symbol、结算时刻、币种、signed Decimal cashflow 与去重 ID；
- 与 execution session 的 orders/fills/funding 完整性对账。
- event 去重/高水位、currency 汇总、账户/策略归因、结算延迟和空结果证明。

所以 SDK 返回 `funding_evidence_status=unavailable`、`signed_funding_cashflow=None` 是正确的
fail-closed 行为。任何跨越结算时点的 cycle 都不能声明 realized net 完整，这一项单独
足以阻止生产/实盘。单页 parser 无法证明时间窗完整或“确实没有资金费”，不得
冒充账户 ledger 闭环；应另立生产迭代在 `bt_api_py` 公共域实现。

### P1：数据静默的网络现场证据仍未闭合

`notify_idle` 修复了“没有下一个行情回调就无法推进 stale 检查”的结构问题。
2 个聚焦测试与更广的源码套件支持 G2 工程 PASS；它们不能替代 stop/restart、
双 venue 同时中断、有仓 wind-down 和 public network 现场收据，因此生产网络结论仍由
G4 决定。

## 5. 候选 manifest 与 G3 构建安装

schema 3 candidate manifest 已冻结为 `RESEARCH_REJECTED_DEMO_PROHIBITED`，v7 绑定 SHA-256
为 `ace39424097ad7667034b0cac7feaeeebc7dbe25ba1b37ec3c30be6ccaf96f94`。两候选的
runner/strategy/config/candidate hash 匹配，012_1 qualification-v3 与结构化 economic-screen hash
也已绑定；两候选只允许 `replay`/`shadow`，`paper-live`/`demo` 显式禁止。
最终策略/candidate hash 为：

| 候选 | strategy SHA-256 | candidate SHA-256 |
|---|---|---|
| 012_1 | `30e88f7f2f135970a0a287aea6573862d6a108b43cef27c33554f0183ceb7556` | `865ff67750460bb3a35e41fea83d5130927b30be3b1a4ad4c40b9a0295401b3d` |
| 012_2 event-driven | `cba035fc2e6b1b6f3ba1e3de988feaeb3cc8b67e9cbe8632182fae9be0632b30` | `e950f92e1c68f55521a7fbf151e93e1786ff4799cc308240cd8c7a66aaec0e07` |

独立策略审查发现重复旧 reconcile snapshot 会继续推进 fence，存在潜在活锁。修复后两策略
都加入对称回归，完整策略套件为 134 passed；上表与 manifest 总 hash 均是修复后绑定。

v7 在同一 epoch 构建并安装五个 wheel。Backtrader wheel SHA-256 为
`689146eb2acb084b2787af5e25de8b61c31697b575c6f5232ab27819200c4621`，bt_api_py wheel SHA-256
为 `f5e4ceb8442f06d13f231bad05adc06138d1b7a614161ac496216fa1269f7ded`。隔离 target、Anaconda
base wheel 强制重装、repo 外两个零写 replay 均 PASS；相关源码/安装态回归各为 727 passed。
初始 v5 wheel 被检查出仍含生成目录残留的旧 utils，已拒绝且未作为证据使用。完整五 wheel
hash、命令与 import 路径见 `evidence/2026-09-08-v7-build-install-receipt.md`。

普通本地 wheel 不含可验证 Git build attestation，candidate approval 因此在安装态拒绝签发
demo receipt。这是故意的 fail-closed 行为，而不是通过猜测源码提交来放宽准入；也不影响
当前被研究否决的两个零写 replay。

一次全库 FAST 诊断为 3251 passed、1 skipped、7 failed。7 个失败均来自当前 checkout
缺失 `examples/007_ctp/strategy_workspaces/live_certification/.gitignore` 资产。这是迭代21 以外的
工作树/资产缺口，不是迭代21 相关套件回归；该诊断也不得写成“全库 PASS”。

## 6. 历史对抗审查

`strategy-v1-adversarial-review.md`、`strategy-v2-adversarial-review.md` 和
`sdk-v2-adversarial-review.md` 保留当时反例与修复门。它们是历史快照；不能用其旧测试数或
旧 `FAIL` 直接代替当前候选 Gate，也不回写原文来掉包反例。

## 7. Gate 终审快照

| Gate | 结论 | 允许的下一步 |
|---|---|---|
| G0 | `PASS` | 已进入实施 |
| G1 | `INCOMPLETE` | 可继续本地工程收口；不得冒充最终候选 PASS |
| G2 engineering | `PASS` | 可继续零写的安装与网络观测；不授权策略下单 |
| G2 funding economics | `PRODUCTION_BLOCKED_ACTUAL_FUNDING_CASHFLOW_LEDGER` | 统一认证 `FundingCashflow` 缺失；跨结算 realized net 不完整 |
| G2 research | `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN` | 仅保留 replay/shadow 研究；新研究需新 candidate |
| HFT | `FAIL/NOT_ADMITTED` | 只能使用 event-driven 名称 |
| G3 | `PASS` | v7 五 wheel、隔离安装、base 重装、退役模块检查、repo 外 replay 与 installed 727 收据已闭合 |
| G4 | `NOT_RUN` | 可在 G3 后执行零写 public shadow，不会恢复当前策略准入 |
| G5A/G5B | `PROHIBITED` | 只读 demo preflight 可运行；不得下单 |

## 8. 待根任务封版的证据

1. 最终相关源码/quality 命令的完整计数与独立审查结论。
2. 只读 demo preflight 结果；该结果只能证明账户可读性，不能改变写操作
   `PROHIBITED`。
3. G4 如未执行保持 `NOT_RUN`；只有候选 SHA 绑定的完整公开网络收据可改变它。

这些补充收据只能更新 G1/G4 或与其相关的只读子项，不改变两个已被否决候选的
`paper-live/demo PROHIBITED` 和总体策略 `FAIL`。
