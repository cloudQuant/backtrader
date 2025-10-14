# 更新日志 (Changelog)

本文档记录 backtrader 项目的重要变更。

---

## [未发布] - 2024-10-14

### 重要说明 (Important)

#### ⚠️ 确保使用项目本地版本

**问题**：
如果您遇到 `TypeError: 'int' object is not subscriptable` 错误，且错误堆栈显示 `D:\anaconda3\Lib\site-packages\backtrader\...`，说明您正在使用**pip安装的旧版本**，而非项目修复后的版本。

**解决方案**：
```bash
# 在项目根目录执行（推荐方式）
pip install -e .

# 验证安装
python -c "import backtrader; print(backtrader.__file__)"
# 应该输出：F:\source_code\backtrader\backtrader\__init__.py
```

**详细说明**：参见 [docs/INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)

---

### 修复 (Fixed)

#### 🐛 修复 ExtendPandasFeed 列索引错误导致 stdstats 报错

**问题描述**：
使用扩展的 `PandasData` 数据源时，当启用 `stdstats=True`（Cerebro的默认设置）会导致程序报错：`IndexError: index 9 is out of bounds for axis 0 with size 9`

**影响场景**：
- 使用 `ExtendPandasFeed` 添加自定义数据字段
- DataFrame 使用 `set_index('datetime')` 将时间设为索引
- 启用 stdstats（默认设置）时程序崩溃
- 用户被迫使用 `stdstats=False` 作为临时解决方案

**根本原因**：
- DataFrame 调用 `set_index('datetime')` 后，datetime 成为索引，实际数据列只剩 9 列（索引 0-8）
- 但 `ExtendPandasFeed` 的 params 中 datetime 仍定义为列0，导致后续字段索引全部错位
- 扩展字段 `convert_premium_rate` 的索引9超出了实际列数范围

**解决方案**：
- 将 `datetime` 参数设为 `None`（因为它是索引而非数据列）
- 调整所有列索引从 0 开始重新计数：
  - open: 0, high: 1, low: 2, close: 3, volume: 4
  - pure_bond_value: 5, convert_value: 6
  - pure_bond_premium_rate: 7, convert_premium_rate: 8
- 添加详细的文档说明 DataFrame 结构
- 移除强制 `stdstats=False` 的限制
- `run_test_strategy` 函数增加 `stdstats` 参数（默认 True）

**修改文件**：
- `strategies/0025_可转债双低策略/原始策略回测.py`
  - 修复 ExtendPandasFeed 的 params 定义
  - 添加详细的注释说明
  - run_test_strategy 增加 stdstats 参数
- `docs/EXTENDED_FEED_FIX.md` - 详细的修复说明和最佳实践

**测试结果**：
- ✅ 50 个数据源，stdstats=True/False 均通过
- ✅ 200 个数据源，stdstats=True/False 均通过
- ✅ 可转债策略现在可以正常使用 stdstats=True

**影响范围**：
- 仅影响使用扩展 PandasData 且 DataFrame 使用 set_index 的场景
- 标准 OHLCV 数据源不受影响
- 完全向后兼容

---

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

