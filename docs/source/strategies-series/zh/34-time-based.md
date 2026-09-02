# 定时与数据回放：让回测第一次拥有了"盘中的耐心"

> 量化策略图鉴 · 第 34 篇 · 分类 `time_based`（7 个策略）· 2026-09-02

绝大多数回测框架的世界观是"一根 K 线一个世界"：策略看到收盘价、下单、立刻成交、跳到下一根。但真实交易不是这样的——你会在开盘前扫一遍隔夜消息，会在周线尚未走完时盯着一根"还在生长"的 K 线犹豫，会在特定时刻（月末、午休、收盘前五分钟）做特定的动作。能把"时间"本身当作一等公民来调度的框架，才配谈实盘。

backtrader 在这件事上给了三件独门武器：`add_timer()` 定时器、`resampledata()` 重采样、`replaydata()` 数据回放。本篇解读 `tests/functional/strategies/time_based/` 下的 7 个测试。坦白说，这一类的"策略"多数是双均线交叉这类朴素规则——但它们真正被测的不是策略，而是**框架功能本身**。把功能验证写成策略回测、并给每个指标钉上断言基线，这种"功能测试策略化"的思路，比孤零零的单元测试更能守住数值不漂移。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 定时器调度 | 日线 2005-2006（含交易时段） | 双均线交叉 + `SESSION_START` 定时器触发验证 | `test_62_timers.py` |
| Pandas 加载 | 日线 2005-2006 | `PandasData` 喂 DataFrame + 双均线交叉 | `test_52_data_pandas.py` |
| 数据重采样 | 日线→周线 | `resampledata` 聚合周线 + 双均线交叉 | `test_53_data_resample.py` |
| 数据回放 | 日线→周线 | `replaydata` 逐日推进"生长中的周线" + 双均线 | `test_58_data_replay.py` |
| 回放 × 布林 | 日线→周线 | 回放周线上的布林带突破 | `test_118_data_replay_bollinger.py` |
| 回放 × EMA | 日线→周线 | 回放周线上的 EMA(12,26) 交叉 | `test_119_data_replay_ema.py` |
| 回放 × MACD | 日线→周线 | 回放周线上的 MACD(12,26,9) 交叉 | `test_120_data_replay_macd.py` |

## 深读一：定时器——把"几点该干什么"写进策略

实盘策略最常见的需求不是更聪明的指标，而是**调度**：早上 9:25 拉一次行情、每周五收盘前再平衡、每天 14:55 强平隔夜仓。backtrader 的答案是在策略里注册定时器，回调进入 `notify_timer`（[test_62_timers.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_based/test_62_timers.py)）：

```python
class TimerStrategy(bt.Strategy):
    params = dict(
        when=bt.timer.SESSION_START,
        timer=True,
        fast_period=10,
        slow_period=30,
    )

    def __init__(self):
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

        if self.p.timer:
            self.add_timer(when=self.p.when)

    def notify_timer(self, timer, when, *args, **kwargs):
        self.timer_count += 1
```

数据源声明了交易时段 `sessionstart=9:00, sessionend=17:30`，定时器便在每个交易日开盘时刻准时敲门。测试给出的基线非常讲究：`timer_count == 512`，而 `next()` 只被调用了 `482` 次——差值恰好是慢线的 30 根预热 K 线。也就是说，**定时器从第一根 bar 就开始触发，而不用等指标就绪**。这个细节在实盘里意味着：预热期内该做的风控检查、数据同步，一天都不会漏。同一次回测的其余基线：终值 104,966.80、夏普 0.721、最大回撤 3.43%、9 笔完整交易。

## 深读二：重采样——日线攒成周线，历史一步到位

`resampledata` 解决的是"手上只有日线、策略想要周线"的问题。它把 5 根日 K 一次性聚合成 1 根周 K：开=周首开盘、高=周内最高、低=周内最低、收=周末收盘（[test_53_data_resample.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_based/test_53_data_resample.py)）：

```python
data_path = resolve_data_path("2005-2006-day-001.txt")
data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

# Resample to weekly timeframe
cerebro.resampledata(
    data,
    timeframe=bt.TimeFrame.Weeks,
    compression=1
)

cerebro.addstrategy(SimpleMAStrategy, fast_period=5, slow_period=15)
```

两年日线共 482 根，聚合后策略只看到 **89 根周线**，5/15 双均线在周线维度上完成 3 笔交易、终值 100,765.01、夏普 1.079。数字本身平淡，真正有价值的是这 89 根周线被永久钉进了断言——任何人改动重采样的一行代码，这个测试都会立刻尖叫。这是"功能测试策略化"的典型样本：不 mock、不造数据，用一次真实回测守住一个框架特性。

## 深读三：数据回放——回到"那一根 K 线还没走完"的下午

重采样是把历史"压缩"，回放（Replay）则是把历史"重演"。同一份日线数据，`replaydata` 让策略在周线视角上运行，但**每来一根日线就推进一次**：你看到的是一根随交易日不断生长的周 K——周一收盘时它是"半根"，周五收盘才补全（[test_58_data_replay.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_based/test_58_data_replay.py)）：

```python
# Use replay functionality to replay daily data as weekly data
cerebro.replaydata(
    data,
    timeframe=bt.TimeFrame.Weeks,
    compression=1
)

cerebro.addstrategy(ReplayMAStrategy, fast_period=5, slow_period=15)

print("Starting backtest...")
results = cerebro.run(runonce=runonce, preload=False)
```

对比同一组 5/15 参数：重采样下策略只看到 89 根周线、完成 3 笔交易；回放下同样的策略被推进了 **439 次**、做了 13 笔交易、终值 108,263.90、夏普 1.179。为什么？因为回放中的指标每根日线都在重算，"周中"就能触发交叉——这正是回放存在的意义：**检验策略在没有未来数据、只有"半根 K 线"时的真实行为**。也正因如此，回放测试必须 `preload=False`、以事件驱动逐根喂数，它天然是对引擎慢路径的极限压测。同一套回放框架还跑了布林突破（419 根、2 笔）、EMA(12,26)（384 根、9 笔）、MACD(12,26,9)（344 根、夏普 1.323）三个变体，确认不同指标族在回放数据上都不漂移。

## 其余一席，快速点将

- **Pandas 加载**（`test_52`）：不是所有数据都躺在 CSV 里。`pd.read_csv` 读进 DataFrame 后直接 `bt.feeds.PandasData(dataname=dataframe)` 入场——量化研究"从分析到回测"的最后一步，往往就差这一行。基线：482 根、9 笔、终值 100,496.68，与 CSV 直读完全对得上。

## 一条命令跑起来

```bash
# 整个分类（7 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/time_based/ -v

# 只跑数据回放
pytest tests/functional/strategies/time_based/test_58_data_replay.py -v
```

## 为什么在这个项目上研究时间与数据流

定时器、重采样、回放，三个特性全都要在引擎的时间轴上动手脚，任何一处差一个 bar 就全盘皆错。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 把这类"最容易悄悄坏掉"的功能全部纳入 1,152 个策略回归测试，runonce/runnext 双模式对拍加上逐指标的断言基线，重采样多聚合一行、回放少推进一步都会被抓住。而纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，意味着你可以把回放这种事件驱动的慢路径也放进日常回归，而不是"太慢了只跑一次"。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
