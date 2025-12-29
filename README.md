# backtrader

#### 介绍
基于backtrader打造最好用的量化投研工具(中低频为主,后续改写成cpp版本后支持高频交易)
1. 当前版本是master版本，和官方主流的backtrader对齐，仅增加了部分功能，修改了部分bug, 没有功能上的改进，可以运行我csdn专栏专栏里面的策略。这个版本仅用于修复bug。
2. 最新版本是dev分支，主要是为了实现一些新的功能，会新增加一些功能，尝试把底层代码改成c++，支持tick级别的测试等，等dev完善之后，后续会逐步合并到master分支。
#### 安装教程
```markdown
# 安装python3.11, python3.11有性能上的提升，并且很多包都已经支持，下面是anaconda的一些镜像，仅供参考
# win：https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Windows-x86_64.exe
# mac m系列: https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-MacOSX-arm64.sh
# ubuntu:https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Linux-x86_64.sh

# 克隆项目
git clone https://gitee.com/yunjinqi/backtrader.git
# 安装依赖项
pip install -r ./backtrader/requirements.txt
# 编译cython文件并进行安装, mac和 ubuntu下使用下面指令。有一个只能在windows上才能编译成功，会报错，忽略就好
cd ./backtrader/backtrader && python -W ignore compile_cython_numba_files.py && cd .. && cd .. && pip install -U ./backtrader/
# 编译cython文件并进行安装, windows下使用下面指令
cd ./backtrader/backtrader; python -W ignore compile_cython_numba_files.py; cd ..; cd ..; pip install -U ./backtrader/
# 运行测试
pytest ./backtrader/tests -n 4
```

#### 使用说明

1. [参考官方的文档和论坛](https://www.backtrader.com/)
2. [参考我在csdn的付费专栏](https://blog.csdn.net/qq_26948675/category_10220116.html)
3. ts和cs的使用说明：https://yunjinqi.blog.csdn.net/article/details/130507409
4. 网络上也有很多的backtrader的学习资源，大家可以百度

#### Plotly绑图（高性能交互式图表）

针对大数据量场景，新增了Plotly绑图后端，相比matplotlib有以下优势：
- **高性能**: 支持10万+数据点，不卡顿
- **交互式**: 支持缩放、平移、Hover显示数据
- **联动**: 多子图共享X轴，联动操作

##### 基本使用
```python
import backtrader as bt

cerebro = bt.Cerebro()
# ... 添加策略和数据 ...
cerebro.run()

# 使用Plotly后端绑图（推荐大数据量使用）
cerebro.plot(backend="plotly", style="candle")

# 使用原有matplotlib后端（默认）
cerebro.plot(backend="matplotlib")
```

##### 保存为HTML文件
```python
from backtrader.plot import PlotlyPlot

plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html("backtrader_chart.html")
```

##### 支持的功能
- **图表类型**: K线图(`candle`)、OHLC(`bar`)、折线图(`line`)
- **成交量**: 支持overlay或独立子图
- **技术指标**: SMA, RSI, MACD等自动绘制
- **范围滑块**: 底部导航条方便浏览

## 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Cerebro (引擎)                                  │
│  - 管理策略、数据、经纪商的生命周期                                              │
│  - 运行模式: runonce (向量化) / 事件驱动                                        │
│  - 调用 _runonce() 或 _runnext() 执行回测                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│   DataFeed      │         │    Strategy     │         │     Broker      │
│   (数据源)       │         │    (策略)        │         │    (经纪商)      │
│                 │         │                 │         │                 │
│ - 继承LineSeries │         │ - 继承LineIterator│        │ - 订单管理       │
│ - OHLCV数据线    │         │ - 包含Indicators │         │ - 持仓管理       │
│ - datetime线    │         │ - next()/once() │         │ - 资金管理       │
└─────────────────┘         └─────────────────┘         └─────────────────┘
          │                           │
          │                           ▼
          │                 ┌─────────────────┐
          │                 │   Indicator     │
          │                 │   (指标)         │
          │                 │                 │
          │                 │ - 继承LineIterator│
          │                 │ - 计算技术指标    │
          │                 │ - once()/next() │
          │                 └─────────────────┘
          │                           │
          ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Line 系统核心类层次                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  LineRoot (基类)                                                            │
│    ├── LineSingle (单线)                                                    │
│    │     └── LineBuffer (线缓冲区)                                          │
│    │           ├── array: 数据存储                                          │
│    │           ├── _idx: 当前索引                                           │
│    │           ├── lencount: 数据长度                                       │
│    │           └── __getitem__/__setitem__: 数据访问                        │
│    │                                                                        │
│    └── LineMultiple (多线)                                                  │
│          └── LineSeries (线序列)                                            │
│                ├── lines: Lines对象(包含多个LineBuffer)                      │
│                └── 数据源、指标、策略的基类                                    │
│                                                                             │
│  LineActions (线操作基类，继承LineBuffer)                                     │
│    ├── LinesOperation (二元操作: a + b, a - b, a * b, a / b)                │
│    │     ├── 存储操作数 a, b 和操作符                                        │
│    │     ├── once(): 向量化批量计算                                          │
│    │     └── next(): 逐bar计算                                              │
│    │                                                                        │
│    └── LineOwnOperation (一元操作: -a, abs(a))                               │
│          ├── 存储操作数 a 和操作符                                           │
│          └── once()/next(): 计算方法                                        │
│                                                                             │
│  LineIterator (线迭代器，继承LineSeries)                                      │
│    ├── _lineiterators: 子指标列表                                           │
│    ├── _once(): runonce模式批量处理                                          │
│    ├── _next(): 事件驱动模式逐bar处理                                        │
│    └── Indicator/Strategy/Observer 的基类                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                            执行流程 (runonce模式)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Cerebro._runonce(runstrats)                                             │
│     │                                                                       │
│     ├── 2. strat._once(start, end)  # 批量预计算所有指标                      │
│     │       │                                                               │
│     │       ├── 遍历 _lineiterators 中的所有指标                              │
│     │       │     └── indicator._once(start, end)                           │
│     │       │           ├── 调用子指标的 _once()                             │
│     │       │           ├── 调用 preonce(), oncestart(), once()             │
│     │       │           └── 更新 lencount, _idx                             │
│     │       │                                                               │
│     │       └── LinesOperation.once(start, end)  # Line操作的向量化计算       │
│     │             ├── 调用 _parent_a._once() 和 _parent_b._once()            │
│     │             ├── _once_op(): 两个数组操作                               │
│     │             ├── _once_val_op(): 数组与标量操作                          │
│     │             └── 结果存入 self.array                                    │
│     │                                                                       │
│     ├── 3. strat.reset()  # 重置指针到起始位置                                │
│     │                                                                       │
│     └── 4. 循环每个bar:                                                      │
│           ├── data.advance()  # 数据前进                                     │
│           ├── strat._oncepost(dt)                                           │
│           │     ├── indicator.advance()  # 指标前进                          │
│           │     ├── strat.advance()  # 策略前进                              │
│           │     └── strat.next()  # 调用用户策略逻辑                          │
│           └── broker处理订单                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                            关键属性说明                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  _minperiod: 最小周期，指标需要的最少数据量才能产生有效值                        │
│  _idx: 当前索引位置，用于 __getitem__ 访问当前值                               │
│  lencount: 数据长度计数，len(line) 返回此值                                   │
│  _clock: 时钟源，用于同步数据和指标                                            │
│  _owner: 拥有者引用，指向包含此对象的父对象                                     │
│  _ltype: 类型标识 (IndType=0, StratType=1, ObsType=2)                        │
│  _opstage: 操作阶段 (1=向量化模式, 2=事件驱动模式)                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```


