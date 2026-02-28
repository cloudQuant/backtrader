---
title: 代码风格指南
description: Backtrader 的 Python 代码格式和风格约定
---

# 代码风格指南

本指南涵盖 Backtrader 项目中使用的代码格式和风格约定。遵循这些准则可以确保代码的一致性、可读性和可维护性。

## 目录

- [格式化规则](#格式化规则)
- [导入顺序约定](#导入顺序约定)
- [类型提示指南](#类型提示指南)
- [文档字符串约定](#文档字符串约定)
- [注释标准](#注释标准)
- [命名约定](#命名约定)
- [代码质量工具](#代码质量工具)
- [Pre-commit 钩子](#pre-commit-钩子)

## 格式化规则

### 行长度

- **最大行长度**: 124 字符
- **软限制**: 100 字符（为了可读性首选）
- **原因**: 在可读性和实用的数据结构定义之间取得平衡

### 缩进

- **空格**: 4 个空格（Python 标准）
- **制表符**: 永远不要使用制表符

### 尾随空格

- 不允许尾随空格
- 由 pre-commit 钩子强制执行

### 行结束符

- **Unix 风格 (LF)**: 必需
- **Windows 风格 (CRLF)**: 自动转换为 LF

### 空行

- **顶层**: 类/函数定义之间 2 个空行
- **类内部**: 方法定义之间 1 个空行
- **函数内部**: 谨慎使用空行分隔逻辑部分

### 示例

```python
# 好的：适当的间距和行长度
class MyIndicator(bt.Indicator):
    """用于演示的自定义指标。"""

    lines = ('signal',)
    params = (
        ('period', 14),
        ('threshold', 0.5),
    )

    def __init__(self):
        # 计算指标值
        self.lines.signal = bt.indicators.RSI(self.data, period=self.p.period)
```

## 导入顺序约定

### 标准顺序（isort 配置 Black 风格）

1. 标准库导入
2. 第三方库导入
3. 本地应用导入
4. 相对导入（来自当前包）

### 格式化规则

- **分组**: 各组之间用空行分隔
- **排序**: 每组内按字母顺序排序
- **行长度**: 使用 `ruff format` 进行自动换行

### 示例

```python
# 标准库
import datetime
from pathlib import Path

# 第三方库
import numpy as np
import pandas as pd

# 本地应用
from backtrader.indicators import Indicator
from backtrader.lineseries import LineSeries

# 相对导入（来自当前包）
from .utils import calculate_value
```

### 导入别名

常见库的别名约定：

```python
import backtrader as bt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
```

### 通配符导入

**避免通配符导入**，除非特定情况：

```python
# 允许在 __init__.py 中用于暴露公共 API
from .indicator import *
from .observers import *

# 永远不要在常规模块中使用
# from indicators import *  # 不好
```

## 类型提示指南

### 何时使用类型提示

**必须使用**:
- 公共 API 方法
- 复杂的函数签名
- 返回非显而易见类型的函数
- 类方法参数

**可选使用**:
- 私有方法（前缀为 `_`）
- 简单明显的情况
- 性能关键代码（类型提示有开销）

### 基本语法

```python
def calculate_sma(period: int, data: list[float]) -> float:
    """计算简单移动平均线。"""
    return sum(data[:period]) / period
```

### 常用类型

```python
from typing import Optional, List, Dict, Union, Callable

def process_data(
    data: pd.DataFrame,
    period: int = 14,
    callback: Optional[Callable[[float], None]] = None,
) -> Dict[str, float]:
    """处理数据，带有可选回调。"""
    pass
```

### Backtrader 的类型提示

```python
from backtrader import LineLike, StrategyBase

def register_indicator(
    owner: LineIterator,
    indicator: Indicator,
) -> None:
    """将指标注册到其所有者。"""
    pass
```

### 类型检查

运行 mypy 验证类型提示：

```bash
mypy backtrader/
```

## 文档字符串约定

### 风格：Google 风格

对所有公共类、方法和函数使用 Google 风格的文档字符串。

### 函数/方法文档字符串

```python
def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
    """计算相对强弱指标。

    RSI 是一种动量指标，用于衡量最近价格变化的幅度，
    以评估超买或超卖状态。

    Args:
        prices: 价格值列表。
        period: 计算周期数。默认为 14。

    Returns:
        RSI 值列表。与输入价格长度相同。

    Raises:
        ValueError: 如果周期小于 2 或价格列表为空。

    Example:
        >>> calculate_rsi([100, 102, 98, 105], period=3)
        [None, None, 50.0, 75.0]
    """
    if period < 2:
        raise ValueError(f"周期必须至少为 2，得到 {period}")
    # 实现代码...
```

### 类文档字符串

```python
class CustomIndicator(bt.Indicator):
    """用于趋势分析的自定义技术指标。

    该指标结合多个移动平均线来识别趋势方向和强度。

    Attributes:
        lines: 包含输出用的 'trend' 线。
        params: 配置参数。

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(MyStrategy)
        >>> cerebro.run()
    """
```

### 模块文档字符串

```python
"""自定义指标模块。

该模块包含扩展标准 Backtrader 指标库的
自定义技术指标。

典型用法：
    from backtrader.indicators.custom import CustomIndicator
    cerebro.addindicator(CustomIndicator)
"""
```

## 注释标准

### 语言：仅限英文

**所有代码注释必须使用英文**。这确保了国际化代码库的一致性。

```python
# 好的
# 根据价格动量计算信号
signal = self.data.close[0] - self.data.close[-1]

# 不好的
# Calculate signal based on price momentum
signal = self.data.close[0] - self.data.close[-1]
```

### 何时添加注释

**应该注释**:
- 复杂的算法
- 不明显的业务逻辑
- 针对 bug/问题 的变通方法
- 性能关键部分
- 公共 API 文档

**不应该注释**:
- 显而易见的代码（自文档化）
- 过时的信息
- 未经调整的复制粘贴代码

### 注释风格

```python
# 单行注释解释为什么，而不是做什么
# 不好：
# 计数器加一
counter += 1

# 好的：
# 在达到阈值后重置计数器以防止溢出
counter = 0 if counter >= MAX_THRESHOLD else counter + 1
```

### TODO/FIXME 注释

```python
# TODO: 添加对多时间周期的支持
# FIXME: 当数据包含 NaN 值时失败
# HACK: 针对 numpy 1.x 中上游错误的临时变通方法
# NOTE: 热路径中的性能优化机会
```

### 块注释

```python
# 以下计算实现 EMA 公式：
# EMA(today) = Value(today) * k + EMA(yesterday) * (1 - k)
# 其中 k = 2 / (period + 1)
#
# 此实现匹配 pandas.ewm() 的行为
k = 2 / (period + 1)
ema_today = current_value * k + ema_yesterday * (1 - k)
```

## 命名约定

### 通用规则

遵循 PEP 8 命名约定：

| 类型 | 约定 | 示例 |
|------|------------|---------|
| 模块 | `小写_加_下划线` | `linebuffer.py` |
| 类 | `首字母大写` | `LineIterator` |
| 函数 | `小写_加_下划线` | `calculate_sma()` |
| 方法 | `小写_加_下划线` | `get_value()` |
| 常量 | `大写_加_下划线` | `MAX_PERIOD` |
| 变量 | `小写_加_下划线` | `close_price` |
| 私有 | `_前缀_下划线` | `_internal_method()` |
| 受保护 | `__双_下划线` | `__private_attr` |

### Backtrader 特定名称

```python
# 线（输出序列）
class MyIndicator(bt.Indicator):
    lines = ('signal', 'trend')  # 小写，元组

# 参数
params = (
    ('period', 14),           # 小写
    ('use_threshold', True),
)

# 访问方式
self.p.period      # 参数访问
self.lines.signal  # 线访问
```

### 布尔值

使用 `is_` 或 `has_` 前缀表示布尔变量：

```python
is_valid = True
has_data = False
should_recalculate = True
```

### 避免单字母名称

除了循环变量和数学符号：

```python
# 好的
for index in range(len(data)):
    price = data[index]

# 可接受的
for i, price in enumerate(data):
    pass

# 不好的（含义不清）
x = calculate()
y = process(x)
```

## 代码质量工具

### pyupgrade

自动将 Python 语法升级到新版本：

```bash
# 升级到 Python 3.8+ 语法
pyupgrade --py38-plus backtrader/

# 升级到 Python 3.11+ 语法
pyupgrade --py311-plus backtrader/
```

**功能**:
- 将 `%` 格式化转换为 f-strings
- 替换 `super()` 调用
- 现代化类型提示
- 删除不必要的 `object` 继承

### ruff

快速的 Python linter 和格式化工具：

```bash
# 检查问题
ruff check backtrader/

# 自动修复问题
ruff check --fix backtrader/

# 格式化代码
ruff format backtrader/
```

**配置** (pyproject.toml):

```toml
[tool.ruff]
line-length = 121
target-version = "py38"

[tool.ruff.lint]
select = ["E", "F"]
ignore = ["E501"]  # 行长度由格式化工具处理
```

### isort

导入语句整理工具：

```bash
# 排序导入
isort backtrader/

# 只检查不修改
isort --check-only backtrader/
```

**配置** (pyproject.toml):

```toml
[tool.isort]
profile = "black"
line_length = 121
```

### mypy

静态类型检查器：

```bash
# 运行类型检查
mypy backtrader/

# 检查特定文件
mypy backtrader/indicators/sma.py
```

**配置** (pyproject.toml):

```toml
[tool.mypy]
python_version = "3.8"
warn_return_any = true
warn_unused_configs = true
check_untyped_defs = true
ignore_missing_imports = true
```

### black

代码格式化工具（注意：项目使用 ruff-format 以保持一致性）：

```bash
# 使用 Black 格式化（如果需要）
black --line-length 124 backtrader/
```

## Pre-commit 钩子

### 安装

```bash
# 安装 pre-commit 框架
pip install pre-commit

# 在你的仓库中安装钩子
pre-commit install

# 手动在所有文件上运行
pre-commit run --all-files
```

### 钩子配置

项目使用 `.pre-commit-config.yaml` 配置以下钩子：

1. **pyupgrade**: 自动升级 Python 语法
2. **ruff**: Linting 和格式化
3. **trailing-whitespace**: 删除尾随空格
4. **end-of-file-fixer**: 确保 EOF 处有换行符
5. **check-yaml/check-json**: 验证 YAML 和 JSON 文件
6. **debug-statements**: 防止提交调试器代码

### 使用 Pre-commit

```bash
# 自动：每次 git commit 时运行
git commit -m "feat: 添加新指标"

# 手动：在所有文件上运行
pre-commit run --all-files

# 在特定文件上运行
pre-commit run --files backtrader/indicators/*.py

# 跳过钩子（不推荐）
git commit --no-verify -m "WIP"
```

### Git 设置 (Makefile)

```bash
# 自动设置 git 钩子
make git-setup

# 这会创建运行以下内容的 pre-commit 钩子：
make pre-commit
```

### Pre-commit 输出

```bash
$ git commit -m "添加新功能"

Trim trailing whitespace.................................................Passed
Fix end of files.........................................................Passed
Check Yaml..............................................................Passed
pyupgrade...............................................................Passed
ruff-format............................................................Passed
ruff-lint................................................................Passed
[dev abc1234] 添加新功能
 1 file changed, 42 insertions(+)
```

## 快速参考

### 提交前检查

```bash
# 格式化和检查代码
bash scripts/optimize_code.sh

# 或手动执行
pyupgrade --py38-plus backtrader/
isort backtrader/
ruff format backtrader/
ruff check --fix backtrader/

# 运行测试
pytest tests/ -n 4 -v
```

### IDE 配置

**VS Code** (.vscode/settings.json):

```json
{
  "python.formatting.provider": "none",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliemarsh.ruff"
  },
  "ruff.lineLength": 124,
  "ruff.organizeImports": true
}
```

**PyCharm**:
- 启用 "Ruff" 插件
- 设置行长度为 124
- 启用 "保存时优化导入"

## 另请参阅

- [开发环境设置](setup_zh.md)
- [测试指南](testing.md)
- [贡献指南](contributing.md)
- [架构概览](../architecture/overview_zh.md)
