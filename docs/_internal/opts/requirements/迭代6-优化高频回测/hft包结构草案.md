# 迭代6：`hft` 包结构草案

## 1. 目标

本草案用于说明 `backtrader/brokers/hft/` 在迭代6中的职责切分、模块边界与依赖方向，作为 Phase 0/1 的结构性交付物。

## 2. 当前包结构

```text
backtrader/brokers/hft/
├── __init__.py
├── exchange.py
├── latency.py
├── matching_core.py
├── queue.py
├── recorder.py
└── state.py
```

## 3. 模块职责

### 3.1 `latency.py`

职责：

- 定义延迟模型接口
- 提供固定延迟与插值延迟实现
- 维护订单可见时间队列
- 为事件补充本地可见时间语义

当前核心对象：

- `LatencyModel`
- `ConstantLatencyModel`
- `IntpLatencyModel`
- `LatencyEngine`

### 3.2 `queue.py`

职责：

- 抽象挂单排队位置估计
- 处理成交事件对队列前序量的消耗

当前核心对象：

- `NoQueueModel`
- `ProbQueueModel`

### 3.3 `exchange.py`

职责：

- 定义交易所侧新单处理与 trade 驱动撮合规则
- 区分 maker / taker 角色
- 处理 GTX / FOK / IOC 等与深度相关的语义

当前核心对象：

- `FillRole`
- `OrderResult`
- `ExchangeModel`
- `SimpleExchangeModel`
- `QueueExchangeModel`

### 3.4 `matching_core.py`

职责：

- 管理待撮合订单的生命周期
- 按 `symbol` 组织 pending orders
- 处理 Stop / StopLimit 触发
- 对接 `LatencyEngine` 与 `ExchangeModel`
- 返回统一 `FillReport` / `MatchResult` / `CancelResult`

当前核心对象：

- `FillReport`
- `MatchResult`
- `CancelResult`
- `MatchingCore`

### 3.5 `state.py`

职责：

- 聚合成交后的累计统计
- 统一暴露 `fee / num_trades / trading_volume / trading_value`
- 不直接替代 broker 的 `_cash` / `_positions`

当前核心对象：

- `StateTracker`

### 3.6 `recorder.py`

职责：

- 记录订单/成交时间线快照
- 为后续指标或回放分析提供基础记录能力

当前核心对象：

- `Recorder`

## 4. 与 broker 的关系

### 4.1 `TickBroker`

职责：

- 作为 tick / orderbook 高频回测入口
- 调用共享核心进行撮合
- 执行现金、持仓、订单状态回写
- 将 maker/taker 角色传入 `CommInfoBase`

### 4.2 `MixBroker`

职责：

- 保持 `tick 优先 + bar fallback`
- bar fallback 最终仍复用增强后的 `_execute()` 路径

## 5. 依赖关系

```text
TickBroker
  ├─ LatencyEngine
  ├─ MatchingCore
  │    ├─ ExchangeModel
  │    │    └─ QueueModel
  │    └─ Stop / StopLimit trigger logic
  ├─ StateTracker
  ├─ Recorder
  └─ CommInfoBase(role-aware commission)
```

## 6. 边界约束

- `hft/` 不直接维护 broker 权威现金与持仓
- `TickBroker` 不负责实现所有高频细节，而是作为事件入口和执行回写层
- `MixBroker` 本轮不再继续做结构性改造

## 7. 结论

`hft` 子包已经形成稳定的职责边界：

- 时间语义独立
- 交易所撮合规则独立
- 队列模型独立
- 状态聚合独立
- 录制能力独立

这意味着后续继续增强高频回测时，可以在不重写 broker 主体的情况下，逐步替换或增强具体微观结构组件。
