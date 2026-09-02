# 均线交叉：从金叉死叉到 Hull 均线的 69 副面孔

> 量化策略图鉴 · 第 01 篇 · 分类 `trend_following`（均线交叉子族约 69 个策略）· 2026-09-02

如果量化策略有一部族谱，第一页一定写着移动平均线交叉。它是绝大多数人接触的第一种"技术分析"：快线上穿慢线买入，下穿卖出。正因为太简单，它也是最容易被低估的策略族——在本仓库 `trend_following` 分类约 340 个策略里，均线交叉及其近亲占了约 69 席，是这个分类中最大的子族。

一个反直觉的事实：在黄金 2008-2025 这轮大牛市上，最朴素的 50/200 金叉系统 18 年只做了 13 笔交易，胜率不到 31%，却把 100 万做到 357 万。胜率和收益无关，这是趋势跟踪的第一课。

本篇解读这个子族的代表成员：金叉/死叉的统计学含义、价格穿越与均线交叉两种范式之争、以及 SMA/EMA/HMA 这一族"低延迟均线"的演化。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| SMA 趋势跟随 | XAUUSD 日线 2008-2025 | 收盘价站上 200SMA 持多，跌回空仓 | `test_0001_sma_trend_following.py` |
| 金叉策略 | XAUUSD 日线 2008-2025 | 50SMA 上穿 200SMA 入场，死叉离场 | `test_0175_golden_cross.py` |
| 死叉反向 | XAUUSD 日线 2008-2025 | 死叉抄底博超卖反弹，金叉离场 | `test_0174_death_cross_reverse.py` |
| 双均线交叉 EA | XAUUSD M15 | 2/5 SMA 之差突破 45 点死区才入场 | `test_0051_0631_doublema_crossover.py` |
| YY Cross 2MA | XAUUSD M15 | 72/150 双均线交叉反手 + 300 点止盈 | `test_0014_0022_yy_cross_2_ma.py` |
| 通用 MACross EA | XAUUSD M15 | 可配置周期/反转/风险管理的交叉模板 | `test_0033_0408_universal_macross_ea.py` |
| Sunrise EMA | ORCL 日线 2010-2014 | EMA14/24 交叉 + 四阶段回调确认状态机 | `test_86_sunrise_ema_crossover_strategy.py` |
| HMA 交叉 | ORCL 日线 2010-2014 | Hull 均线 60/90 交叉，低延迟多空反手 | `test_87_hma_crossover_strategy.py` |
| DEMA 交叉 | ORCL 日线 | 双重 EMA 去滞后，减少交叉迟滞 | `test_98_dema_crossover_strategy.py` |
| EMA+LWMA+RSI | XAUUSD M15 | 线性加权均线交叉 + RSI 过滤 | `test_0020_0136_ema_lwma_rsi.py` |
| Two iMA Cross | XAUUSD M15 | MT5 iMA 双线交叉的最小实现 | `test_0047_0592_two_ima_cross.py` |
| 20/200 Ants | XAUUSD M15 | 机构级 20/200 均线组合的多空版本 | `test_0244_0800_20_200_ants.py` |

## 深读一：金叉策略——18 年 13 笔交易的耐心

金叉的统计学本质是**双样本均值的穿越检验**：50 日均值是近期价格的样本均值，200 日均值是长期均值的代理，快线上穿慢线，等价于"近端动量显著高于长期基准"的一次朴素检验。信号稀疏、滞后、但噪音极低。

仓库实现（[test_0175_golden_cross.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0175_golden_cross.py)）在 pandas 侧预计算信号，策略侧只做下单：

```python
out['ma_fast'] = out['close'].rolling(window=fast_period).mean()   # fast=50
out['ma_slow'] = out['close'].rolling(window=slow_period).mean()   # slow=200

out['golden_cross'] = ((out['ma_fast'].shift(1) <= out['ma_slow'].shift(1)) &
                       (out['ma_fast'] > out['ma_slow'])).astype(float)
out['death_cross'] = ((out['ma_fast'].shift(1) >= out['ma_slow'].shift(1)) &
                      (out['ma_fast'] < out['ma_slow'])).astype(float)

def next(self):
    golden_cross = float(self.data.golden_cross[0]) > 0.5
    death_cross = float(self.data.death_cross[0]) > 0.5

    if not self.position:
        if golden_cross:
            self.pending_order = self.buy(size=self._get_position_size(
                target_notional_pct=float(self.p.lot_size)))
        return

    if death_cross:
        self.pending_order = self.close()
```

注意 `shift(1)`：交叉的"前一根"必须严格用前一根的均线值比较，防止信号在当根被"事后修正"。

**钉死的基线**。XAUUSD 日线 2008-2025、初始 100 万、0.02% 佣金：13 笔交易，4 胜 8 负（1 笔未平），胜率 30.77%，终值 3,571,828.03（+257.18%），盈利因子 2.04，最大回撤 37.54%。测试用 `abs(final_value - 3571828.03) < 3.6` 级别的容差把每个数字钉进断言——31% 的胜率靠盈亏比 2:1 赚钱，这就是趋势跟踪"截断亏损、让利润奔跑"的活样本。

## 深读二：SMA 趋势跟随——同一根均线，另一种用法

同一个目录里藏着最好的对照组（[test_0001_sma_trend_following.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0001_sma_trend_following.py)）：同样 200 日 SMA、同一份数据，但不等交叉，**价格本身站上均线就持有，跌回就空仓**：

```python
out['sma'] = out['close'].rolling(sma_period).mean()          # sma_period=200
out['trend_signal'] = (out['close'] > out['sma']).astype(float)

def next(self):
    trend_signal = float(self.data.trend_signal[0])

    if self.position:
        if trend_signal < 0.5:
            self.pending_order = self.close()
    else:
        if trend_signal > 0.5:
            self.pending_order = self.buy(size=self._get_position_size(
                target_notional_pct=float(self.p.lot_size)))
```

结果对比很有意思：价格穿越版交易 65 笔（11 胜 53 负，胜率 16.92%），终值 3,686,124.79（+268.61%），最大回撤 32.83%。收益略胜金叉版，但交易次数是 5 倍。价格穿越信号更灵敏、进出场更早；均线交叉信号更钝、换手更低。同一根 200 均线，机构用它当"牛熊分界线"（价格在上下决定风险敞口），散户用它找交叉点——两种范式在这里各回各位。顺带一提，隔壁的死叉反向策略（[test_0174_death_cross_reverse.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0174_death_cross_reverse.py)）专做"死叉后博反弹"：12 笔、9 胜 3 负（75% 胜率）、+28.41%——同一个信号，趋势用法和反转用法都能自洽。

## 深读三：双均线交叉 EA——45 点死区救不了 M15

把镜头切到分钟级，画风突变。[test_0051_0631_doublema_crossover.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0051_0631_doublema_crossover.py) 是 MT5 移植的双均线 EA：2/5 超短周期 SMA，但加了一个工程上很聪明的**死区（dead band）**——两线之差必须超过 `breakout_level` 个点才认信号，拒绝在均线粘合处反复开仓：

```python
sc = int(self.p.signal_candle)               # signal_candle=1：只用已收 K 线
fma = float(self.ma_fast[-sc])
sma = float(self.ma_slow[-sc])
breakout = float(self.p.breakout_level) * self._point()   # 45 × 0.01 = 0.45 美元
price = float(self.data.close[0])

if fma - sma > breakout:
    self._set_risk('buy', price)             # 止损 25 点，固定手数 0.1 手
    self.order = self.buy(size=self.p.lots)
elif sma - fma > breakout:
    self._set_risk('sell', price)
    self.order = self.sell(size=self.p.lots)
```

结果依旧诚实：3 个月 XAUUSD M15 上 2,678 笔交易，胜率 47.31%，终值 997,462.90（-0.25%）。2/5 均线在 M15 上接近随机游走的噪音探测器，45 点死区已经是很努力的过滤，仍然填不平磨损。这组数字的价值在于划出边界：**均线周期越短、周期越贴近噪音尺度，交叉系统越接近抛硬币**——它是你优化参数时的"下限对照组"。

## 其余策略，快速点将

- **HMA 交叉**（`test_87`）：Hull 均线用 WMA(2·WMA(n/2)−WMA(n)) 的组合把滞后压到最低，60/90 双 HMA 在 ORCL 上终值 100,081.45——均线族谱里"降延迟"路线的代表，和 DEMA（`test_98`）互为参照。
- **Sunrise EMA**（`test_86`）：交叉只当"预选"，还要经过回调确认、窗口打开、突破监控四阶段状态机——把一次交叉拆成一次完整入场流程的教科书。
- **YY Cross 2MA**（`test_0014`）：72/150 慢交叉反手 + 300 点止盈，MT4 时代论坛流传的经典参数。
- **通用 MACross EA**（`test_0033`）：周期、反转开关、止损止盈、追踪止损全部参数化的交叉模板，适合当自己的第一个改造对象。
- **20/200 Ants**（`test_0244`）：20/200 这对"机构参数"的 M15 多空版，本子族里被复用最多的参数组合。

## 一条命令跑起来

```bash
# 整个 trend_following 分类（300+ 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/trend_following/ -v

# 只跑金叉策略
pytest tests/functional/strategies/trend_following/test_0175_golden_cross.py -v
```

每个测试都在向量化（`runonce=True`）与事件驱动（`runonce=False`）两种引擎下各跑一遍并比对指标——你在改均线周期做实验之前，先确认引擎本身没有数值漂移。

## 为什么在这个项目上研究均线交叉

均线交叉是参数实验最密集的策略族：周期组合、均线类型、死区宽度、信号 K 线偏移，每个旋钮都值得一轮扫描。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的用武之地：纯 Python 引擎比原版快 46%，1,152 个策略回归测试几分钟跑完；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，69 个均线变体的网格搜索从"过夜任务"变成"喝口咖啡"。而每个策略钉死的指标断言基线，保证你比较的是策略优劣，而不是引擎实现的偏差。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
