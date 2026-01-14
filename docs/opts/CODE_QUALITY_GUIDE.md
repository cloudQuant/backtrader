# Backtrader 代码质量指南

## 快速开始

### 安装工具

```bash
pip install pyupgrade ruff black pre-commit
```

### 运行优化

```bash
# 方法 1: 使用提供的脚本
bash optimize_code.sh

# 方法 2: 手动运行
python -m pyupgrade --py311-plus backtrader/**/*.py
python -m ruff format backtrader/ --line-length 100
python -m ruff check backtrader/ --fix
```

### 设置 Pre-commit 钩子

```bash
pre-commit install
pre-commit run --all-files
```

## 代码风格规范

### 1. 行长限制

- **最大行长**: 100 字符
- **例外**: 长 URL、导入语句可以超过限制

```python
# ✅ 好的
result = some_function(arg1, arg2, arg3,
                       arg4, arg5)

# ❌ 不好的
result = some_function(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9, arg10)
```

### 2. 导入语句

```python
# ✅ 好的
import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd

from backtrader import Indicator
from backtrader.utils import date2num

# ❌ 不好的
from backtrader import *
import backtrader as bt
from . import *
```

### 3. 变量命名

```python
# ✅ 好的
for line in lines:
    process(line)

counter = 0
result_list = []

# ❌ 不好的
for l in lines:  # 容易与 1 混淆
    process(l)

c = 0  # 不清楚含义
res = []  # 缩写不清楚
```

### 4. 异常处理

```python
# ✅ 好的
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
except Exception:
    logger.error("Unknown error occurred")

# ❌ 不好的
try:
    result = risky_operation()
except:  # 捕获所有异常，不推荐
    pass
```

### 5. 字符串

```python
# ✅ 好的（使用双引号）
message = "Hello, world!"
formatted = f"Value: {value}"

# ❌ 不好的（混合使用）
message = 'Hello, world!'
formatted = 'Value: {}'.format(value)
```

### 6. 注释

```python
# ✅ 好的
# 计算移动平均线
ma = calculate_moving_average(data, period=20)

# ❌ 不好的
# 计算 MA
ma = calculate_moving_average(data, period=20)

# 多余的注释
x = 1  # 设置 x 为 1
```

## 常见问题修复

### 问题 1: 长行需要换行

```python
# ❌ 原始代码
result = some_function(argument1, argument2, argument3, argument4, argument5)

# ✅ 修复后
result = some_function(
    argument1, argument2, argument3, argument4, argument5
)
```

### 问题 2: 不一致的缩进

```python
# ❌ 原始代码
def function():
  x = 1  # 2 个空格
    y = 2  # 4 个空格

# ✅ 修复后
def function():
    x = 1  # 4 个空格
    y = 2  # 4 个空格
```

### 问题 3: 未使用的导入

```python
# ❌ 原始代码
import os
import sys
from typing import Dict

x = 1  # 没有使用 os, sys, Dict

# ✅ 修复后
x = 1
```

### 问题 4: 过时的语法

```python
# ❌ 原始代码
class MyClass(object):  # Python 3 不需要显式继承 object
    pass

# ✅ 修复后
class MyClass:
    pass
```

## 工具使用指南

### pyupgrade

自动升级 Python 语法到更新的版本。

```bash
# 升级到 Python 3.11+
python -m pyupgrade --py311-plus backtrader/**/*.py

# 查看将要进行的更改（不实际修改）
python -m pyupgrade --py311-plus --diff backtrader/**/*.py
```

### ruff

高性能的 linter 和格式化工具。

```bash
# 检查代码问题
python -m ruff check backtrader/

# 自动修复问题
python -m ruff check backtrader/ --fix

# 格式化代码
python -m ruff format backtrader/ --line-length 100

# 查看将要进行的更改
python -m ruff format backtrader/ --diff
```

### black

代码格式化工具（可选，ruff format 已足够）。

```bash
# 格式化代码
python -m black backtrader/ --line-length 100

# 检查格式
python -m black backtrader/ --check
```

## 测试和验证

### 运行单元测试

```bash
# 运行所有测试
pytest tests/add_tests/

# 运行特定测试
pytest tests/add_tests/test_ind_basicops.py

# 显示覆盖率
pytest tests/add_tests/ --cov=backtrader
```

### 检查代码质量

```bash
# 运行所有检查
bash optimize_code.sh

# 或分别运行
python -m pyupgrade --py311-plus backtrader/**/*.py
python -m ruff format backtrader/ --line-length 100
python -m ruff check backtrader/ --fix
```

## 最佳实践

### 1. 定期更新工具

```bash
pip install --upgrade pyupgrade ruff black
```

### 2. 使用 Pre-commit 钩子

```bash
# 安装
pre-commit install

# 运行（自动在提交前）
pre-commit run --all-files
```

### 3. 在 CI/CD 中集成

在 GitHub Actions 或其他 CI 工具中添加检查步骤。

### 4. 代码审查清单

- [ ] 代码通过 ruff 检查
- [ ] 代码通过 pyupgrade 升级
- [ ] 代码格式符合规范
- [ ] 所有测试通过
- [ ] 没有未使用的导入
- [ ] 变量名清晰明确
- [ ] 异常处理正确
- [ ] 注释清晰有用

## 常用命令速查

| 命令 | 说明 |
|------|------|
| `bash optimize_code.sh` | 运行完整优化 |
| `python -m ruff check backtrader/` | 检查代码问题 |
| `python -m ruff format backtrader/` | 格式化代码 |
| `pytest tests/add_tests/` | 运行所有测试 |
| `pre-commit run --all-files` | 运行所有 pre-commit 钩子 |

## 故障排除

### 问题: 导入排序不正确

**解决方案**: 使用 ruff 的 isort 功能

```bash
python -m ruff check backtrader/ --select I --fix
```

### 问题: 格式化后仍有错误

**解决方案**: 运行完整的优化流程

```bash
bash optimize_code.sh
```

### 问题: Pre-commit 钩子失败

**解决方案**: 检查配置文件

```bash
pre-commit validate-config
pre-commit validate-manifest
```

## 参考资源

- [PEP 8 风格指南](https://www.python.org/dev/peps/pep-0008/)
- [ruff 文档](https://docs.astral.sh/ruff/)
- [pyupgrade 文档](https://github.com/asottile/pyupgrade)
- [Pre-commit 框架](https://pre-commit.com/)

## 获取帮助

如有问题，请：

1. 查看工具的官方文档
2. 运行 `tool --help` 查看帮助信息
3. 提交 Issue 或 Pull Request

---

**最后更新**: 2024-12-10
**维护者**: Backtrader 开发团队
