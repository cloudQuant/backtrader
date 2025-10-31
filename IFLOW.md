# backtrader 项目概述

## 项目简介

backtrader 是一个基于 Python 的量化交易回测和实盘交易框架。该项目是基于官方主流 backtrader 进行改进和扩展的版本，主要用于中低频量化投资研究。项目当前分为两个主要分支：

1. **master 分支**：与官方 backtrader 对齐，主要修复 bug 和增加部分功能
2. **dev 分支**：开发新功能，尝试将底层代码改写为 C++ 以支持高频交易

## 技术栈

- **核心语言**：Python 3.11
- **主要依赖库**：
  - pandas
  - numpy==1.26.4
  - matplotlib
  - plotly
  - cython
  - numba
  - pytest 相关测试框架
  - 金融数据和交易相关库（akshare, ctpbee 等）

## 核心架构

### 主要组件

1. **Cerebro**：核心引擎，负责管理数据、策略、指标、分析器等组件的运行
2. **Strategy**：策略基类，用户自定义交易策略需要继承此类
3. **Data Feeds**：数据源管理，支持多种数据格式的导入和处理
4. **Indicators**：技术指标库，包含大量常用技术指标
5. **Analyzers**：分析器，用于评估策略表现
6. **Observers**：观察器，用于监控交易过程
7. **Brokers**：经纪商模拟器，处理订单执行和账户管理

### 核心特性

- 支持多时间周期数据处理
- 灵活的策略编写框架
- 丰富的技术指标库
- 完整的回测分析工具
- 支持实盘交易接口（如 CTP）
- 高性能计算（通过 Cython 和 Numba 优化）

## 安装和运行

### 安装步骤

```bash
# 1. 克隆项目
git clone https://gitee.com/yunjinqi/backtrader.git

# 2. 安装依赖
pip install -r ./backtrader/requirements.txt

# 3. 编译 Cython 文件并安装（不同系统命令略有不同）
# Linux/Mac:
cd ./backtrader/backtrader && python -W ignore compile_cython_numba_files.py && cd .. && cd .. && pip install -U ./backtrader/
# Windows:
cd ./backtrader/backtrader; python -W ignore compile_cython_numba_files.py; cd ..; cd ..; pip install -U ./backtrader/

# 4. 运行测试
pytest ./backtrader/tests -n 4
```

### 运行要求

- Python 3.11（推荐）
- 相关依赖库（见 requirements.txt）
- 支持编译 Cython 扩展的环境

## 开发规范

### 代码风格

- 遵循 Python 标准编码规范
- 使用 Black 代码格式化工具（line-length = 100）
- 类型检查使用 MyPy
- 代码测试使用 Pytest 框架

### 项目结构

```
backtrader/
├── backtrader/              # 核心代码库
│   ├── __init__.py          # 包初始化文件
│   ├── cerebro.py           # 核心引擎
│   ├── strategy.py          # 策略基类
│   ├── indicators/          # 技术指标
│   ├── analyzers/           # 分析器
│   ├── observers/           # 观察器
│   └── brokers/             # 经纪商模拟器
├── examples/                # 示例代码
├── tests/                   # 测试代码
├── docs/                    # 文档
└── tools/                   # 工具脚本
```

### 测试规范

- 使用 Pytest 作为测试框架
- 测试文件命名：`test_*.py`
- 测试类命名：`Test*`
- 测试函数命名：`test_*`

## 使用说明

1. 参考官方文档和论坛：https://www.backtrader.com/
2. 参考作者 CSDN 专栏：https://blog.csdn.net/qq_26948675/category_10220116.html
3. 查看项目 examples 目录中的示例代码