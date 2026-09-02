# 杂项精选：TD Sequential 的衰竭倒数、逢跌买入与"顺带验框架"

> 量化策略图鉴 · 第 22 篇 · 分类 `misc`（28 个策略）· 2026-09-02

每个策略库都有一个"杂物间"，但本仓库的 `misc` 分类杂物得有格调：这里有 Tom DeMark 那套让交易员数 K 线数到 13 的 TD Sequential，有华尔街梗文化产物 BTFD（Buy The F***ing Dip），有蜡烛图老手 Bill Williams 的鳄鱼指标，也有"创 20 日新高就买、拿 2 根 K 线就卖"的极简挑战。

更特别的是，这个分类还承担着**框架功能验证**的双重角色：滑点模拟、佣金方案、writer 落盘、各类 analyzer 的数值校验都住在这里。它们不是"策略"，却是其余 1,000 多个策略回测结果可信的地基——滑点模型错了，所有高频策略的回测都是自欺。策略与地基同住一室，本篇一起讲。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| TD Sequential | ORCL 日线 2010-2014 | 连续 9 根对 4 期前收盘的比较完成 Setup，再数 Countdown 至 13 | `test_65_td_sequential_strategy.py` |
| Pinkfish 挑战 | YHOO 日线 2005-2006 | 创 20 日新高买入，固定持有 2 根无条件卖出 | `test_46_pinkfish_strategy.py` |
| Buy The Dip | ORCL 日线 | 跌幅达标后逢低买入的一族实现 | `test_110_buy_the_dip_strategy.py` / `test_79_buy_dip_strategy.py` |
| BTFD | 标准日线 2005-2006 | 梗文化的定量化：回调即机会 | `test_39_btfd_strategy.py` |
| Heikin Ashi | ORCL 日线 | 平均K线平滑噪声后趋势跟踪 | `test_76_heikin_ashi_strategy.py` |
| 鳄鱼指标 | ORCL 日线 | Bill Williams 三线平衡态判定趋势 | `test_82_alligator_strategy.py` |
| 随机支撑阻力 | 上证 sh600000 日线 | 随机指标定位支撑/阻力位交易 | `test_32_stochastic_sr_strategy.py` |
| 斜率策略 | ORCL 日线 | 价格线性回归斜率定方向 | `test_77_slope_strategy.py` |
| Renko+EMA | ORCL 日线 | 砖形图过滤噪声叠加均线 | `test_92_renko_ema_strategy.py` |
| 空中花园 | 沪锌 ZN889 分钟线 | 日内开盘形态突破 | `test_11_sky_garden_strategy.py` |
| The Strategy | 2006 年 5 分钟+日线 | 多时间框架共振的样例级实现 | `test_21_the_strategy.py` |
| 可转债策略 | 转债/正股日线 | 转债与正股联动交易 | `test_16_cb_strategy.py` / `test_17_cb_monday_strategy.py` |
| 双七策略 | ORCL 日线 | 连续 7 根同向K线的反转下注 | `test_71_double_sevens_strategy.py` |
| 多空组合 | 标准日线 2005-2006 | 多空对冲的基础样例 | `test_38_long_short_strategy.py` |
| **框架：滑点** | 标准日线 2005-2006 | SMA 金叉策略验证滑点模型影响 | `test_47_slippage_strategy.py` |
| **框架：佣金** | 标准日线 2005-2006 | 多种佣金方案的行为校验 | `test_54_commission_schemes.py` |
| **框架：writer** | 标准日线 2005-2006 | 回测数据落盘（CSV/文件）验证 | `test_60_writer_test.py` |
| **框架：分析器** | YHOO/标准日线 | Calmar/VWR/Sharpe 等指标数值基线 | `test_49_calmar_analyzer.py` / `test_50_vwr_analyzer.py` / `test_57_sharpe_timereturn.py` |
| **框架：指标与仓位** | 标准日线/YHOO | PSAR 指标与 Sizer 机制校验 | `test_55_psar_indicator.py` / `test_56_sizer_test.py` |

## 深读一：TD Sequential——数 K 线数出的衰竭信号

Tom DeMark 的 TD Sequential 是技术分析界少见的"有完整算法规范"的指标，被交易员用来捕捉趋势衰竭：价格不会永远跌，但连续跌够 9 根、再熬过 13 格倒数，空头也该累了。仓库实现（[test_65_td_sequential_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/misc/test_65_td_sequential_strategy.py)）忠实还原了两段式结构。Setup 阶段：连续 9 根收盘价低于 4 根之前的收盘（`candles_past_to_compare=4`）：

```python
if len(self.dataclose) > self.p.candles_past_to_compare:
    # 买方向触发：本次收盘 < 4 期前收盘，且上一次不满足
    if (self.dataclose[0] < self.dataclose[-self.p.candles_past_to_compare] and
            self.dataclose[-1] > self.dataclose[-(self.p.candles_past_to_compare + 1)]):
        self.buyTrig = True
        self.sellTrig = False
    # Setup 计数：连续满足则累加
    if self.dataclose[0] < self.dataclose[-self.p.candles_past_to_compare] and self.buyTrig:
        self.tdsl += 1
```

Countdown 阶段在 Setup 计满 9 后启动，直到第 13 格、且收盘价跌破第 8 格低点才确认"理想买点"：

```python
if self.buyCountdown == 8:
    self.buyVal = countdown_compare          # 记录第 8 格的价格
elif self.buyCountdown == 13:
    if self.dataprimary.low[0] <= self.buyVal:
        self.idealBuySig = True
        if not self.position:
            self.buy(size=10)                # 理想买点，做多
        self.buySetup = False
        self.buyCountdown = 0
```

实现里还带着 DeMark 体系的各种取消条款（`cancel_1/2/3`、`recycle_12`）与激进倒数开关（`aggressive_countdown`）——参数就是这套方法的完整词汇表。**回测结果**：ORCL 2010-2014、10 万本金、0.1% 佣金，1,257 根 K 线后终值 100,002.91——基本打平。测试用 `runonce` True/False 双参数化跑两遍并断言同一组数字，指标基准锁到小数点后六位（Sharpe 0.022949…）。衰竭计数在单只股票上不赚钱，但作为"复杂状态机的工程化样板"无价。

## 深读二：Pinkfish——两根 K 线的诚实

如果说 TD Sequential 是"繁"，Pinkfish 挑战就是"简"的极致（[test_46_pinkfish_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/misc/test_46_pinkfish_strategy.py)）：创 20 日新高就买，拿满 2 根 K 线，无条件卖。全部交易逻辑：

```python
def next(self):
    self.bar_num += 1
    if not self.position:
        if self.data.high[0] >= self.highest[0]:      # 当根最高触及 20 日最高
            self.buy()
            self.inmarket = len(self)
    else:
        if (len(self) - self.inmarket) >= self.p.sellafter:   # 持有 2 根
            self.sell()
```

注意它和海龟式突破的区别：没有出场通道、没有止损，出场只看日历——"到了就走"。**回测结果**：YHOO 2005-2006、5 万本金、固定 100 股，484 根 K 线后终值 49,739.00，Sharpe -2.5197，年化 -0.26%。测试把这组难看的数字焊死在断言里。为什么值得读？因为它是最好的"假设检验教具"：动量入场+随机持有期，在震荡市里就是磨损机器；把 `sellafter` 从 2 改成 20 会不会不一样？改成 trailing stop 呢？每改一处，断言立刻告诉你代价——这正是回归测试库教人研究的方式。

## 深读三：滑点验证——策略目录里的"地基"

第三读不属于任何交易思想，却决定所有回测的可信度。[test_47_slippage_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/misc/test_47_slippage_strategy.py) 内置一个标准 SMA(10/30) 金叉策略，但它存在的意义是给 `cerebro.broker.set_slippage_*` 系列接口当载体：同一策略在零滑点与固定/百分比滑点下的成交价差、净值差被逐一断言。同族的还有佣金方案矩阵（`test_54`）、writer 落盘（`test_60`）、Calmar/VWR/Sharpe 的 analyzers 数值基线（`test_49/50/57`）、PSAR 指标（`test_55`）与 Sizer（`test_56`）。它们与策略共用同一套 Cerebro 管线，因此任何引擎改动若影响成交、计费或指标计算，这些测试会在策略测试之前先报警——**misc 分类因此是仓库的"策略+框架验证"双重角色承担者**，这不是杂物间，是承重墙。

## 其余策略，快速点将

- **BTFD 三兄弟**（`test_39` / `test_79` / `test_110`）：同一"逢跌买入"思想的三种参数化——回调深度、确认条件、入场节奏各不相同，天然适合横向对比。
- **空中花园**（`test_11`）：沪锌分钟线上的开盘形态日内策略，中国期货时段处理可直接抄。
- **The Strategy**（`test_21`）：5 分钟+日线双时间框架回测的官方级样例，`resampledata` 用法参考。
- **连七反转**（`test_71`）、**上下影线**（`test_85`）：K 线形态统计派。
- **Arjun Bhatia 期货**（`test_84`）、**随机交叉**（`test_69`）、**cheat-on-open**（`test_40`，演示开盘价作弊模式的边界）。

## 一条命令跑起来

```bash
# 整个分类（28 个测试，策略+框架验证混合）
pytest tests/functional/strategies/misc/ -v

# 只跑 TD Sequential（runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/misc/test_65_td_sequential_strategy.py -v
```

## 为什么在这个项目上研究杂项策略

杂项分类最考验引擎的"边角"：Renko/Heikin Ashi 的非标准K线、多时间框架对齐、滑点与佣金的成交细节——恰恰是最容易产生数值分歧的地方。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把这些边角全部钉进基线：纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速；runonce/runnext 双模式对拍让向量化与事件驱动两条代码路径互为裁判。想在 TD Sequential 上扫几百组取消条款组合？这个仓库让你扫得起。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
