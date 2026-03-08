---
title: 开发环境设置
description: 设置开发环境

---
# 开发环境设置

本指南介绍如何设置 Backtrader 开发环境。

## 前置条件

- Python 3.8 或更高版本
- Git
- pip

## 克隆仓库

```bash
git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader

```
或使用 Gitee 镜像 (中国用户):

```bash
git clone <https://gitee.com/yunjinqi/backtrader.git>
cd backtrader

```

## 安装开发依赖

```bash

# 安装依赖

pip install -r requirements.txt

# 以开发模式安装

pip install -e .

```

## 开发命令

### 测试

```bash

# 运行所有测试

pytest tests/ -v

# 运行特定测试文件

pytest tests/strategies/test_signals.py -v

# 并行运行

pytest tests/ -n 4 -v

# 带覆盖率

pytest tests/ -m "not integration" --cov=backtrader

```

### 代码质量

```bash

# 格式化代码

bash scripts/optimize_code.sh

# 或单独执行各步骤

pyupgrade --py38-plus backtrader/
isort backtrader/
black --line-length 124 backtrader/
ruff check --fix backtrader/

```

### 类型检查

```bash

# 运行 mypy

mypy backtrader/

# 或使用 make 目标

make type-check

```

### 文档

```bash

# 生成文档

make docs

# 查看文档

make docs-view

```

## 项目结构

```bash
backtrader/
├── backtrader/           # 主包

│   ├── core/            # 核心类

│   ├── indicators/      # 技术指标

│   ├── observers/       # 观察器

│   ├── analyzers/       # 性能分析器

│   ├── feeds/           # 数据源

│   ├── brokers/         # 经纪人实现

│   ├── stores/          # 数据存储

│   └── utils/           # 工具

├── tests/                # 测试套件

│   ├── original_tests/
│   ├── add_tests/
│   └── strategies/
├── docs/                 # 文档

├── scripts/              # 实用脚本

└── tools/                # 开发工具

```

## Git 工作流

### 分支

- `dev` - 活跃开发
- `master` - 稳定发布
- `development` - 主分支

### 提交格式

遵循约定式提交：

```bash
<type>: <description>

[可选正文]

```
类型: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`

### 创建 Pull Request

1. Fork 并从 `dev` 创建分支
2. 进行更改
3. 确保测试通过
4. 提交 PR 到 `dev` 分支

## 测试您的更改

### 单元测试

```python

# tests/test_my_feature.py

import backtrader as bt
import pytest

def test_my_feature():
    cerebro = bt.Cerebro()

# ... 设置
    result = cerebro.run()
    assert result is not None

```

### 集成测试

```python
@pytest.mark.integration
def test_live_connection():

# 需要 testnet 凭证
    pass

```

### 运行特定测试

```bash

# 指标测试

pytest tests/indicators/test_sma.py

# 策略测试

pytest tests/strategies/test_signals.py

# 使用标记

pytest tests/ -m "priority_p0"  # 仅关键测试

pytest tests/ -m "not integration"  # 跳过集成测试

```

## 代码风格指南

### 格式化

- **行长度**: 124 字符
- **格式化工具**: Black
- **导入顺序**: isort (Black 配置)

### 类型提示

```python
def calculate_sma(period: int, data: list) -> float:
    """计算简单移动平均线。

    Args:
        period: 周期数。
        data: 输入数据序列。

    Returns:
        计算的 SMA 值。
    """
    pass

```

### 注释

- 代码注释使用英文
- Google 风格文档字符串
- 解释"为什么"，而不是"什么"

## 开发技巧

### 使用 pdb

```python
import pdb

def next(self):
    pdb.set_trace()

# 您的代码

```

### 日志记录

```python
from backtrader.utils import SpdLogManager

logger = SpdLogManager().get_logger(__name__)
logger.info('策略已初始化')

```

### 快速测试

```python

# 快速测试脚本

if __name__ == '__main__':
    cerebro = bt.Cerebro()

# ... 设置
    cerebro.run()
    cerebro.plot()

```

## Cython 编译

对于性能关键的开发，编译 Cython 扩展：

```bash

# Unix/Mac

cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .

# Windows

cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U .

```

## 常见问题

### 导入错误

确保 Python 版本正确：

```bash
python --version  # 应该是 3.8+

```

### 测试失败

清理并重新安装：

```bash
pip uninstall backtrader
pip install -e .

```

### 绘图问题 (macOS)

```bash
pip install python.app

```

## 另请参阅

- [测试](testing.md)
- [代码风格](style.md)
- [贡献](contributing.md)
