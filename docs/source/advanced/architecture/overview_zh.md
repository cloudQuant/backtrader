- --

title: 架构概览
description: 系统架构和设计

- --

# 架构概览

Backtrader 使用事件驱动架构来实现高效的回测和实盘交易。

## 系统架构

```mermaid
flowchart TB
    subgraph Data["数据层"]
        CSV[CSV 文件]
        DF[Pandas DataFrame]
        YF[Yahoo Finance]
        CCXT[CCXT 实盘]
        CTP[CTP 期货]
    end

    subgraph Backtrader Core["Backtrader 核心"]
        Cerebro[Cerebro 引擎]
        LF[Line 系统]
        PS[阶段系统]
    end

    subgraph Execution["执行层"]
        Strat[策略]
        Ind[指标]
        Obs[观察器]
        An[分析器]
    end

    subgraph Trading["交易层"]
        Brk[经纪人]
        Ord[订单]
    end

    Data --> Cerebro
    Cerebro --> Strat
    Strat --> Ind
    Strat --> Obs
    Strat -->|订单| Brk

    Brk -->|成交| Strat

    Cerebro --> An

    LF --> Cerebro
    PS --> Strat

```bash

## 核心组件

### Cerebro

协调整个系统的中央引擎：

- 管理数据源
- 执行策略
- 处理经纪人操作
- 协调分析器和观察器

### Line 系统

时间序列的基础数据结构：

```mermaid
classDiagram
    class LineRoot {

        - get(size)
        - len()
        - datetime

    }

    class LineBuffer {

        - __getitem__(key)
        - __setitem__(key, value)
        - minperiod

    }

    class LineSeries {

        - align()
        - date()
        - time()

    }

    class LineIterator {

        - prenext()
        - nextstart()
        - next()
        - once()

    }

    LineRoot <|-- LineBuffer

    LineBuffer <|-- LineSeries

    LineSeries <|-- LineIterator

```bash

### 阶段系统

策略生命周期的执行阶段：

```mermaid
stateDiagram-v2
    [*] --> __init__: 策略创建
    __init__ --> prenext: 指标预热中
    prenext --> prenext: 处理 K 线
    prenext --> nextstart: 达到最小周期
    nextstart --> next: 过渡完成
    next --> next: 正常运行
    next --> [*]: 回测结束

```bash

| 阶段 | 描述 | 用途 |

|------|------|------|

| `__init__` | 初始化策略和指标 | 创建指标，设置状态 |

| `prenext()` | 数据不足时调用 | 跳过交易逻辑 |

| `nextstart()` | 第一根有效数据 K 线 | 一次性设置 |

| `next()` | 正常运行 | 主要交易逻辑 |

### 观察器扩展模式

观察器是扩展功能的主要方式：

```mermaid
flowchart LR
    Strategy[策略] -->|1. 注册| LI[_lineiterators]

    Observer[观察器] -->|2. 添加| LI

    Cerebro[Cerebro] -->|3. 迭代| LI

    LI -->|4. 调用 next| Observer

```bash

## 数据流

### 回测流程

```mermaid
sequenceDiagram
    participant C as Cerebro
    participant D as 数据源
    participant S as 策略
    participant I as 指标
    participant B as 经纪人

    C->>D: 加载下一根 K 线
    D->>C: 返回 OHLCV 数据
    C->>I: 更新指标
    I->>I: 计算值
    C->>S: 调用 next()
    S->>S: 执行逻辑
    S->>B: 下单 (如果有)
    B->>B: 执行订单
    C->>C: 继续下一根 K 线

```bash

### 实盘交易流程

```mermaid
sequenceDiagram
    participant E as 交易所
    participant S as 存储/数据源
    participant C as Cerebro
    participant S2 as 策略
    participant B as 经纪人

    E->>S: 行情数据 (WebSocket)
    S->>C: 推送数据
    C->>C: 更新指标
    C->>S2: 调用 next()
    S2->>B: 下单
    B->>S: 提交订单
    S->>E: 发送订单
    E->>S: 订单成交
    S->>C: 更新持仓

```bash

## 组件层次

```bash
backtrader/
├── 核心层
│   ├── metabase.py          # 基础混入和所有者查找

│   ├── lineroot.py           # Line 系统基类

│   ├── linebuffer.py         # 循环缓冲区存储

│   ├── lineseries.py         # 时间序列操作

│   └── lineiterator.py       # 迭代器逻辑和阶段

│
├── 数据层
│   ├── feed.py               # 基础数据源类

│   └── feeds/                # 数据源实现

│
├── 执行层
│   ├── strategy.py           # 基础策略类

│   ├── indicator.py          # 基础指标类

│   ├── observer.py           # 基础观察器类

│   ├── analyzer.py           # 基础分析器类

│   └── broker.py             # 基础经纪人类

│
└── 应用层
    └── cerebro.py            # 主引擎

```bash

## 设计原则

### 1. 事件驱动

Cerebro 逐根 K 线处理数据，触发：

1. 指标更新
2. 策略执行
3. 订单处理
4. 观察器通知

### 2. 组件解耦

- 策略不依赖特定数据源
- 经纪人可插拔
- 指标适用于任何数据源

### 3. 可扩展性

主要扩展点：

1. **观察器**- 数据收集和监控

2.**分析器**- 性能指标
3.**指标**- 自定义计算
4.**策略**- 交易逻辑
5.**数据源**- 新数据源
6.**经纪人** - 订单执行

## Post-Metaclass 架构

代码库已移除基于元类的元编程：

### 旧模式 (已移除)

```python

# ❌ 不再使用

class MetaStrategy(type):
    def __call__(cls, *args, **kwargs):

# 元类魔法
        pass

```bash

### 新模式 (当前)

```python

# ✅ 显式 donew() 模式

def __new__(cls, *args, **kwargs):
    _obj, args, kwargs = cls.donew(*args, **kwargs)
    return _obj

def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

```bash

- *优势：**
- 性能提升 45%
- 显式初始化
- 更容易调试
- 更好的 IDE 支持

## 相关文档

- [Line 系统](line-system.md)
- [阶段系统](phase-system.md)
- [Post-Metaclass 设计](post-metaclass.md)
