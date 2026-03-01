# Backtrader 优化需求文档索引

本目录包含 204 份优化需求和分析文档，按类别组织如下。

## 📚 文档分类

### 1. 性能优化 (Performance Optimization)

#### 核心性能分析

- [`performance_analysis_report.md`](performance_analysis_report.md) - 性能分析报告
- [`performance_optimization_summary.md`](performance_optimization_summary.md) - 性能优化总结
- [`性能优化 TODO 清单.md`](性能优化 TODO 清单.md) - 性能优化待办清单
- [`性能差异分析报告.md`](性能差异分析报告.md) - 性能差异分析

#### 性能分析工具

- [`performance_analysis_guide.md`](performance_analysis_guide.md) - 性能分析指南

### 2. 架构设计 (Architecture Design)

#### Tick 级别架构

- [`TICK_LEVEL_ARCHITECTURE_DESIGN.md`](TICK_LEVEL_ARCHITECTURE_DESIGN.md) - Tick 级别架构设计
- [`TICK_LEVEL_ARCHITECTURE_IMPROVEMENTS.md`](TICK_LEVEL_ARCHITECTURE_IMPROVEMENTS.md) - Tick 级别架构改进
- [`TICK_LEVEL_DESIGN_PART2.md`](TICK_LEVEL_DESIGN_PART2.md) - Tick 级别设计第二部分

#### 元类移除

- [`metaclass_removal_implementation_guide.md`](metaclass_removal_implementation_guide.md) - 元类移除实施指南

### 3. 实盘交易优化 (Live Trading)

- [`LIVE_TRADING_OPTIMIZATION.md`](LIVE_TRADING_OPTIMIZATION.md) - 实盘交易优化

### 4. 代码质量 (Code Quality)

- [`CODE_QUALITY_GUIDE.md`](CODE_QUALITY_GUIDE.md) - 代码质量指南
- [`bugs_report.md`](bugs_report.md) - Bug 报告
- [`backtrader_codebase_analysis_comprehensive.md`](backtrader_codebase_analysis_comprehensive.md) - 代码库综合分析

### 5. 特定问题分析 (Specific Issues)

- [`sharpe_ratio_difference_analysis.md`](sharpe_ratio_difference_analysis.md) - 夏普率差异分析
- [`夏普率不一致分析报告.md`](夏普率不一致分析报告.md) - 夏普率不一致分析报告（中文）

### 6. 需求文档 (Requirements)

- [`需求 11.md`](需求 11.md) - 需求 11
- [`需求 11 完成总结.md`](需求 11 完成总结.md) - 需求 11 完成总结
- [`格式优化需求.md`](格式优化需求.md) - 格式优化需求
- [`优化画图展示功能.md`](优化画图展示功能.md) - 优化画图展示功能

### 7. 优化需求迭代 (Optimization Iterations)

位于 `优化需求/` 子目录，包含 169 个迭代文档：

#### 按主题分类

- *基础设施优化**
- 迭代 1-20: 基础框架优化
- 迭代 21-40: 数据处理优化
- 迭代 41-60: 策略系统优化

- *功能增强**
- 迭代 61-80: 指标系统增强
- 迭代 81-100: 实盘交易功能
- 迭代 101-120: 文档和测试

- *高级特性**
- 迭代 121-140: 性能调优
- 迭代 141-160: 架构重构
- 迭代 161-169: 最新优化

#### 重点迭代文档

- *项目文档化**
- [`优化需求/迭代 43-优化注释形成项目文档.md`](优化需求/迭代 43-优化注释形成项目文档.md)
- [`优化需求/迭代 116-生成项目文档-完成.md`](优化需求/迭代 116-生成项目文档-完成.md)

- *CCXT 集成**
- [`优化需求/迭代 94-基于 ccxt-store 优化.md`](优化需求/迭代 94-基于 ccxt-store 优化.md)
- [`优化需求/迭代 84-基于 backtrader_binance 优化.md`](优化需求/迭代 84-基于 backtrader_binance 优化.md)

- *策略优化**
- [`优化需求/迭代 90-基于 trading-strategy-optimizer 优化.md`](优化需求/迭代 90-基于 trading-strategy-optimizer 优化.md)
- [`优化需求/迭代 111-基于 signal_trading 优化.md`](优化需求/迭代 111-基于 signal_trading 优化.md)

- *UI 和可视化**
- [`优化需求/迭代 99-基于 BackTraderUI 优化.md`](优化需求/迭代 99-基于 BackTraderUI 优化.md)

- *综合改进**
- [`优化需求/迭代 113-后续改进综合方案.md`](优化需求/迭代 113-后续改进综合方案.md)

### 8. 用户指南 (User Guides)

位于 `user_guide/` 子目录，包含 8 个用户指南文档。

### 9. 待办事项 (TODOs)

位于 `todos/` 子目录，包含 4 个待办事项文档。

### 10. 入门指南 (Getting Started)

位于 `getting_started/` 子目录，包含 2 个入门文档。

## 🔍 快速查找

### 按问题类型查找

- *性能问题**
- 查看 [`performance_analysis_report.md`](performance_analysis_report.md)
- 参考 [`性能优化 TODO 清单.md`](性能优化 TODO 清单.md)

- *架构问题**
- 查看 [`TICK_LEVEL_ARCHITECTURE_DESIGN.md`](TICK_LEVEL_ARCHITECTURE_DESIGN.md)
- 参考 [`metaclass_removal_implementation_guide.md`](metaclass_removal_implementation_guide.md)

- *实盘交易问题**
- 查看 [`LIVE_TRADING_OPTIMIZATION.md`](LIVE_TRADING_OPTIMIZATION.md)
- 参考 CCXT 相关迭代文档

- *代码质量问题**
- 查看 [`CODE_QUALITY_GUIDE.md`](CODE_QUALITY_GUIDE.md)
- 参考 [`bugs_report.md`](bugs_report.md)

### 按开发阶段查找

- *规划阶段**
- 查看 `todos/` 目录
- 参考需求文档

- *实施阶段**
- 查看优化需求迭代文档
- 参考实施指南

- *测试阶段**
- 查看性能分析报告
- 参考 Bug 报告

- *部署阶段**
- 查看实盘交易优化文档
- 参考用户指南

## 📊 统计信息

- **总文档数**: 204 份
- **优化迭代**: 169 个
- **主题分类**: 10 个
- **语言**: 中英文双语
- **最后更新**: 2026-03-01

## 🔗 相关资源

- [主文档目录](../README.md)
- [API 参考](/api/)
- [用户指南](../user_guide/)
- [开发者指南](../developer_guide/)

## 📝 使用建议

1. **新手**: 从 `getting_started/` 开始
2. **开发者**: 查看 `CODE_QUALITY_GUIDE.md` 和优化需求文档
3. **性能调优**: 参考性能分析系列文档
4. **架构理解**: 阅读架构设计文档
5. **问题排查**: 查看 bugs_report.md 和相关分析文档

## 🤝 贡献

如需添加新的优化需求或分析文档：

1. 遵循现有文档格式
2. 使用清晰的文件命名
3. 更新本索引文件
4. 提交 Pull Request

- --

- *维护者**: Backtrader 开发团队
- *创建日期**: 2026-03-01
- *版本**: 1.0
