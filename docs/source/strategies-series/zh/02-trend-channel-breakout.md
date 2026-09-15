# 通道突破进阶：海龟法则的完整版，以及它的近亲们

> 量化策略图鉴 · 第 02 篇 · 分类 `trend_following`（通道/水平位突破子族约 28 个策略）· 2026-09-02

上一篇（[第 28 篇](28-breakout.md)）讲了 `breakout` 分类里海龟法则的极简版：突破 20 日高点买入，跌破 10 日低点卖出，两行规则讲完。真实的海龟远不止这两行——1980 年代 Richard Dennis 发给学员的规则手册里，还有 55 日"失败突破"备用入场、按 ATR 计算的单元仓位、0.5×ATR 间隔的金字塔加仓、4 单位头寸上限。这些细节才是海龟实验真正的核心：**突破只是信号，仓位工程才是系统**。

本篇回到 `trend_following` 分类，看通道突破在这里的进阶变体：完整版海龟规则、M15 执行 + 4 小时信号的双周期 Donchian 色彩系统，以及一个叫"不倒翁"的时段区间突破。约 28 个策略，一条命令全部可复现。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 原版海龟规则 | XAUUSD M15 | 20/55 通道 + ATR 单元仓位 + 金字塔加仓 | `test_0074_0776_original_turtle_rules_trader.py` |
| Donchian 色彩系统 | XAUUSD M15→240min | 4 小时重采样通道色彩状态机，M15 执行 | `test_0078_0855_donchian_channels_system.py` |
| PChannel 系统 | XAUUSD M15→240min | 枢轴通道色彩反转，双数据流架构同上 | `test_0077_0854_pchannel_system.py` |
| 简单有效突破 | XAUUSD M15+H1 | H1 突破窗口双向 stop-entry 挂单 + 风险仓位 | `test_0015_0029_simple_yet_effective_breakout_strategy.py` |
| Flat Channel | XAUUSD M30 | StdDev 连缩识别盘整，突破挂单 + 87.3% 保本 | `test_0042_0541_flat_channel.py` |
| 不倒翁突破 | XAUUSD M15 | 时段高低区间突破，止损反手手数翻倍 | `test_0046_0579_nevalyashka_breakdown_level.py` |
| 海龟 A 股版 | sh600000 日线 | 200SMA 牛熊过滤 + 价格变化率突破 | `test_34_turtle_strategy.py` |
| Prop Firm 突破 | XAUUSD M15 | 突破 + 自营资金规则辅助函数 | `test_0016_0036_breakout_strategy_with_prop_firm_helper_functions.py` |
| EURUSD 突破 | EURUSD M15 | 欧元区时段的水平位突破变体 | `test_0044_0575_eurusd_breakout.py` |
| 日内水平位 | XAUUSD M15 | 日线级别水平位的盘中触发 | `test_0068_0734_breakdown_level_day.py` |
| PriceChannel Stop | XAUUSD M15 | 通道边界直接作为挂单止损 | `test_0088_0913_pricechannel_stop.py` |
| VR 水平位 | XAUUSD M15 | 成交量关系确认的水平位突破 | `test_0013_0003_vr_breakdown_level.py` |

## 深读一：原版海龟规则——信号之外，全是仓位工程

[test_0074_0776_original_turtle_rules_trader.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0074_0776_original_turtle_rules_trader.py) 把规则手册的骨架全部翻译了过来。参数即规则：`n_st=20`（系统一入场通道）、`n_lt=55`（系统二备用通道）、`n_exit=10`（反向离场通道）、`atr_period=20`、`max_risk=0.01`、`volume_limit=4.0`。

单元仓位的算法是海龟的灵魂——**每个单位只冒账户 1% 的风险，用 ATR 折算成手数**：

```python
def _unit_size(self):
    atr = float(self.atr[-1]) if len(self) > 1 else float(self.atr[0])
    if atr <= 0:
        return self.p.volume_min
    equity = self.broker.getvalue()
    risk_budget = equity * self.p.max_risk            # 1% 风险预算
    unit = risk_budget / max(atr * self.p.stop_loss * self.p.multiplier, 1e-9)
    return self._round_volume(unit)

# 入场：突破 20 日通道（上一笔若为失败突破，改用 55 日通道二次确认）
st_upper = self._channel_max(self.p.n_st)
st_lower = self._channel_min(self.p.n_st)
st_breakout = self._breakout(close, st_upper, st_lower)
if st_breakout == 0:
    return
unit = self._unit_size()
self._set_risk_prices(st_breakout, close)             # 止损 = 入场价 ∓ 1×ATR
self.last_entry_price = close
self.entry_order = self.buy(size=unit) if st_breakout > 0 else self.sell(size=unit)

# 加仓：浮盈每前进 1×ATR 加一个单位，总仓位封顶 4 手
if (close - self.last_entry_price) * current_direction > self.p.adding_interval * atr:
    self.entry_order = self.buy(size=unit) if current_direction > 0 else self.sell(size=unit)
```

离场同样分层：先看 1×ATR 止损，再看 10 日反向通道（`n_exit`），可选 Parabolic SAR 收紧止损。3 个月 XAUUSD M15 上的基线：6,109 根 K 线，345 笔交易，173 胜 172 负（胜率 50.14%），终值 1,190,431.17（+19.04%），盈利因子 1.23，最大回撤仅 8.08%。胜率对半开却能稳定盈利——利润全部来自"加仓加在趋势里、止损止在起点上"的仓位结构。

## 深读二：Donchian 色彩系统——把 M15 的手和 4 小时的脑分开

[test_0078_0855_donchian_channels_system.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0078_0855_donchian_channels_system.py) 展示了通道策略的另一种进化方向：**双周期架构**。信号在 240 分钟重采样流上计算，交易在 M15 流上执行：

```python
signal_df = _build_signal_frame(df, 240)      # M15 → 240 分钟 OHLCV 重采样
cerebro.adddata(Mt5PandasFeed(dataname=df, ...), ...)          # 执行流 compression=15
cerebro.adddata(Mt5PandasFeed(dataname=signal_df, ...), ...)   # 信号流 compression=240
```

指标本身（`DonchianChannelsSystem`，period=20、shift=2、margins=-2）输出的是一个 0-4 的"色彩"状态而不是买卖点：

```python
def next(self):
    shift = int(self.p.shift)                # 通道右移 2 根，回避突破当根自证
    highs = [float(self.data.high[-(shift + i)]) for i in range(int(self.p.period))]
    lows = [float(self.data.low[-(shift + i)]) for i in range(int(self.p.period))]
    hh = max(highs)
    ll = min(lows)
    smin = ll + (hh - ll) * float(self.p.margins) / 100.0
    smax = hh - (hh - ll) * float(self.p.margins) / 100.0
    close = float(self.data.close[0])
    open_ = float(self.data.open[0])
    color = 2.0                              # 2=通道内，3/4=上破（阴/阳），0/1=下破
    if close > smax:
        color = 4.0 if open_ <= close else 3.0
    if close < smin:
        color = 0.0 if open_ > close else 1.0
    self.lines.color[0] = color
```

`margins=-2` 把通道上下轨各向外扩 2% 带宽（收盘价必须超出 Donchian 轨道这个缓冲带才算突破），`shift=2` 让通道滞后两根 K 线——两个参数都在防"用当根高点证明当根突破"的假信号。策略侧只认色彩**跳变**（`c1 > 2.0 and c0 < 3.0` 式的转移）而非绝对状态，配合 1,000 点止损 / 2,000 点止盈的固定风险。基线：5,756 根 K 线，23 笔交易（18 多 5 空），10 胜 13 负，终值 1,000,230.40——勉强打平。信号慢下来之后交易次数骤降一个数量级，这是周期选择的直接代价与收益。

## 深读三：不倒翁突破——时段区间 + 马丁格尔反手

"Nevalyashka"是俄语"不倒翁"——按下去总会弹回来。[test_0046_0579_nevalyashka_breakdown_level.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0046_0579_nevalyashka_breakdown_level.py) 每天在 07:26-09:13 窗口内记录高低点，窗口结束后收盘价突破上沿做多、跌破下沿做空，止盈目标等于区间宽度，止损放在区间对侧：

```python
params = dict(
    time_start='07:26',
    time_end='09:13',
    lot=0.1,
    k_martin=2.0,          # 止损出场后反手，手数 ×2
    no_loss=False,         # 可选：浮盈过半程即移保本
    point=0.0001,
)

max_price, min_price = self._today_range()
if max_price is None or min_price is None or max_price <= min_price:
    return

close_price = float(self.data.close[0])
width = max_price - min_price
if close_price > max_price:
    self._arm('buy', close_price, min_price, close_price + width, float(self.p.lot))
    return
if close_price < min_price:
    self._arm('sell', close_price, max_price, close_price - width, float(self.p.lot))
```

真正"不倒翁"的部分在止损之后：被打掉止损不认输，反手开反向仓且手数乘 `k_martin=2.0`，赌假突破回切。基线：99 笔交易，49 胜 50 负（胜率 49.49%），终值 1,018,940.50（+1.89%），盈利因子 1.28，最大回撤 4.88%。数字平平，但它是本子族里"突破 + 反突破"双剧本的最小完整样本——也是观察马丁格尔风控缺口的现成反面教材（手数翻倍在第几次连亏后会撞上保证金？改改 `k_martin` 就知道）。

## 其余策略，快速点将

- **PChannel 系统**（`test_0077`）：与 Donchian 色彩系统同款双周期架构，把指标换成枢轴通道——两个文件对照着读，能看清"信号指标可插拔"的工程分层。
- **Flat Channel**（`test_0042`）：用 StdDev 连续收缩识别盘整带，在带缘挂突破单，止盈 1 倍带宽、止损 2 倍带宽，浮盈到目标的 87.3%（斐波那契比例）即移保本——波动率收缩→扩张的教科书实现。
- **简单有效突破**（`test_0015`）：H1 窗口上下缘双向 stop-entry 挂单，仓位按"每笔风险占权益比例"反推——挂单式突破与市价式突破的直接对照。
- **海龟 A 股版**（`test_34`）：200SMA 定牛熊、价格变化率超 10% 认突破、10% 追踪止损——海龟思想落到 A 股日线的本土化改写。

## 一条命令跑起来

```bash
# 整个 trend_following 分类（300+ 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/trend_following/ -v

# 只跑完整版海龟
pytest tests/functional/strategies/trend_following/test_0074_0776_original_turtle_rules_trader.py -v
```

双周期策略对数据流对齐极其敏感——重采样的 `label/closed` 参数差一格，信号就整体偏移一根 K 线。runonce/runnext 双模式对拍加上钉死的指标断言，正是防这类"悄悄的偏差"的第一道闸。

## 为什么在这个项目上研究通道突破

通道突破的参数空间是三维的：入场周期、离场周期、仓位单位。想把每种组合都真跑一遍，就需要**大规模、可复现**的回测基础设施。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 正是为此而生：纯 Python 引擎比原版快 46%，1,152 个策略回归测试几分钟跑完；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，海龟参数网格从"过夜任务"变成"喝口咖啡"。指标断言基线保证你调的是策略，而不是被引擎数值漂移牵着走。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
