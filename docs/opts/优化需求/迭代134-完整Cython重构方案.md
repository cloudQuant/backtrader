# 迭代134: 完整Cython重构方案

## 一、重构目标

将backtrader **全部核心模块** 完整重构为Cython实现，避免Python与C之间的数据转换开销：
- 所有288个现有测试用例通过
- API完全兼容，用户代码无需修改
- 整体性能提升 **10-50倍**
- **不保留纯Python回退**，Cython为必需依赖

## 二、架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    用户层 (User Layer)                       │
│         Strategy, Indicator, Observer 用户自定义类            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Python接口层 (API Layer)                    │
│    backtrader/*.py - 保持现有API，委托给Cython核心层          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Cython核心层 (Core Layer)                    │
│              backtrader/_core/*.pyx                         │
│    ┌─────────────┬─────────────┬─────────────┐             │
│    │ _linebuffer │ _lineroot   │ _lineseries │             │
│    ├─────────────┼─────────────┼─────────────┤             │
│    │ _lineiter   │ _cerebro    │ _strategy   │             │
│    ├─────────────┼─────────────┼─────────────┤             │
│    │ _indicator  │ _broker     │ _order      │             │
│    └─────────────┴─────────────┴─────────────┘             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   数据层 (Data Layer)                        │
│              backtrader/_core/_types.pxd                    │
│         共享C类型定义、内存视图、numpy数组                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

1. **类型一致性**: 所有数值数据使用 `double` 类型，避免类型转换
2. **内存连续性**: 使用numpy数组或typed memoryview，确保C-contiguous
3. **零拷贝传递**: Cython模块间通过memoryview传递数据
4. **Python兼容**: 每个Cython类提供Python友好接口

## 三、完整模块清单

### 3.1 核心模块 (必须Cython化)

| 序号 | 模块 | 文件 | 代码行数 | 优先级 | Cython文件 |
|------|------|------|---------|--------|-----------|
| 1 | 类型定义 | - | - | P0 | `_core/_types.pxd` |
| 2 | 元基础 | `metabase.py` | 2,002 | P0 | `_core/_metabase.pyx` |
| 3 | 参数系统 | `parameters.py` | 2,100 | P0 | `_core/_parameters.pyx` |
| 4 | 线缓冲区 | `linebuffer.py` | 2,495 | P0 | `_core/_linebuffer.pyx` |
| 5 | 线根类 | `lineroot.py` | 875 | P0 | `_core/_lineroot.pyx` |
| 6 | 线系列 | `lineseries.py` | 2,100 | P0 | `_core/_lineseries.pyx` |
| 7 | 数据系列 | `dataseries.py` | 350 | P0 | `_core/_dataseries.pyx` |
| 8 | 线迭代器 | `lineiterator.py` | 2,500 | P0 | `_core/_lineiterator.pyx` |
| 9 | 数据源基类 | `feed.py` | 1,450 | P0 | `_core/_feed.pyx` |
| 10 | 指标基类 | `indicator.py` | 420 | P0 | `_core/_indicator.pyx` |
| 11 | 观察者基类 | `observer.py` | 110 | P1 | `_core/_observer.pyx` |
| 12 | 策略基类 | `strategy.py` | 2,700 | P0 | `_core/_strategy.pyx` |
| 13 | 回测引擎 | `cerebro.py` | 2,500 | P0 | `_core/_cerebro.pyx` |
| 14 | 订单 | `order.py` | 1,000 | P0 | `_core/_order.pyx` |
| 15 | 交易 | `trade.py` | 410 | P0 | `_core/_trade.pyx` |
| 16 | 持仓 | `position.py` | 300 | P0 | `_core/_position.pyx` |
| 17 | 经纪商基类 | `broker.py` | 330 | P0 | `_core/_broker.pyx` |
| 18 | 佣金 | `comminfo.py` | 450 | P1 | `_core/_comminfo.pyx` |
| 19 | 信号 | `signal.py` | 100 | P2 | `_core/_signal.pyx` |
| 20 | 大小器基类 | `sizer.py` | 110 | P1 | `_core/_sizer.pyx` |
| 21 | 定时器 | `timer.py` | 450 | P2 | `_core/_timer.pyx` |
| 22 | 交易日历 | `tradingcal.py` | 400 | P2 | `_core/_tradingcal.pyx` |
| 23 | 分析器基类 | `analyzer.py` | 600 | P1 | `_core/_analyzer.pyx` |
| 24 | 重采样过滤器 | `resamplerfilter.py` | 1,000 | P1 | `_core/_resamplerfilter.pyx` |
| 25 | 过滤器基类 | `flt.py` | 60 | P2 | `_core/_flt.pyx` |
| 26 | 填充器 | `fillers.py` | 150 | P2 | `_core/_fillers.pyx` |
| 27 | 函数库 | `functions.py` | 530 | P1 | `_core/_functions.pyx` |
| 28 | 数学支持 | `mathsupport.py` | 70 | P0 | `_core/_mathsupport.pyx` |
| 29 | 数学运算 | - | - | P0 | `_core/_mathops.pyx` |
| 30 | 存储基类 | `store.py` | 190 | P2 | `_core/_store.pyx` |
| 31 | 写入器 | `writer.py` | 340 | P2 | `_core/_writer.pyx` |
| 32 | 错误定义 | `errors.py` | 60 | P2 | `_core/_errors.pyx` |

### 3.2 指标模块 (52个)

| 序号 | 指标 | 文件 | Cython文件 | 优先级 |
|------|------|------|-----------|--------|
| 1 | SMA | `sma.py` | `indicators/_core/_sma.pyx` | P0 |
| 2 | EMA | `ema.py` | `indicators/_core/_ema.pyx` | P0 |
| 3 | WMA | `wma.py` | `indicators/_core/_wma.pyx` | P0 |
| 4 | SMMA | `smma.py` | `indicators/_core/_smma.pyx` | P0 |
| 5 | DEMA | `dema.py` | `indicators/_core/_dema.pyx` | P1 |
| 6 | KAMA | `kama.py` | `indicators/_core/_kama.pyx` | P1 |
| 7 | HMA | `hma.py` | `indicators/_core/_hma.pyx` | P1 |
| 8 | ZLEMA | `zlema.py` | `indicators/_core/_zlema.pyx` | P1 |
| 9 | MA基类 | `mabase.py` | `indicators/_core/_mabase.pyx` | P0 |
| 10 | RSI | `rsi.py` | `indicators/_core/_rsi.pyx` | P0 |
| 11 | LRSI | `lrsi.py` | `indicators/_core/_lrsi.pyx` | P1 |
| 12 | RMI | `rmi.py` | `indicators/_core/_rmi.pyx` | P1 |
| 13 | MACD | `macd.py` | `indicators/_core/_macd.pyx` | P0 |
| 14 | ATR | `atr.py` | `indicators/_core/_atr.pyx` | P0 |
| 15 | 布林带 | `bollinger.py` | `indicators/_core/_bollinger.pyx` | P0 |
| 16 | CCI | `cci.py` | `indicators/_core/_cci.pyx` | P1 |
| 17 | 随机指标 | `stochastic.py` | `indicators/_core/_stochastic.pyx` | P0 |
| 18 | Williams | `williams.py` | `indicators/_core/_williams.pyx` | P1 |
| 19 | 动量 | `momentum.py` | `indicators/_core/_momentum.pyx` | P1 |
| 20 | 交叉 | `crossover.py` | `indicators/_core/_crossover.pyx` | P0 |
| 21 | 基础运算 | `basicops.py` | `indicators/_core/_basicops.pyx` | P0 |
| 22 | 偏差 | `deviation.py` | `indicators/_core/_deviation.pyx` | P1 |
| 23 | 方向运动 | `directionalmove.py` | `indicators/_core/_directionalmove.pyx` | P1 |
| 24 | DMA | `dma.py` | `indicators/_core/_dma.pyx` | P2 |
| 25 | DPO | `dpo.py` | `indicators/_core/_dpo.pyx` | P2 |
| 26 | DV2 | `dv2.py` | `indicators/_core/_dv2.pyx` | P2 |
| 27 | 包络线 | `envelope.py` | `indicators/_core/_envelope.pyx` | P1 |
| 28 | Heikin-Ashi Delta | `hadelta.py` | `indicators/_core/_hadelta.pyx` | P2 |
| 29 | Heikin-Ashi | `heikinashi.py` | `indicators/_core/_heikinashi.pyx` | P2 |
| 30 | Hurst | `hurst.py` | `indicators/_core/_hurst.pyx` | P2 |
| 31 | 一目均衡 | `ichimoku.py` | `indicators/_core/_ichimoku.pyx` | P1 |
| 32 | KST | `kst.py` | `indicators/_core/_kst.pyx` | P2 |
| 33 | 振荡器 | `oscillator.py` | `indicators/_core/_oscillator.pyx` | P1 |
| 34 | 百分比变化 | `percentchange.py` | `indicators/_core/_percentchange.pyx` | P2 |
| 35 | 百分比排名 | `percentrank.py` | `indicators/_core/_percentrank.pyx` | P2 |
| 36 | 枢轴点 | `pivotpoint.py` | `indicators/_core/_pivotpoint.pyx` | P1 |
| 37 | PGO | `prettygoodoscillator.py` | `indicators/_core/_pgo.pyx` | P2 |
| 38 | 价格振荡器 | `priceoscillator.py` | `indicators/_core/_priceoscillator.pyx` | P1 |
| 39 | PSAR | `psar.py` | `indicators/_core/_psar.pyx` | P1 |
| 40 | TRIX | `trix.py` | `indicators/_core/_trix.pyx` | P2 |
| 41 | TSI | `tsi.py` | `indicators/_core/_tsi.pyx` | P2 |
| 42 | 终极振荡器 | `ultimateoscillator.py` | `indicators/_core/_ultimateoscillator.pyx` | P2 |
| 43 | 涡旋 | `vortex.py` | `indicators/_core/_vortex.pyx` | P2 |
| 44 | ZL指标 | `zlind.py` | `indicators/_core/_zlind.pyx` | P2 |
| 45 | Aroon | `aroon.py` | `indicators/_core/_aroon.pyx` | P1 |
| 46 | 加速减速振荡器 | `accdecoscillator.py` | `indicators/_core/_accdec.pyx` | P2 |
| 47 | 真棒振荡器 | `awesomeoscillator.py` | `indicators/_core/_awesome.pyx` | P2 |
| 48 | OLS回归 | `ols.py` | `indicators/_core/_ols.pyx` | P2 |
| 49 | 自定义指标 | `myind.py` | `indicators/_core/_myind.pyx` | P2 |

### 3.3 分析器模块 (18个)

| 序号 | 分析器 | 文件 | Cython文件 | 优先级 |
|------|--------|------|-----------|--------|
| 1 | 年化收益 | `annualreturn.py` | `analyzers/_core/_annualreturn.pyx` | P1 |
| 2 | 卡玛比率 | `calmar.py` | `analyzers/_core/_calmar.pyx` | P1 |
| 3 | 回撤 | `drawdown.py` | `analyzers/_core/_drawdown.pyx` | P0 |
| 4 | 杠杆 | `leverage.py` | `analyzers/_core/_leverage.pyx` | P2 |
| 5 | 滚动对数收益 | `logreturnsrolling.py` | `analyzers/_core/_logreturnsrolling.pyx` | P2 |
| 6 | 周期统计 | `periodstats.py` | `analyzers/_core/_periodstats.pyx` | P1 |
| 7 | 持仓 | `positions.py` | `analyzers/_core/_positions.pyx` | P1 |
| 8 | PyFolio | `pyfolio.py` | `analyzers/_core/_pyfolio.pyx` | P2 |
| 9 | 收益 | `returns.py` | `analyzers/_core/_returns.pyx` | P0 |
| 10 | 夏普比率 | `sharpe.py` | `analyzers/_core/_sharpe.pyx` | P0 |
| 11 | 夏普统计 | `sharpe_ratio_stats.py` | `analyzers/_core/_sharpe_stats.pyx` | P1 |
| 12 | SQN | `sqn.py` | `analyzers/_core/_sqn.pyx` | P2 |
| 13 | 时间收益 | `timereturn.py` | `analyzers/_core/_timereturn.pyx` | P1 |
| 14 | 总价值 | `total_value.py` | `analyzers/_core/_totalvalue.pyx` | P1 |
| 15 | 交易分析 | `tradeanalyzer.py` | `analyzers/_core/_tradeanalyzer.pyx` | P0 |
| 16 | 交易记录 | `transactions.py` | `analyzers/_core/_transactions.pyx` | P1 |
| 17 | VWR | `vwr.py` | `analyzers/_core/_vwr.pyx` | P2 |

### 3.4 数据源模块 (20个)

| 序号 | 数据源 | 文件 | Cython文件 | 优先级 |
|------|--------|------|-----------|--------|
| 1 | CSV通用 | `csvgeneric.py` | `feeds/_core/_csvgeneric.pyx` | P0 |
| 2 | BT CSV | `btcsv.py` | `feeds/_core/_btcsv.pyx` | P1 |
| 3 | Pandas | `pandafeed.py` | `feeds/_core/_pandafeed.pyx` | P0 |
| 4 | Yahoo | `yahoo.py` | `feeds/_core/_yahoo.pyx` | P1 |
| 5 | Quandl | `quandl.py` | `feeds/_core/_quandl.pyx` | P2 |
| 6 | IB数据 | `ibdata.py` | `feeds/_core/_ibdata.pyx` | P1 |
| 7 | OANDA | `oanda.py` | `feeds/_core/_oanda.pyx` | P2 |
| 8 | CCXT | `ccxtfeed.py` | `feeds/_core/_ccxtfeed.pyx` | P1 |
| 9 | Crypto | `cryptofeed.py` | `feeds/_core/_cryptofeed.pyx` | P2 |
| 10 | CTP数据 | `ctpdata.py` | `feeds/_core/_ctpdata.pyx` | P1 |
| 11 | VC数据 | `vcdata.py` | `feeds/_core/_vcdata.pyx` | P2 |
| 12 | VChart | `vchart.py` | `feeds/_core/_vchart.pyx` | P2 |
| 13 | VChartCSV | `vchartcsv.py` | `feeds/_core/_vchartcsv.pyx` | P2 |
| 14 | VChartFile | `vchartfile.py` | `feeds/_core/_vchartfile.pyx` | P2 |
| 15 | Blaze | `blaze.py` | `feeds/_core/_blaze.pyx` | P2 |
| 16 | Chainer | `chainer.py` | `feeds/_core/_chainer.pyx` | P2 |
| 17 | InfluxDB | `influxfeed.py` | `feeds/_core/_influxfeed.pyx` | P2 |
| 18 | MT4 CSV | `mt4csv.py` | `feeds/_core/_mt4csv.pyx` | P2 |
| 19 | Rollover | `rollover.py` | `feeds/_core/_rollover.pyx` | P1 |
| 20 | SierraChart | `sierrachart.py` | `feeds/_core/_sierrachart.pyx` | P2 |

### 3.5 经纪商模块 (7个)

| 序号 | 经纪商 | 文件 | Cython文件 | 优先级 |
|------|--------|------|-----------|--------|
| 1 | 回测经纪商 | `bbroker.py` | `brokers/_core/_bbroker.pyx` | P0 |
| 2 | IB经纪商 | `ibbroker.py` | `brokers/_core/_ibbroker.pyx` | P1 |
| 3 | OANDA经纪商 | `oandabroker.py` | `brokers/_core/_oandabroker.pyx` | P2 |
| 4 | CCXT经纪商 | `ccxtbroker.py` | `brokers/_core/_ccxtbroker.pyx` | P1 |
| 5 | Crypto经纪商 | `cryptobroker.py` | `brokers/_core/_cryptobroker.pyx` | P2 |
| 6 | CTP经纪商 | `ctpbroker.py` | `brokers/_core/_ctpbroker.pyx` | P1 |
| 7 | VC经纪商 | `vcbroker.py` | `brokers/_core/_vcbroker.pyx` | P2 |

### 3.6 观察者模块 (7个)

| 序号 | 观察者 | 文件 | Cython文件 | 优先级 |
|------|--------|------|-----------|--------|
| 1 | 基准 | `benchmark.py` | `observers/_core/_benchmark.pyx` | P1 |
| 2 | 经纪商 | `broker.py` | `observers/_core/_broker.pyx` | P0 |
| 3 | 买卖 | `buysell.py` | `observers/_core/_buysell.pyx` | P0 |
| 4 | 回撤 | `drawdown.py` | `observers/_core/_drawdown.pyx` | P1 |
| 5 | 对数收益 | `logreturns.py` | `observers/_core/_logreturns.pyx` | P2 |
| 6 | 时间收益 | `timereturn.py` | `observers/_core/_timereturn.pyx` | P2 |
| 7 | 交易 | `trades.py` | `observers/_core/_trades.pyx` | P1 |

### 3.7 过滤器模块 (8个)

| 序号 | 过滤器 | 文件 | Cython文件 | 优先级 |
|------|--------|------|-----------|--------|
| 1 | Bar拆分器 | `bsplitter.py` | `filters/_core/_bsplitter.pyx` | P2 |
| 2 | 日历日 | `calendardays.py` | `filters/_core/_calendardays.pyx` | P2 |
| 3 | 数据填充器 | `datafiller.py` | `filters/_core/_datafiller.pyx` | P1 |
| 4 | 数据过滤器 | `datafilter.py` | `filters/_core/_datafilter.pyx` | P1 |
| 5 | 日步进 | `daysteps.py` | `filters/_core/_daysteps.pyx` | P2 |
| 6 | Heikin-Ashi | `heikinashi.py` | `filters/_core/_heikinashi.pyx` | P2 |
| 7 | Renko | `renko.py` | `filters/_core/_renko.pyx` | P2 |
| 8 | 交易时段 | `session.py` | `filters/_core/_session.pyx` | P1 |

### 3.8 大小器模块 (2个)

| 序号 | 大小器 | 文件 | Cython文件 | 优先级 |
|------|--------|------|-----------|--------|
| 1 | 固定大小 | `fixedsize.py` | `sizers/_core/_fixedsize.pyx` | P1 |
| 2 | 百分比 | `percents_sizer.py` | `sizers/_core/_percents.pyx` | P1 |

### 3.9 存储模块 (7个)

| 序号 | 存储 | 文件 | Cython文件 | 优先级 |
|------|------|------|-----------|--------|
| 1 | IB存储 | `ibstore.py` | `stores/_core/_ibstore.pyx` | P1 |
| 2 | OANDA存储 | `oandastore.py` | `stores/_core/_oandastore.pyx` | P2 |
| 3 | CCXT存储 | `ccxtstore.py` | `stores/_core/_ccxtstore.pyx` | P1 |
| 4 | Crypto存储 | `cryptostore.py` | `stores/_core/_cryptostore.pyx` | P2 |
| 5 | CTP存储 | `ctpstore.py` | `stores/_core/_ctpstore.pyx` | P1 |
| 6 | VC存储 | `vcstore.py` | `stores/_core/_vcstore.pyx` | P2 |
| 7 | VChartFile | `vchartfile.py` | `stores/_core/_vchartfile.pyx` | P2 |

### 3.10 工具模块

| 序号 | 工具 | 文件 | Cython文件 | 优先级 |
|------|------|------|-----------|--------|
| 1 | AutoDict | `utils/autodict.py` | `utils/_core/_autodict.pyx` | P1 |
| 2 | 日期工具 | `utils/dateintern.py` | `utils/_core/_dateintern.pyx` | P1 |
| 3 | Python3兼容 | `utils/py3.py` | `utils/_core/_py3.pyx` | P0 |

### 3.11 模块统计

| 类别 | 模块数量 | P0 | P1 | P2 |
|------|---------|-----|-----|-----|
| 核心模块 | 32 | 18 | 8 | 6 |
| 指标 | 49 | 10 | 15 | 24 |
| 分析器 | 17 | 4 | 7 | 6 |
| 数据源 | 20 | 2 | 6 | 12 |
| 经纪商 | 7 | 1 | 3 | 3 |
| 观察者 | 7 | 2 | 3 | 2 |
| 过滤器 | 8 | 0 | 3 | 5 |
| 大小器 | 2 | 0 | 2 | 0 |
| 存储 | 7 | 0 | 3 | 4 |
| 工具 | 3 | 1 | 2 | 0 |
| **合计** | **152** | **38** | **52** | **62** |

## 四、目录结构

```
backtrader/
├── _core/                           # Cython核心模块 (32个)
│   ├── __init__.pxd
│   ├── _types.pxd                   # 共享类型定义
│   ├── _metabase.pxd/.pyx
│   ├── _parameters.pxd/.pyx
│   ├── _linebuffer.pxd/.pyx
│   ├── _lineroot.pxd/.pyx
│   ├── _lineseries.pxd/.pyx
│   ├── _dataseries.pxd/.pyx
│   ├── _lineiterator.pxd/.pyx
│   ├── _feed.pxd/.pyx
│   ├── _indicator.pxd/.pyx
│   ├── _observer.pxd/.pyx
│   ├── _strategy.pxd/.pyx
│   ├── _cerebro.pxd/.pyx
│   ├── _order.pxd/.pyx
│   ├── _trade.pxd/.pyx
│   ├── _position.pxd/.pyx
│   ├── _broker.pxd/.pyx
│   ├── _comminfo.pxd/.pyx
│   ├── _signal.pxd/.pyx
│   ├── _sizer.pxd/.pyx
│   ├── _timer.pxd/.pyx
│   ├── _tradingcal.pxd/.pyx
│   ├── _analyzer.pxd/.pyx
│   ├── _resamplerfilter.pxd/.pyx
│   ├── _flt.pxd/.pyx
│   ├── _fillers.pxd/.pyx
│   ├── _functions.pxd/.pyx
│   ├── _mathsupport.pxd/.pyx
│   ├── _mathops.pxd/.pyx
│   ├── _store.pxd/.pyx
│   ├── _writer.pxd/.pyx
│   └── _errors.pxd/.pyx
│
├── indicators/
│   └── _core/                       # Cython指标 (49个)
│       ├── _sma.pyx, _ema.pyx, _macd.pyx, ...
│
├── analyzers/
│   └── _core/                       # Cython分析器 (17个)
│       ├── _sharpe.pyx, _drawdown.pyx, ...
│
├── feeds/
│   └── _core/                       # Cython数据源 (20个)
│       ├── _csvgeneric.pyx, _pandafeed.pyx, ...
│
├── brokers/
│   └── _core/                       # Cython经纪商 (7个)
│       ├── _bbroker.pyx, _ibbroker.pyx, ...
│
├── observers/
│   └── _core/                       # Cython观察者 (7个)
│       ├── _broker.pyx, _buysell.pyx, ...
│
├── filters/
│   └── _core/                       # Cython过滤器 (8个)
│       ├── _datafiller.pyx, _session.pyx, ...
│
├── sizers/
│   └── _core/                       # Cython大小器 (2个)
│       ├── _fixedsize.pyx, _percents.pyx
│
├── stores/
│   └── _core/                       # Cython存储 (7个)
│       ├── _ibstore.pyx, _ccxtstore.pyx, ...
│
├── utils/
│   └── _core/                       # Cython工具 (3个)
│       ├── _autodict.pyx, _dateintern.pyx, _py3.pyx
│
└── *.py                             # Python接口层（导入Cython模块）
```

## 四、核心模块设计

详见附录A-E的完整代码实现。

### 4.1 模块依赖关系

```
_types.pxd (基础类型)
    │
    ├── _linebuffer.pyx (数据存储)
    │       │
    │       └── _lineroot.pyx (Line基类)
    │               │
    │               └── _lineseries.pyx (多线容器)
    │                       │
    │                       └── _lineiterator.pyx (迭代器)
    │                               │
    │                               ├── _indicator.pyx
    │                               └── _strategy.pyx
    │
    ├── _order.pyx (订单)
    ├── _position.pyx (持仓)
    ├── _broker.pyx (经纪商)
    ├── _feed.pyx (数据源)
    └── _mathops.pyx (数学运算)
```

## 五、实施计划 (完整152模块重构)

### 总体时间规划

| 阶段 | 时间 | 模块数 | 重点 |
|------|------|--------|------|
| 阶段1 | 第1-3周 | 15 | 基础设施 + Line系统 |
| 阶段2 | 第4-6周 | 17 | 交易系统 + 数据系统 |
| 阶段3 | 第7-10周 | 49 | 指标系统 |
| 阶段4 | 第11-14周 | 42 | 分析器/观察者/数据源等 |
| 阶段5 | 第15-18周 | 29 | 经纪商/存储/过滤器等 |
| 阶段6 | 第19-20周 | - | 集成测试/性能优化/发布 |

---

### 阶段1: 基础设施 + Line系统 (第1-3周, 15个模块)

#### 第1周: 类型定义与核心缓冲区

| 任务 | Cython文件 | 工作量 | 验收标准 |
|------|-----------|--------|---------|
| 类型定义 | `_core/_types.pxd` | 1天 | 编译通过 |
| 数学支持 | `_core/_mathsupport.pyx` | 0.5天 | 编译通过 |
| 数学运算 | `_core/_mathops.pyx` | 1.5天 | 单元测试通过 |
| LineBuffer | `_core/_linebuffer.pyx` | 2天 | 基础测试通过 |

#### 第2周: Line系统核心

| 任务 | Cython文件 | 工作量 | 验收标准 |
|------|-----------|--------|---------|
| LineRoot | `_core/_lineroot.pyx` | 2天 | 继承关系正确 |
| LineSeries | `_core/_lineseries.pyx` | 2天 | 多线访问正确 |
| DataSeries | `_core/_dataseries.pyx` | 1天 | OHLCV访问正确 |

#### 第3周: 迭代器与参数系统

| 任务 | Cython文件 | 工作量 | 验收标准 |
|------|-----------|--------|---------|
| 参数系统 | `_core/_parameters.pyx` | 2天 | 参数解析正确 |
| 元基础 | `_core/_metabase.pyx` | 2天 | 对象创建正确 |
| LineIterator | `_core/_lineiterator.pyx` | 3天 | 迭代逻辑正确 |
| Python3工具 | `utils/_core/_py3.pyx` | 0.5天 | 编译通过 |
| 错误定义 | `_core/_errors.pyx` | 0.5天 | 编译通过 |

**阶段1验收**: Line系统基础测试全部通过

---

### 阶段2: 交易系统 + 数据系统 (第4-6周, 17个模块)

#### 第4周: 订单与持仓

| 任务 | Cython文件 | 工作量 | 验收标准 |
|------|-----------|--------|---------|
| Order | `_core/_order.pyx` | 2天 | 订单创建/状态正确 |
| Trade | `_core/_trade.pyx` | 1.5天 | 交易记录正确 |
| Position | `_core/_position.pyx` | 1.5天 | 持仓计算正确 |
| 佣金 | `_core/_comminfo.pyx` | 1天 | 佣金计算正确 |

#### 第5周: 经纪商与数据源

| 任务 | Cython文件 | 工作量 | 验收标准 |
|------|-----------|--------|---------|
| Broker基类 | `_core/_broker.pyx` | 2天 | 接口定义正确 |
| 回测Broker | `brokers/_core/_bbroker.pyx` | 3天 | 订单执行正确 |
| Feed基类 | `_core/_feed.pyx` | 2天 | 数据加载正确 |

#### 第6周: 数据源实现

| 任务 | Cython文件 | 工作量 | 验收标准 |
|------|-----------|--------|---------|
| CSV通用 | `feeds/_core/_csvgeneric.pyx` | 2天 | CSV读取正确 |
| Pandas | `feeds/_core/_pandafeed.pyx` | 2天 | DataFrame转换正确 |
| 重采样 | `_core/_resamplerfilter.pyx` | 2天 | 重采样正确 |
| AutoDict | `utils/_core/_autodict.pyx` | 0.5天 | 字典访问正确 |
| 日期工具 | `utils/_core/_dateintern.pyx` | 0.5天 | 日期转换正确 |

**阶段2验收**: 基础回测流程可运行

---

### 阶段3: 指标系统 (第7-10周, 49个模块)

#### 第7周: 指标基类与核心MA (10个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| Indicator基类 | `_core/_indicator.pyx` | 2天 |
| MA基类 | `indicators/_core/_mabase.pyx` | 1天 |
| SMA | `indicators/_core/_sma.pyx` | 0.5天 |
| EMA | `indicators/_core/_ema.pyx` | 0.5天 |
| WMA | `indicators/_core/_wma.pyx` | 0.5天 |
| SMMA | `indicators/_core/_smma.pyx` | 0.5天 |
| 基础运算 | `indicators/_core/_basicops.pyx` | 1天 |
| 交叉 | `indicators/_core/_crossover.pyx` | 0.5天 |

#### 第8周: 动量指标 (12个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| RSI | `indicators/_core/_rsi.pyx` | 0.5天 |
| MACD | `indicators/_core/_macd.pyx` | 0.5天 |
| 随机指标 | `indicators/_core/_stochastic.pyx` | 0.5天 |
| 动量 | `indicators/_core/_momentum.pyx` | 0.5天 |
| Williams | `indicators/_core/_williams.pyx` | 0.5天 |
| CCI | `indicators/_core/_cci.pyx` | 0.5天 |
| LRSI | `indicators/_core/_lrsi.pyx` | 0.5天 |
| RMI | `indicators/_core/_rmi.pyx` | 0.5天 |
| TSI | `indicators/_core/_tsi.pyx` | 0.5天 |
| 终极振荡器 | `indicators/_core/_ultimateoscillator.pyx` | 0.5天 |

#### 第9周: 波动率与趋势指标 (14个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| ATR | `indicators/_core/_atr.pyx` | 0.5天 |
| 布林带 | `indicators/_core/_bollinger.pyx` | 0.5天 |
| 偏差 | `indicators/_core/_deviation.pyx` | 0.5天 |
| 方向运动 | `indicators/_core/_directionalmove.pyx` | 1天 |
| Aroon | `indicators/_core/_aroon.pyx` | 0.5天 |
| PSAR | `indicators/_core/_psar.pyx` | 0.5天 |
| 一目均衡 | `indicators/_core/_ichimoku.pyx` | 0.5天 |
| 包络线 | `indicators/_core/_envelope.pyx` | 0.5天 |
| 振荡器 | `indicators/_core/_oscillator.pyx` | 0.5天 |
| 价格振荡器 | `indicators/_core/_priceoscillator.pyx` | 0.5天 |
| 枢轴点 | `indicators/_core/_pivotpoint.pyx` | 0.5天 |

#### 第10周: 其他指标 (13个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| DEMA | `indicators/_core/_dema.pyx` | 0.5天 |
| KAMA | `indicators/_core/_kama.pyx` | 0.5天 |
| HMA | `indicators/_core/_hma.pyx` | 0.5天 |
| ZLEMA | `indicators/_core/_zlema.pyx` | 0.5天 |
| TRIX | `indicators/_core/_trix.pyx` | 0.5天 |
| KST | `indicators/_core/_kst.pyx` | 0.5天 |
| Hurst | `indicators/_core/_hurst.pyx` | 0.5天 |
| OLS | `indicators/_core/_ols.pyx` | 0.5天 |
| 其他剩余指标 | 多个 | 2天 |

**阶段3验收**: 所有49个指标测试通过

---

### 阶段4: 分析器/观察者/策略 (第11-14周, 42个模块)

#### 第11周: 策略与引擎

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| Strategy | `_core/_strategy.pyx` | 3天 |
| Cerebro | `_core/_cerebro.pyx` | 4天 |
| Signal | `_core/_signal.pyx` | 0.5天 |
| Functions | `_core/_functions.pyx` | 0.5天 |

#### 第12周: 分析器 (17个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| Analyzer基类 | `_core/_analyzer.pyx` | 1天 |
| 回撤 | `analyzers/_core/_drawdown.pyx` | 0.5天 |
| 夏普 | `analyzers/_core/_sharpe.pyx` | 0.5天 |
| 收益 | `analyzers/_core/_returns.pyx` | 0.5天 |
| 交易分析 | `analyzers/_core/_tradeanalyzer.pyx` | 0.5天 |
| 其他分析器 | 多个 | 2天 |

#### 第13周: 观察者 (7个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| Observer基类 | `_core/_observer.pyx` | 1天 |
| Broker观察者 | `observers/_core/_broker.pyx` | 0.5天 |
| BuySell | `observers/_core/_buysell.pyx` | 0.5天 |
| Trades | `observers/_core/_trades.pyx` | 0.5天 |
| 其他观察者 | 多个 | 1.5天 |

#### 第14周: 大小器与定时器

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| Sizer基类 | `_core/_sizer.pyx` | 0.5天 |
| FixedSize | `sizers/_core/_fixedsize.pyx` | 0.5天 |
| Percents | `sizers/_core/_percents.pyx` | 0.5天 |
| Timer | `_core/_timer.pyx` | 1天 |
| TradingCal | `_core/_tradingcal.pyx` | 1天 |
| Fillers | `_core/_fillers.pyx` | 0.5天 |
| Writer | `_core/_writer.pyx` | 0.5天 |

**阶段4验收**: 完整策略回测测试通过

---

### 阶段5: 数据源/经纪商/存储/过滤器 (第15-18周, 29个模块)

#### 第15周: 数据源 (10个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| BT CSV | `feeds/_core/_btcsv.pyx` | 0.5天 |
| Yahoo | `feeds/_core/_yahoo.pyx` | 1天 |
| IB数据 | `feeds/_core/_ibdata.pyx` | 1天 |
| CCXT | `feeds/_core/_ccxtfeed.pyx` | 1天 |
| CTP数据 | `feeds/_core/_ctpdata.pyx` | 1天 |
| Rollover | `feeds/_core/_rollover.pyx` | 0.5天 |

#### 第16周: 数据源续 + 经纪商 (10个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| 其他数据源 | 多个 | 2天 |
| IB经纪商 | `brokers/_core/_ibbroker.pyx` | 1天 |
| CCXT经纪商 | `brokers/_core/_ccxtbroker.pyx` | 1天 |
| CTP经纪商 | `brokers/_core/_ctpbroker.pyx` | 1天 |

#### 第17周: 存储与过滤器 (12个)

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| Store基类 | `_core/_store.pyx` | 0.5天 |
| IB存储 | `stores/_core/_ibstore.pyx` | 1天 |
| CCXT存储 | `stores/_core/_ccxtstore.pyx` | 1天 |
| CTP存储 | `stores/_core/_ctpstore.pyx` | 1天 |
| 其他存储 | 多个 | 1天 |
| Flt基类 | `_core/_flt.pyx` | 0.5天 |
| 过滤器 | 多个 | 1天 |

#### 第18周: 剩余模块

| 任务 | Cython文件 | 工作量 |
|------|-----------|--------|
| 其他经纪商 | 多个 | 2天 |
| 其他过滤器 | 多个 | 2天 |
| 其他存储 | 多个 | 1天 |

**阶段5验收**: 所有152个模块编译通过

---

### 阶段6: 集成测试与发布 (第19-20周)

#### 第19周: 集成测试

| 任务 | 工作量 | 验收标准 |
|------|--------|---------|
| 全量回归测试 | 2天 | 288个测试全部通过 |
| 性能基准测试 | 1天 | 性能提升10x+ |
| 内存泄漏检测 | 1天 | 无内存泄漏 |
| 边界条件测试 | 1天 | 无崩溃 |

#### 第20周: 发布准备

| 任务 | 工作量 | 验收标准 |
|------|--------|---------|
| 跨平台编译 | 2天 | Linux/macOS/Windows |
| 预编译wheel | 1天 | PyPI发布 |
| 文档更新 | 1天 | README/API文档 |
| 版本发布 | 1天 | v2.0.0 |

---

### 里程碑检查点

| 里程碑 | 时间 | 交付物 | 验收标准 |
|--------|------|--------|---------|
| M1 | 第3周末 | Line系统 | 15个核心模块编译通过 |
| M2 | 第6周末 | 交易系统 | 基础回测可运行 |
| M3 | 第10周末 | 指标系统 | 49个指标测试通过 |
| M4 | 第14周末 | 完整系统 | 策略回测测试通过 |
| M5 | 第18周末 | 全部模块 | 152个模块编译通过 |
| M6 | 第20周末 | 正式发布 | v2.0.0发布 |

## 六、关键代码实现

### 6.1 类型定义 (_types.pxd)

```cython
# backtrader/_core/_types.pxd

cimport numpy as np
from libc.math cimport NAN, isnan

ctypedef double price_t
ctypedef long long datetime_t
ctypedef int index_t

cdef double DNAN = NAN

cdef enum BufferMode:
    UNBOUNDED = 0
    QBUFFER = 1

cdef enum OrderStatus:
    CREATED = 0
    SUBMITTED = 1
    ACCEPTED = 2
    COMPLETED = 4
    CANCELED = 5
    REJECTED = 8

cdef enum OrderType:
    MARKET = 0
    LIMIT = 1
    STOP = 2

cdef enum OrderSide:
    BUY = 0
    SELL = 1
```

### 6.2 LineBuffer核心 (_linebuffer.pyx)

```cython
# cython: language_level=3, boundscheck=False, wraparound=False

cimport numpy as np
import numpy as np
from ._types cimport *

DEF INITIAL_CAPACITY = 256

cdef class CLineBuffer:
    cdef:
        np.ndarray _data
        double[:] _view
        index_t _idx, _size, _capacity
        BufferMode _mode
        list _bindings
    
    def __cinit__(self):
        self._capacity = INITIAL_CAPACITY
        self._data = np.empty(self._capacity, dtype=np.float64)
        self._view = self._data
        self._idx = -1
        self._size = 0
        self._mode = UNBOUNDED
        self._bindings = []
    
    cdef inline double _get(self, index_t ago) noexcept nogil:
        cdef index_t idx = self._idx + ago
        if 0 <= idx < self._size:
            return self._view[idx]
        return NAN
    
    cdef inline void _set(self, index_t ago, double value) noexcept nogil:
        cdef index_t idx = self._idx + ago
        if 0 <= idx < self._size:
            self._view[idx] = value
    
    def __getitem__(self, ago):
        return self._get(<index_t>ago)
    
    def __setitem__(self, ago, value):
        cdef index_t idx = self._idx + <index_t>ago
        while idx >= self._size:
            self._extend_one(NAN)
        self._view[idx] = NAN if value is None else <double>value
    
    cpdef void forward(self, double value=NAN, index_t size=1):
        cdef index_t i
        for i in range(size):
            self._idx += 1
            if self._idx >= self._capacity:
                self._grow()
            self._view[self._idx] = value
            if self._idx >= self._size:
                self._size = self._idx + 1
    
    cdef void _grow(self):
        cdef index_t new_cap = self._capacity * 2
        cdef np.ndarray new_data = np.empty(new_cap, dtype=np.float64)
        new_data[:self._size] = self._data[:self._size]
        self._data = new_data
        self._view = self._data
        self._capacity = new_cap
    
    cdef void _extend_one(self, double value):
        if self._size >= self._capacity:
            self._grow()
        self._view[self._size] = value
        self._size += 1
    
    cpdef np.ndarray to_numpy(self):
        return np.asarray(self._view[:self._size])
    
    cpdef double[:] get_view(self):
        return self._view[:self._size]
```

### 6.3 数学运算 (_mathops.pyx)

```cython
# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True

from libc.math cimport sqrt, fabs, NAN
from ._types cimport index_t

cpdef void sma_once(double[:] dst, double[:] src, index_t period,
                    index_t start, index_t end) noexcept nogil:
    cdef index_t i
    cdef double total = 0.0, inv_p = 1.0 / period
    
    for i in range(start, start + period):
        total += src[i]
    dst[start + period - 1] = total * inv_p
    
    for i in range(start + period, end):
        total = total - src[i - period] + src[i]
        dst[i] = total * inv_p

cpdef void ema_once(double[:] dst, double[:] src, index_t period,
                    index_t start, index_t end) noexcept nogil:
    cdef index_t i
    cdef double alpha = 2.0 / (period + 1), ema
    
    ema = src[start]
    dst[start] = ema
    for i in range(start + 1, end):
        ema = alpha * src[i] + (1 - alpha) * ema
        dst[i] = ema

cpdef void rsi_once(double[:] dst, double[:] src, index_t period,
                    index_t start, index_t end) noexcept nogil:
    cdef index_t i
    cdef double change, avg_gain = 0, avg_loss = 0, rs
    
    for i in range(start + 1, start + period + 1):
        change = src[i] - src[i - 1]
        if change > 0: avg_gain += change
        else: avg_loss -= change
    avg_gain /= period
    avg_loss /= period
    
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    dst[start + period] = 100 - 100 / (1 + rs)
    
    for i in range(start + period + 1, end):
        change = src[i] - src[i - 1]
        avg_gain = (avg_gain * (period - 1) + (change if change > 0 else 0)) / period
        avg_loss = (avg_loss * (period - 1) + (-change if change < 0 else 0)) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        dst[i] = 100 - 100 / (1 + rs)

cpdef void binary_add(double[:] dst, double[:] s1, double[:] s2,
                      index_t start, index_t end) noexcept nogil:
    cdef index_t i
    for i in range(start, end): dst[i] = s1[i] + s2[i]

cpdef void binary_sub(double[:] dst, double[:] s1, double[:] s2,
                      index_t start, index_t end) noexcept nogil:
    cdef index_t i
    for i in range(start, end): dst[i] = s1[i] - s2[i]

cpdef void crossover(double[:] dst, double[:] s1, double[:] s2,
                     index_t start, index_t end) noexcept nogil:
    cdef index_t i
    dst[start] = 0
    for i in range(start + 1, end):
        dst[i] = 1.0 if s1[i] > s2[i] and s1[i-1] <= s2[i-1] else 0.0
```

### 6.4 Python接口层 (无回退)

```python
# backtrader/linebuffer.py
# Cython为必需依赖，不提供纯Python回退

from ._core._linebuffer import CLineBuffer

class LineBuffer(CLineBuffer):
    """API兼容的LineBuffer - 直接继承Cython实现"""
    
    UnBounded, QBuffer = (0, 1)
    
    # 所有方法直接继承自CLineBuffer
    # 仅在需要时添加Python层扩展
    
    def __repr__(self):
        return f"<LineBuffer len={len(self)} idx={self._idx}>"
```

```python
# backtrader/__init__.py
# 启动时验证Cython模块

def _verify_cython():
    """验证Cython核心模块已正确编译"""
    required_modules = [
        '_core._types',
        '_core._linebuffer',
        '_core._lineroot',
        '_core._lineseries',
        '_core._lineiterator',
        '_core._indicator',
        '_core._strategy',
        '_core._cerebro',
        '_core._broker',
        '_core._order',
        '_core._mathops',
    ]
    
    missing = []
    for mod in required_modules:
        try:
            __import__(f'backtrader.{mod}')
        except ImportError:
            missing.append(mod)
    
    if missing:
        raise ImportError(
            f"Cython核心模块未编译，缺失: {missing}\n"
            f"请运行: python setup.py build_ext --inplace"
        )

_verify_cython()
```

## 七、构建系统

### 7.1 setup.py

```python
from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy as np

extensions = [
    Extension("backtrader._core._types", ["backtrader/_core/_types.pyx"]),
    Extension("backtrader._core._linebuffer", ["backtrader/_core/_linebuffer.pyx"]),
    Extension("backtrader._core._lineroot", ["backtrader/_core/_lineroot.pyx"]),
    Extension("backtrader._core._mathops", ["backtrader/_core/_mathops.pyx"]),
    # ... 其他模块
]

setup(
    name='backtrader',
    ext_modules=cythonize(extensions, compiler_directives={
        'language_level': '3',
        'boundscheck': False,
        'wraparound': False,
    }),
    include_dirs=[np.get_include()],
)
```

### 7.2 Makefile

```makefile
build:
	python setup.py build_ext --inplace

test: build
	python -m pytest tests/ -v

test-pure:  # 纯Python测试
	BACKTRADER_NO_CYTHON=1 python -m pytest tests/ -v

clean:
	rm -rf build/ *.so **/*.so
```

## 八、测试策略

### 8.1 兼容性测试

```bash
# 1. 纯Python基线
BACKTRADER_NO_CYTHON=1 pytest tests/ -v

# 2. Cython加速版本
pytest tests/ -v

# 3. 结果对比（应完全一致）
pytest tests/ --compare-results
```

### 8.2 性能基准

```python
# tests/benchmarks/test_linebuffer_bench.py
import pytest
from backtrader._core._linebuffer import CLineBuffer

def test_getitem_benchmark(benchmark):
    buf = CLineBuffer()
    for i in range(10000):
        buf.forward(float(i))
    
    def run():
        for i in range(10000):
            _ = buf[0]
    
    benchmark(run)
```

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 跨平台编译问题 | 中 | 提供预编译wheel，CI多平台测试 |
| 动态特性兼容 | 中 | 保持Python包装层，渐进式重构 |
| 调试困难 | 低 | 纯Python回退，详细日志 |
| 用户代码兼容 | 高 | API 100%兼容，广泛测试 |

## 十、预期收益

| 场景 | 当前性能 | Cython后 | 提升 |
|------|---------|----------|------|
| LineBuffer访问 | 基准 | ~10x | **10倍** |
| SMA.once() | 基准 | ~20x | **20倍** |
| 完整回测(1万bar) | 基准 | ~10-15x | **10-15倍** |
| 完整回测(100万bar) | 基准 | ~20-50x | **20-50倍** |

## 十一、里程碑

| 里程碑 | 时间 | 交付物 |
|--------|------|--------|
| M1: LineBuffer | 第2周 | `_linebuffer.pyx`，测试通过 |
| M2: Line系统 | 第4周 | `_lineroot/_lineseries/_lineiterator.pyx` |
| M3: 指标系统 | 第7周 | `_indicator.pyx` + 核心指标 |
| M4: 交易系统 | 第9周 | `_order/_position/_broker.pyx` |
| M5: 完整系统 | 第11周 | `_strategy/_cerebro.pyx` |
| M6: 发布 | 第12周 | v2.0.0 发布 |

---

## 附录: 详细代码模板

详细的.pxd/.pyx文件模板请参考 `docs/cython_templates/` 目录。
