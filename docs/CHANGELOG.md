# 更新日志 (Changelog)

本文档记录 backtrader 项目的重要变更。

---

## [未发布] - 2024-10-14

### 修复 (Fixed)

#### 🔧 修复 indicators 模块 PyCharm 警告问题

**问题描述**：
在 PyCharm 中，`backtrader/indicators/` 文件夹的许多指标类显示 "Unresolved reference" 警告，如 ATR、RSI、MACD 等 50+ 个指标。

**根本原因**：
`backtrader/indicators/__init__.py` 使用 `from .module import *` 导入方式，但未定义 `__all__` 变量，导致 IDE 静态分析无法确定导出的类。

**解决方案**：
- 在 `backtrader/indicators/__init__.py` 末尾添加显式的 `__all__` 导出列表
- 包含 118 个指标类和别名
- 保持向后兼容，不影响现有代码

**修改文件**：
- `backtrader/indicators/__init__.py` - 添加 `__all__` 列表（+122 行）

**测试结果**：
- ✅ 所有 68 个指标测试通过
- ✅ 导入功能正常
- ✅ PyCharm 正确识别所有导出类
- ✅ 支持完整的代码补全和类型提示

**导出的指标包括**：
- 趋势指标：SMA, EMA, WMA, DEMA, TEMA, HMA, KAMA, ZLEMA 等
- 震荡指标：RSI, MACD, Stochastic, CCI, Williams %R, RMI 等
- 波动率指标：ATR, Bollinger Bands, True Range 等
- 动量指标：Momentum, ROC, TSI, KST 等
- 其他指标：Aroon, Ichimoku, PSAR, Vortex, DPO 等

**影响范围**：
- 仅影响 IDE 类型检查和代码补全
- 运行时行为完全不变
- 完全向后兼容

**提交信息**：
```
commit 32217b0
fix: 为indicators模块添加显式__all__导出列表

解决PyCharm中'Unresolved reference'警告问题
```

---

### 文档 (Documentation)

#### 📚 优化项目文档

**修改文件**：
- `CLAUDE.md` - 基于源代码深度阅读，重写开发者文档
- `README.md` - 完善双语（中英文）用户文档

**主要改进**：
1. **CLAUDE.md 优化**：
   - 修正不准确的描述（移除不存在的 Cython 优化和向量化回测框架信息）
   - 添加完整的核心组件说明（Cerebro、Strategy、Brokers、Feeds 等）
   - 详细的目录结构和架构说明
   - 50+ 技术指标完整列表
   - 各类经纪商和数据源的具体说明
   - 开发指南、常见问题和性能优化建议

2. **README.md 优化**：
   - 完善双语支持（中英文）
   - 添加详细的功能模块说明
   - 提供可直接运行的完整代码示例
   - 多时间周期分析示例
   - CCXT 加密货币交易示例
   - 参数优化示例
   - 资金费率回测说明

**提交信息**：
```
commit 70054be
docs: 优化CLAUDE.md和README.md文档内容
```

---

## 版本历史

### 当前版本：1.9.76.123

**支持的 Python 版本**：
- Python 3.8
- Python 3.9
- Python 3.10
- Python 3.11
- Python 3.12
- Python 3.13

**主要特性**：
- 🚀 事件驱动回测引擎
- 🪙 CCXT 集成（100+ 加密货币交易所）
- 🏦 多市场支持（股票、期货、外汇、加密货币）
- 📈 50+ 技术指标
- 📊 性能分析器（夏普比率、最大回撤等）
- 🎯 灵活的订单类型
- 💼 仓位管理系统

**已知问题**：
- 无

---

## 贡献指南

如需贡献代码或报告问题，请参阅：
- [CLAUDE.md](../CLAUDE.md) - 开发者指南
- [README.md](../README.md) - 项目文档
- [Issue Tracker (Gitee)](https://gitee.com/yunjinqi/backtrader/issues)
- [Issue Tracker (GitHub)](https://github.com/cloudQuant/backtrader/issues)

---

## 许可证

本项目基于 GNU General Public License v3.0 开源。

---

**维护者**：cloudQuant (yunjinqi@qq.com)

