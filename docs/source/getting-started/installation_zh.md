- --

title: 安装指南
description: 如何安装和设置 Backtrader

- --

# 安装指南

## 系统要求

- Python 3.8 或更高版本 (测试至 3.13)
- pip 包管理器

## 安装方法（从源码安装）

> **注意**：本项目未发布到 PyPI，请从源码安装。

### 从 GitHub 安装（推荐）

```bash
git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader
pip install -r requirements.txt
pip install -U .

```bash

### 从 Gitee 镜像安装（国内用户推荐）

```bash
git clone <https://gitee.com/yunjinqi/backtrader.git>
cd backtrader
pip install -r requirements.txt
pip install -U .

```bash

### 开发模式安装

如需修改源代码：

```bash
git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader
pip install -r requirements.txt
pip install -e .

```bash

## 依赖项

### 核心依赖

这些会自动安装：

```bash
pandas>=1.3.0
numpy>=1.20.0
matplotlib>=3.3.0
python-dateutil>=2.8.0
pytz>=2021.1

```bash

### 可选依赖

#### 可视化

```bash

# 使用 Plotly 进行交互式绘图

pip install plotly>=5.0.0

# 使用 Pyecharts 进行 Web 图表

pip install pyecharts>=1.9.0

```bash

#### 实盘交易

```bash

# CCXT 用于加密货币交易所

pip install ccxt

# CTP 用于期货交易 (中国)

pip install ctp-python

```bash

#### 开发

```bash

# 安装开发依赖

pip install -r requirements.txt

```bash

## 验证安装

```python
import backtrader as bt

print(f"Backtrader 版本: {bt.__version__}")
print("安装成功！")

```bash

## 开发环境设置

贡献者请参阅 [开发者指南](/developer-guide/setup.md)。

## 故障排除

### 导入错误

如果遇到导入错误，请确保 Python 版本正确：

```bash
python --version  # 应该是 3.8+

```bash

### 绘图问题

macOS 上的 matplotlib 问题：

```bash
pip install python.app

```bash
对于无头环境，使用 Agg 后端：

```python
import matplotlib
matplotlib.use('Agg')

```bash

### 网络问题 (中国用户)

如果依赖包安装缓慢，可以使用国内 pip 镜像：

```bash
pip install -i <https://pypi.tuna.tsinghua.edu.cn/simple> -r requirements.txt

```bash

## 下一步

- [快速开始教程](quickstart.md) - 创建您的第一个策略
- [基本概念](concepts.md) - 理解核心概念
- [数据源](data-feeds.md) - 加载市场数据
