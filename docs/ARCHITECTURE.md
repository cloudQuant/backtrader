# Backtrader 架构说明 (Architecture)

> 面向贡献者的架构导览。配合 `CONTRIBUTING.md`（开发流程）与
> `docs/LOGGING_GUIDELINES.md`（日志规范）阅读。

本仓库是 backtrader 的性能优化分支：移除了元类、优化了 broker、并以纯 Python
（必要处用 Cython 辅助）重写关键路径。核心设计目标是**在保持原版 API 完全兼容**
的前提下提升执行速度与可维护性。

---

## 1. 分层架构 (Layers)

```text
Strategy (用户代码)
   │  buy/sell/close/order_target_*  ←→  notify_order/notify_trade
   ▼
Cerebro (编排)  ── 装配 datas/strategies/observers/analyzers/sizers/writers，
   │                驱动 runonce(向量化) / runnext(事件驱动) / tick 三种主循环
   ▼
Broker (撮合 + 组合状态)  ── 现金/保证金/持仓/订单撮合；net 与 dual_side 两种持仓模式
   ▲
Data Feeds (feed + feeds/)  ── 加载并按时钟推进行情
   ▲
Line System (数据基座)
   lineroot → linebuffer → lineseries → lineiterator
```

数据流：feeds 产出按时间排序的 bar/tick → cerebro 主循环对齐各 feed 时钟并推进 →
strategy/indicator/observer/analyzer 在每个时钟点被调用 → strategy 下单 → broker
撮合并回填持仓/现金 → observer/analyzer 记录。

---

## 2. Line 系统（最重要、最动态的子系统）

backtrader 的「线」(line) 是带最小周期(minperiod)与时钟(clock)语义的时间序列。

| 模块 | 职责 |
| --- | --- |
| `lineroot.py` | 线的根接口：运算符重载（`+ - * /` 等返回 `LinesOperation`）、owner 查找 |
| `linebuffer.py` | 用环形缓冲存储线数据；`LineActions`/`LinesOperation` 延迟计算 |
| `lineseries.py` | 多线容器（`Lines`）、线别名、`__setattr__` 时的线绑定与时钟传播 |
| `lineiterator.py` | 迭代逻辑：`prenext`/`next`/`once` 三相；indicator/strategy/observer 的公共基类 |

关键概念：

- **minperiod**：一条线在能产出有效值前需要的最少 bar 数。indicator 把各输入的
  minperiod 向上聚合（见 `Strategy._periodset` / `Indicator._finalize_minperiod`）。
- **clock（时钟）**：驱动一个 lineiterator 推进的数据源。多数据/多时间框架回测中，
  从**次级（较慢）feed** 派生的 indicator 必须按其所属 feed 的时钟推进，否则会在
  runonce 模式下错位——这正是 `_periodset` 里二级时钟绑定逻辑解决的问题
  （见 `docs/DEV_REGRESSION_FAILURES.md`，回归网是 `make test-strategies`）。
- **runonce vs runnext**：`runonce` 向量化（每条线一次性 `once()` 批量计算），
  `runnext` 事件驱动（逐 bar `next()`）。两者数值结果必须一致。

> 这些模块大量使用「构造期未定型、运行期才赋真值」的动态属性，因此在
> `pyproject.toml` 的 mypy 覆盖里对它们关闭了若干必然误报的检查码。修改时务必跑
> 全量测试。

---

## 3. 无元类的对象系统 (No-Metaclass Object System)

原版 backtrader 依赖元类做参数/线声明。本分支用 **mixin + `donew()`** 替代：

- `metabase.py`：`BaseMixin`、`ObjectFactory`、`findowner()`、`donew/dopreinit/
  dopostinit` 生命周期钩子；`AutoInfoClass` 承载动态参数类。
- `parameters.py`：描述符式参数系统（`ParameterDescriptor` + `ParameterManager`），
  支持类型校验、继承（`inherit_from` 的 merge/replace/add_only/selective 策略）、
  分组、依赖、变更回调。
- **硬规则**：不要新增元类；新组件走 `donew()` 模式；子类 `__init__` 必须先
  `super().__init__()` 再访问 `self.p`。

---

## 4. 组件 (Components)

均继承自 `LineIterator`：

| 组件 | 基类文件 | 子类目录 | 作用 |
| --- | --- | --- | --- |
| Indicator | `indicator.py` | `indicators/` | 技术指标（50+） |
| Analyzer | `analyzer.py` | `analyzers/` | 绩效分析（17+），结果存 `rets` |
| Observer | `observer.py` | `observers/` | 记录现金/持仓/成交等用于绘图 |
| Sizer | `sizer.py` | `sizers/` | 头寸规模 |

注册约定：新增 indicator/analyzer/feed 需在对应 `__init__.py` 登记。

---

## 5. 执行与撮合 (Execution)

- `broker.py` + `brokers/`：`BackBroker`（回测撮合）、`TickBroker`（tick 级撮合
  状态机，`brokers/hft/` 提供延迟/队列/撮合模型）、实盘 broker（btapi/CTP 等）。
- `order.py` / `trade.py` / `position.py`：订单、成交、持仓数据结构。
- `position_modes.py`：net 与 dual_side（双向持仓）的归一化与校验。
- `comminfo.py` + `commissions/`：手续费/保证金/杠杆模型。

---

## 6. 数据与订阅 (Data)

- `feed.py` + `feeds/`：CSV、pandas、IB、CCXT、CTP 等数据源；`feeds/` 内各类
  负责解析并产出按时间排序的 bar。
- `resamplerfilter.py`：重采样/回放（replay），把高频数据聚合为低频或逐 tick 回放。
- `channels/` + `events.py`：tick 级回测的事件流（tick/orderbook/funding）。

---

## 7. 日志与可观测性 (Logging)

统一入口 `backtrader/utils/log_message.py`（`get_logger`/`configure_logging`/
`set_level`/`reset_logging`）。库默认静默，用户显式开启。框架内部一律走
`get_logger(__name__)`，不直接 `import logging`。详见 `docs/LOGGING_GUIDELINES.md`。

---

## 8. 兼容性约束 (Compatibility Constraints) ⚠️

任何改动都必须遵守（详见 `docs/CODE_QUALITY_ITERATION_PLAN.md`）：

1. 公共 API 不删除、不改签名；导入路径不变。
2. 类继承关系不变（`isinstance` 行为不变）。
3. 参数默认值不变；数值结果、订单逻辑、事件顺序可重现。
4. 每次改动：`pytest tests -n 8` 全绿 + CI 全绿 + benchmark 无显著回归。

---

## 9. 代码地图 (Where things live)

```text
backtrader/
├── cerebro.py          # 编排引擎与主循环
├── strategy.py         # Strategy / SignalStrategy 基类
├── lineroot/linebuffer/lineseries/lineiterator.py  # Line 系统
├── metabase.py / parameters.py                     # 无元类对象 + 参数系统
├── indicator/analyzer/observer/sizer.py            # 组件基类
├── broker.py / order.py / trade.py / position.py   # 执行
├── feed.py / resamplerfilter.py                    # 数据
├── indicators/ analyzers/ observers/ feeds/ brokers/ filters/ sizers/ stores/
├── channels/ events.py    # tick 级事件流
├── plot/ bokeh/ reports/  # 可视化与报告
└── utils/                 # 工具（含 log_message 日志入口）
```

更细的目录树见 `.kiro/steering/structure.md`。
