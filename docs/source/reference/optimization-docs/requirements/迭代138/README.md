# 迭代 138：Tick 级回测架构实现

> 版本: v1.0 | 日期: 2026-02-28 | 状态: 待开发

---
## 1. 迭代概述

### 1.1 目标

实现 Backtrader 的 Tick 级回测与实盘交易能力，支持：

- Tick 数据（逐笔成交）
- OrderBook 数据（盘口深度）
- Bar 数据(K 线数据)
- FundingRate 数据（资金费率）
- 自定义数据通道
- 三种运行模式（纯 K 线/纯 Tick/混合）

### 1.2 背景

基于以下设计文档：

- `docs/opts/TICK_LEVEL_ARCHITECTURE_DESIGN.md` - 总体架构设计
- `docs/opts/TICK_LEVEL_DESIGN_PART2.md` - 详细设计
- `docs/opts/TICK_LEVEL_ARCHITECTURE_IMPROVEMENTS.md` - 优化建议

### 1.3 实施策略

采用**分阶段迭代**方式，每个 Phase 独立可测试，降低风险：

| Phase | 周期 | 重点 | 风险等级 |

|-------|------|------|---------|

| Phase 0 | 1 周 | 架构验证 + 必须优化 | 低 |

| Phase 1 | 3 周 | 核心基础设施 | 中 |

| Phase 2 | 3 周 | 回测引擎 + Broker | 高 |

| Phase 3 | 2 周 | OrderBook 撮合 | 中 |

| Phase 4 | 2 周 | 桥接与实盘 | 中 |

| Phase 5 | 1 周 | 文档与示例 | 低 |

- *总计**：12 周（约 3 个月）

---
## 2. 文档结构

```bash
迭代 138/
├── README.md                           # 本文档

├── 01_Phase0_架构验证.md                # Phase 0 实施计划

├── 02_Phase1_核心基础设施.md            # Phase 1 实施计划

├── 03_Phase2_回测引擎.md                # Phase 2 实施计划

├── 04_Phase3_OrderBook 撮合.md          # Phase 3 实施计划

├── 05_Phase4_桥接与实盘.md              # Phase 4 实施计划

├── 06_Phase5_文档与示例.md              # Phase 5 实施计划

├── 测试策略.md                          # 整体测试策略

├── 风险评估.md                          # 风险识别与应对

└── 验收标准.md                          # 迭代验收标准

```

---
## 3. 核心设计决策

### 3.1 Channel 独立于 LineSeries

- *决策**：DataChannel 不继承 LineSeries，使用 deque 作缓冲

- *理由**：
- 性能：LineSeries overhead 是 deque 的 200 倍
- 灵活性：支持 OrderBook 2D 结构、字符串字段
- 兼容性：零回归风险

- *权衡**：需要可选桥接机制支持指标系统

### 3.2 流式 EventQueue

- *决策**：使用 StreamingEventQueue 替代全量预加载

- *理由**：
- 内存：从 1.7GB 降至~100MB（5 分钟窗口）
- 启动：即时启动 vs 10-30 秒加载
- 扩展性：支持长时间回测

- *优化**（来自改进建议）：
- 自适应预加载窗口
- 批量加载优化
- 内存泄漏防护

### 3.3 三种 Broker 模式

- *决策**：BackBroker（不变）+ TickBroker + MixBroker

- *理由**：
- 向后兼容：BackBroker 完全不变
- 真实性：TickBroker 支持 tick 级撮合
- 实用性：MixBroker 兼顾性能与准确性

- *优化**（来自改进建议）：
- MixBroker 撮合顺序优化
- 订单簿深度撮合
- 市场冲击模型

### 3.4 批处理通知机制

- *决策**：同 timestamp 内收集所有通知，统一分发

- *理由**：
- 避免策略在同 timestamp 内收到"未来"通知
- 保证事件处理顺序的确定性

- *优化**（来自改进建议）：
- 优先级通知队列
- 通知持久化与重放

---
## 4. 关键优化点（来自改进建议）

### 4.1 Phase 0 必须实施

| 优化项 | 预期收益 | 复杂度 |

|--------|---------|--------|

| StreamingEventQueue 自适应窗口 | 内存-30~50% | 中 |

| 数据验证与修复 | 稳定性++ | 中 |

| 策略异常隔离 | 生产可用 | 中 |

### 4.2 Phase 1 重要实施

| 优化项 | 预期收益 | 复杂度 |

|--------|---------|--------|

| MixBroker 撮合顺序优化 | 准确性++ | 中 |

| 订单簿深度撮合 | 真实性++ | 高 |

| 优先级通知队列 | 确定性++ | 低 |

| Channel 共享模式 | 灵活性++ | 中 |

### 4.3 Phase 2 可选实施

| 优化项 | 预期收益 | 复杂度 |

|--------|---------|--------|

| 市场冲击模型 | 大单准确性++ | 中 |

| 性能分析器 | 可观测性++ | 低 |

| 配置管理 | 可维护性++ | 低 |

| 批量加载优化 | I/O-40~60% | 中 |

---
## 5. 技术栈

### 5.1 核心依赖

```python

# 现有依赖（不变）

backtrader >= 1.9.76
numpy >= 1.19.0
pandas >= 1.1.0

# 新增依赖

dataclasses >= 0.6  # Python 3.6 兼容

typing-extensions >= 3.7.4  # 类型提示

```

### 5.2 可选依赖

```python

# 性能监控

psutil >= 5.8.0

# 配置管理

pyyaml >= 5.4.0

# 实盘交易

ccxt >= 1.50.0
websocket-client >= 1.0.0

```

---
## 6. 开发流程

### 6.1 分支策略

```bash
main
  └── feature/tick-level-architecture
        ├── phase0-validation
        ├── phase1-infrastructure
        ├── phase2-backtest-engine
        ├── phase3-orderbook
        ├── phase4-live-trading
        └── phase5-documentation

```

### 6.2 代码审查要求

每个 Phase 完成后必须：

1. ✅ 单元测试覆盖率 >= 80%
2. ✅ 集成测试通过
3. ✅ 性能基准测试
4. ✅ 代码审查通过
5. ✅ 文档更新

### 6.3 合并策略

- Phase 完成 → 合并到 feature 分支
- 所有 Phase 完成 → 合并到 main

---
## 7. 质量保证

### 7.1 测试策略

详见 `测试策略.md`

- *测试金字塔**：

```bash
       /\
      /E2E\         10% - 端到端测试
     /------\
    /集成测试\       30% - 集成测试
   /----------\
  /  单元测试  \     60% - 单元测试
 /--------------\

```

### 7.2 性能基准

| 场景 | 目标 | 测量方法 |

|------|------|---------|

| 1 天 Tick 回测 | < 10 秒 | benchmark_tick.py |

| 内存使用 | < 200MB | memory_profiler |

| 事件处理 | > 10K events/s | performance_test.py |

### 7.3 回归测试

- *零回归承诺**：
- 现有 1020 个测试必须全部通过
- 纯 K 线模式（BAR）行为完全不变
- 向后兼容所有现有 API

---
## 8. 风险管理

详见 `风险评估.md`

### 8.1 主要风险

| 风险 | 概率 | 影响 | 应对措施 |

|------|------|------|---------|

| 性能不达标 | 中 | 高 | Phase 0 验证 + 性能分析器 |

| 内存泄漏 | 中 | 高 | 内存监控 + 定期快照 |

| 回归 bug | 低 | 高 | 完整回归测试 + CI |

| 实盘数据异常 | 高 | 中 | 数据验证 + 异常处理 |

### 8.2 应急预案

- **性能问题**：降级到简化版 EventQueue
- **内存问题**：减小预加载窗口
- **回归问题**：回滚到上一个稳定版本
- **数据问题**：启用 auto_fix 模式

---
## 9. 验收标准

详见 `验收标准.md`

### 9.1 功能验收

- [ ] 支持 Tick/OrderBook/FundingRate 数据
- [ ] 三种运行模式（BAR/TICK/MIXED）正常工作
- [ ] TickBroker/MixBroker 撮合准确
- [ ] 实盘 WebSocket 数据接入正常

### 9.2 性能验收

- [ ] 1 天 Tick 回测 < 10 秒
- [ ] 内存使用 < 200MB
- [ ] 零回归（1020 测试全通过）

### 9.3 质量验收

- [ ] 单元测试覆盖率 >= 80%
- [ ] 集成测试通过率 100%
- [ ] 文档完整（API 文档 + 用户指南）

---
## 10. 里程碑

| 里程碑 | 日期 | 交付物 |

|--------|------|--------|

| M1: Phase 0 完成 | Week 1 | 架构验证 + 性能基准 |

| M2: Phase 1 完成 | Week 4 | 核心基础设施 + 单元测试 |

| M3: Phase 2 完成 | Week 7 | 回测引擎 + 集成测试 |

| M4: Phase 3 完成 | Week 9 | OrderBook 撮合 |

| M5: Phase 4 完成 | Week 11 | 实盘交易 |

| M6: 迭代 138 完成 | Week 12 | 完整文档 + 示例 |

---
## 11. 参考资料

### 11.1 设计文档

- [TICK_LEVEL_ARCHITECTURE_DESIGN.md](../../TICK_LEVEL_ARCHITECTURE_DESIGN.md)
- [TICK_LEVEL_DESIGN_PART2.md](../../TICK_LEVEL_DESIGN_PART2.md)
- [TICK_LEVEL_ARCHITECTURE_IMPROVEMENTS.md](../../TICK_LEVEL_ARCHITECTURE_IMPROVEMENTS.md)

### 11.2 相关迭代

- 迭代 13：多数据长度不一致修复
- 迭代 14：去除元类后的 indicator/analyzer 修复
- 性能优化阶段 1：核心性能优化（-46% runonce 时间）

### 11.3 外部参考

- [CCXT 文档](<https://docs.ccxt.com/)>
- [WebSocket 协议](<https://datatracker.ietf.org/doc/html/rfc6455)>
- [Python asyncio](<https://docs.python.org/3/library/asyncio.html)>

---
## 12. 联系方式

- **项目负责人**：待定
- **技术负责人**：待定
- **测试负责人**：待定

---
## 附录

### A. 术语表

| 术语 | 说明 |

|------|------|

| Tick | 逐笔成交数据，包含价格、成交量、方向 |

| OrderBook | 订单簿/盘口深度，包含多档买卖价格和数量 |

| FundingRate | 资金费率，用于永续合约 |

| Channel | 数据通道，独立于 LineSeries 的数据流 |

| EventQueue | 事件队列，按时间戳排序的全局事件流 |

| StreamingEventQueue | 流式事件队列，分批加载以控制内存 |

| TickBroker | Tick 级订单撮合器 |

| MixBroker | 混合撮合器（Tick + Bar） |

### B. 缩写

| 缩写 | 全称 |

|------|------|

| OB | OrderBook |

| WS | WebSocket |

| OHLC | Open/High/Low/Close |

| VWAP | Volume Weighted Average Price |

| E2E | End-to-End |

| CI | Continuous Integration |
