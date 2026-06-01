# 迭代6：差距矩阵与 ADR

## 1. 差距矩阵

| 项目 | 初始状态 | 迭代6结果 | 处理结论 |
|------|----------|------------|----------|
| TickBroker 结构 | 逻辑集中在 broker 内部 | 共享能力拆到 `hft/` | 已完成 |
| MixBroker | 依赖 TickBroker，bar fallback 基础可用 | 保持现有继承结构，不在本轮继续调整 | 有意保留 |
| 延迟建模 | 无 | 固定延迟 + 插值延迟 + 可见时间规则 | 已完成 |
| Stop / StopLimit | broker 内部处理 | 共享核心与 broker 路径均可验证 | 已完成 |
| `_execute()` 完整性 | 开/平仓、PnL、margin、comminfo 缺失 | 已补齐 opened/closed、PnL、margin、`addcomminfo()` | 已完成 |
| maker/taker 角色 | 无 | `QueueExchangeModel` + `FillRole` | 已完成 |
| maker/taker 手续费 | 无独立费率 | `CommInfoBase` 支持 `maker_commission` / `taker_commission` | 已完成 |
| 队列模型 | 无 | `NoQueueModel` / `ProbQueueModel` | 已完成基础版 |
| TIF | 仅基础行为 | GTX / FOK / IOC | 已完成 |
| Recorder | 无 | `Recorder` | 已完成基础版 |
| 性能基线 | 无 | 基准脚本与结果文档 | 已完成 |
| 研究交付物 | 分散在需求/任务/设计文档 | 本文档 + 对标分析 + 包结构草案独立补齐 | 已完成 |

## 2. ADR-01：共享高频能力下沉到 `backtrader/brokers/hft/`

### 决策

采用共享高频子包承载延迟、撮合、队列、状态和录制能力。

### 原因

- 避免 `TickBroker` 和 `MixBroker` 各自复制高频逻辑
- 降低 broker 自身复杂度
- 方便后续扩展更复杂的交易所/队列模型

### 影响

- `TickBroker` 负责事件入口与执行回写
- 高频语义组件可以独立测试

## 3. ADR-02：MixBroker 本轮不继续结构性调整

### 决策

虽然设计期曾偏向“组合优先”，但本轮最终决定**不改动 `MixBroker` 结构关系**，只要求其保持 `tick 优先 + bar fallback` 的功能语义。

### 原因

- 当前功能已经满足迭代6主目标
- 继续改结构会扩大变更面
- 用户已明确此轮无需修改 `MixBroker`

### 影响

- `MixBroker` 仍继承 `TickBroker`
- 后续若要进一步解耦，可另起迭代处理

## 4. ADR-03：maker/taker 手续费走 `CommInfoBase` 扩展，而不是 broker 内联

### 决策

在 `CommInfoBase` 上增加：

- `maker_commission`
- `taker_commission`

并扩展：

- `getcommission(..., role=...)`
- `confirmexec(..., role=...)`

由 `TickBroker` 在成交时传入 `maker/taker` 角色。

### 原因

- 保持与现有 `setcommission()` / `addcommissioninfo()` / `getcommissioninfo()` 兼容
- 不把手续费策略硬编码在 broker 层
- futures / digital currency / funding rate 等现有手续费模型可复用同一扩展方式

### 影响

- 默认路径完全兼容旧行为
- 高级用户可直接为指定资产配置 maker/taker 差异费率
- 支持负 maker fee 返佣

## 5. ADR-04：性能目标采用“相对基线”

### 决策

本轮不承诺追平 `py-hftbacktest` 的 Rust 性能上限，只要求：

- 基础模式吞吐可接受
- 增强模式开销可解释
- 提供可重复运行的基准脚本和结果

### 原因

- 当前实现约束为纯 Python
- 先把语义和结构做对，比空喊极限性能更重要

## 6. 结论

迭代6已把核心差距项补到“可验收、可说明、可扩展”的程度；保留项和延后项也已经通过 ADR 明确边界，不再是隐性遗漏。
