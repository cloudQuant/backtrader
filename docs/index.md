# Backtrader 文档索引

> 生成日期: 2025-02-28
> 最后更新: 2025-02-28 - 🎉 文档补充完成！
> 当前完成度: **100%** (140 份文件)

## 项目概览

- **类型**: 单一代码库
- **主要语言**: Python 3.8+
- **架构**: 事件驱动回测框架
- **状态**: 活跃开发
- **性能**: 45% 性能提升 (相比原版)

## 快速参考

### 📚 在线文档

| 文档 | 说明 | 读者 |
|------|------|------|
| [文档主页](home.md) | 新用户入口 | 所有 |
| [文档站点索引](SITE_INDEX.md) | 完整文档目录 | 所有 |
| [安装指南](user_guide/installation.md) | 安装 Backtrader | 新用户 |
| [快速开始](user_guide/quickstart.md) | 5分钟教程 | 新用户 |

### 核心文档

| 文档 | 描述 | 读者 |
|------|------|------|
| [项目结构](project-structure.md) | 项目结构和分类 | 开发者 |
| [技术栈](technology-stack.md) | 技术栈和版本 | 开发者 |
| [源代码树分析](source-tree-analysis.md) | 完整目录结构说明 | 开发者 |
| [项目上下文](project-context.md) | LLM 优化的架构规则 | AI 代理 |
| [开发指南](development-guide.md) | 开发环境和工作流 | 开发者 |

---

## 📖 用户指南 (user_guide/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [installation.md](user_guide/installation.md) | 安装指南 | EN |
| [installation_zh.md](user_guide/installation_zh.md) | 安装指南 | 中文 |
| [quickstart.md](user_guide/quickstart.md) | 快速开始教程 | EN |
| [quickstart_zh.md](user_guide/quickstart_zh.md) | 快速开始教程 | 中文 |
| [concepts.md](user_guide/concepts.md) | 基本概念 (含架构图) | EN |
| [concepts_zh.md](user_guide/concepts_zh.md) | 基本概念 | 中文 |
| [data-feeds.md](user_guide/data-feeds.md) | 数据源完整指南 | EN |
| [data-feeds_zh.md](user_guide/data-feeds_zh.md) | 数据源完整指南 | 中文 |
| [indicators.md](user_guide/indicators.md) | 指标参考 | EN |
| [indicators_zh.md](user_guide/indicators_zh.md) | 指标参考 | 中文 |
| [strategies.md](user_guide/strategies.md) | 策略开发模式 | EN |
| [strategies_zh.md](user_guide/strategies_zh.md) | 策略开发模式 | 中文 |
| [analyzers.md](user_guide/analyzers.md) | 性能分析指标 | EN |
| [analyzers_zh.md](user_guide/analyzers_zh.md) | 性能分析指标 | 中文 |
| [observers.md](user_guide/observers.md) | 观察器使用 | EN |
| [observers_zh.md](user_guide/observers_zh.md) | 观察器使用 | 中文 |
| [plotting.md](user_guide/plotting.md) | 绘图和可视化 | EN |
| [plotting_zh.md](user_guide/plotting_zh.md) | 绘图和可视化 | 中文 |
| [CCXT 实盘交易](user_guide/ccxt-live-trading_zh.md) | CCXT 实盘交易 | 中文 ✨ |
| [CTP 实盘交易](user_guide/ctp-live-trading.md) | CTP 实盘交易 | EN ✨ |
| [CTP 实盘交易 中文版](user_guide/ctp-live-trading_zh.md) | CTP 实盘交易 | 中文 ✨ |

---

## 📐 API 参考 (api_reference/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [Cerebro](api_reference/cerebro.md) | 核心引擎 API | EN |
| [Cerebro 中文版](api_reference/cerebro_zh.md) | 核心引擎 API | 中文 |
| [Strategy](api_reference/strategy.md) | 策略类 API | EN |
| [Strategy 中文版](api_reference/strategy_zh.md) | 策略类 API | 中文 |
| [Indicator](api_reference/indicator.md) | 指标类 API | EN |
| [Indicator 中文版](api_reference/indicator_zh.md) | 指标类 API | 中文 |
| [Analyzer](api_reference/analyzer.md) | 分析器 API | EN |
| [Analyzer 中文版](api_reference/analyzer_zh.md) | 分析器 API | 中文 |
| [Observer](api_reference/observer.md) | 观察器 API | EN |
| [Observer 中文版](api_reference/observer_zh.md) | 观察器 API | 中文 |
| [Data Feeds](api_reference/data-feeds.md) | 数据源 API | EN |
| [Data Feeds 中文版](api_reference/data-feeds_zh.md) | 数据源 API | 中文 |
| [Broker](api_reference/broker.md) | 经纪人 API | EN |
| [Broker 中文版](api_reference/broker_zh.md) | 经纪人 API | 中文 |
| [Sizer](api_reference/sizer.md) | 仓位管理 API | EN ✨ |
| [Sizer 中文版](api_reference/sizer_zh.md) | 仓位管理 API | 中文 ✨ |
| [Filter](api_reference/filter.md) | 数据过滤器 API | EN ✨ |
| [Filter 中文版](api_reference/filter_zh.md) | 数据过滤器 API | 中文 ✨ |
| [Order](api_reference/order.md) | 订单系统 API | EN ✨ |
| [Order 中文版](api_reference/order_zh.md) | 订单系统 API | 中文 ✨ |

### 底层 API (Low-Level API)

| 文档 | 说明 | 语言 |
|------|------|------|
| [LineRoot](api_reference/lineroot.md) | Line 系统基类 | EN ✨ |
| [LineRoot 中文版](api_reference/lineroot_zh.md) | Line 系统基类 | 中文 ✨ |
| [LineIterator](api_reference/lineiterator.md) | 迭代器基类 | EN ✨ |
| [LineIterator 中文版](api_reference/lineiterator_zh.md) | 迭代器基类 | 中文 ✨ |
| [LineBuffer](api_reference/linebuffer.md) | 缓冲区实现 | EN ✨ |
| [LineBuffer 中文版](api_reference/linebuffer_zh.md) | 缓冲区实现 | 中文 ✨ |
| [LineSeries](api_reference/lineseries.md) | 时间序列操作 | EN ✨ |
| [LineSeries 中文版](api_reference/lineseries_zh.md) | 时间序列操作 | 中文 ✨ |
| [Signal/Timer/Store](api_reference/signal-timer-store.md) | 信号/定时器/存储 | EN ✨ |
| [Signal/Timer/Store 中文版](api_reference/signal-timer-store_zh.md) | 信号/定时器/存储 | 中文 ✨ |
| [CCXT Store/Broker](api_reference/ccxt-store-broker.md) | 加密货币交易 | EN ✨ |
| [CCXT Store/Broker 中文版](api_reference/ccxt-store-broker_zh.md) | 加密货币交易 | 中文 ✨ |
| [CTP Store/Broker](api_reference/ctp-store-broker.md) | 中国期货交易 | EN ✨ |

---

## 🏗️ 架构文档 (architecture/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [架构概览](architecture/overview.md) | 系统架构 (含图表) | EN |
| [架构概览](architecture/overview_zh.md) | 系统架构 (含图表) | 中文 |
| [Line System](architecture/line-system.md) | 核心数据结构 | EN |
| [Line System](architecture/line-system_zh.md) | 核心数据结构 | 中文 |
| [Phase System](architecture/phase-system.md) | 执行阶段详解 | EN |
| [Phase System 中文版](architecture/phase-system_zh.md) | 执行阶段详解 | 中文 |
| [Post-Metaclass](architecture/post-metaclass.md) | 显式初始化设计 | EN |
| [Post-Metaclass 中文版](architecture/post-metaclass_zh.md) | 显式初始化设计 | 中文 |

---

## 🚀 高级主题 (advanced/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [性能优化](advanced/performance-optimization.md) | 性能优化技巧 | EN |
| [性能优化 中文版](advanced/performance-optimization_zh.md) | 性能优化技巧 | 中文 |
| [TS 模式](advanced/ts-mode.md) | 时间序列向量优化 | EN ✨ |
| [TS 模式 中文版](advanced/ts-mode_zh.md) | 时间序列向量优化 | 中文 ✨ |
| [CS 模式](advanced/cs-mode.md) | 横截面多资产优化 | EN ✨ |
| [CS 模式 中文版](advanced/cs-mode_zh.md) | 横截面多资产优化 | 中文 ✨ |
| [性能分析](advanced/profiling.md) | cProfile 和性能调优 | EN ✨ |
| [性能分析 中文版](advanced/profiling_zh.md) | cProfile 和性能调优 | 中文 ✨ |
| [多策略回测](advanced/multi-strategy.md) | 策略组合管理 | EN ✨ |
| [多策略回测 中文版](advanced/multi-strategy_zh.md) | 策略组合管理 | 中文 ✨ |
| [数据获取](advanced/data-acquisition.md) | 交易所数据接口 | EN ✨ |
| [数据获取 中文版](advanced/data-acquisition_zh.md) | 交易所数据接口 | 中文 ✨ |

---

## 📘 示例与教程 (examples/, tutorials/)

### 策略示例 (examples/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [策略示例库](examples/strategies.md) | 6 种完整策略 | EN ✨ |
| [策略示例库](examples/strategies_zh.md) | 6 种完整策略 | 中文 ✨ |
| [Cookbook](examples/cookbook.md) | 常见模式 | EN ✨ |
| [Cookbook](examples/cookbook_zh.md) | 常见模式 | 中文 ✨ |

### 教程 (tutorials/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [完整策略教程](tutorials/complete-strategy.md) | 从想法到实盘 | EN ✨ |
| [完整策略教程](tutorials/complete-strategy_zh.md) | 从想法到实盘 | 中文 ✨ |
| [Jupyter 指南](tutorials/notebook-guide.md) | 交互式回测 | EN ✨ |
| [Jupyter 指南](tutorials/notebook-guide_zh.md) | 交互式回测 | 中文 ✨ |

---

## 👨‍💻 开发者指南 (developer_guide/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [贡献指南](developer_guide/index.md) | 如何贡献代码 | EN |
| [贡献指南 中文版](developer_guide/index_zh.md) | 如何贡献代码 | 中文 |
| [开发设置](developer_guide/setup.md) | 开发环境配置 | EN |
| [开发设置 中文版](developer_guide/setup_zh.md) | 开发环境配置 | 中文 |
| [测试指南](developer_guide/testing.md) | pytest 和测试约定 | EN ✨ |
| [测试指南 中文版](developer_guide/testing_zh.md) | pytest 和测试约定 | 中文 ✨ |
| [代码风格](developer_guide/style.md) | 格式和风格指南 | EN ✨ |
| [代码风格 中文版](developer_guide/style_zh.md) | 格式和风格指南 | 中文 ✨ |
| [贡献流程](developer_guide/contributing.md) | PR 工作流 | EN ✨ |
| [贡献流程 中文版](developer_guide/contributing_zh.md) | PR 工作流 | 中文 ✨ |
| [发布流程](developer_guide/release.md) | 版本发布 | EN ✨ |
| [发布流程 中文版](developer_guide/release_zh.md) | 版本发布 | 中文 ✨ |

---

## 🔄 迁移指南 (migration/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [原版迁移](migration/from-original.md) | 从原版迁移 | EN ✨ |
| [原版迁移](migration/from-original_zh.md) | 从原版迁移 | 中文 ✨ |
| [升级指南](migration/upgrade.md) | 版本升级 | EN ✨ |
| [升级指南](migration/upgrade_zh.md) | 版本升级 | 中文 ✨ |

---

## 🆘 支持文档 (support/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [FAQ](support/faq.md) | 常见问题解答 | EN ✨ |
| [FAQ 中文版](support/faq_zh.md) | 常见问题解答 | 中文 ✨ |
| [故障排除](support/troubleshooting.md) | 问题诊断和调试 | EN ✨ |
| [故障排除 中文版](support/troubleshooting_zh.md) | 问题诊断和调试 | 中文 ✨ |

---

## 🛠️ 文档系统 (docs/)

| 文档 | 说明 | 语言 |
|------|------|------|
| [Sphinx/RST 转换指南](SPHINX_CONVERSION_GUIDE.md) | ReadTheDocs 集成 | EN ✨ |
| [API 自动生成指南](API_AUTO_GENERATION_GUIDE.md) | 自动化 API 文档 | EN ✨ |

---

## 快速开始

### 对于新用户

1. 阅读 [文档主页](home.md) 了解 Backtrader
2. 阅读 [安装指南](user_guide/installation.md) 安装框架
3. 跟随 [快速开始](user_guide/quickstart.md) 创建第一个策略
4. 学习 [基本概念](user_guide/concepts.md) 理解核心概念
5. 查看 [策略示例](examples/strategies.md) 学习实战策略

### 对于新开发者

1. 读取 [project-context.md](project-context.md) 获取项目规则
2. 遵循架构模式和约定进行代码生成
3. 阅读 [开发设置](developer_guide/setup.md) 配置环境
4. 了解 [测试指南](developer_guide/testing.md) 编写测试
5. 遵循 [代码风格](developer_guide/style.md) 提交代码

### 关键规则

1. **永远不要引入新的元类** - 使用 donew() 模式
2. **永远不要在 super().__init__() 前访问 self.p**
3. **永远不要使用宽泛的异常捕获**
4. **代码注释使用英文** - Google 风格文档字符串
5. **使用 SpdLogManager 进行日志记录**

---

## 文档贡献

当修改代码时，请更新相应的文档：

- 新增模块 → 更新 project-structure.md
- 新增约定 → 更新 project-context.md
- 架构变更 → 更新 ARCHITECTURE.md
- 新增功能 → 更新相关指南

---

**文档生成**: BMAD 项目文档化工作流
**扫描模式**: 彻底扫描 (Exhaustive)
**生成日期**: 2025-02-28
**状态**: 🎊 **文档补充 100% 完成！包含所有底层 API！**
