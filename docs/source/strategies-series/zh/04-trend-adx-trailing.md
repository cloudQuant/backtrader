# 先问有没有趋势，再问方向：ADX、SuperTrend 与跟踪止损

> 量化策略图鉴 · 第 04 篇 · 分类 `trend_following`（约 24 个策略）· 2026-09-02

1978 年，J. Welles Wilder 在《New Concepts in Technical Trading Systems》里一口气贡献了 RSI、ATR、SAR 和方向运动系统（DMS）——技术指标宇宙的大爆炸之年。其中最反直觉的产物是 ADX：它衡量趋势**存不存在**，却完全不关心方向。一段流畅的下跌和一段流畅的上涨，读数同样高；只有震荡市会让它低头。

这对趋势跟踪者是致命重要的区分。趋势策略亏钱的主因从来不是"方向看反"，而是"在没有趋势的地方反复开仓"。所以这一类策略的第一件事不是预测，而是**过滤**：ADX 先过门槛，方向交给别的信号；入场之后，再用 SuperTrend、NRTR、ATR 吊灯这类"会自己走的止损线"把利润跟出来。本篇解读 `trend_following` 分类下约 24 个趋势强度与跟踪止损策略，数据统一为 XAUUSD（现货黄金）M15，2025-12-03 至 2026-03-10 共 6,129 根 K 线——同一段行情，方便横向比较。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| ADX + MA | XAUUSD M15 | ADX 阈值闸门过滤 MA 交叉信号 | `test_0064_0687_adx_ma.py` |
| ADX Crossing | XAUUSD M15+H1 | H1 上 +DI/-DI 交叉定向 | `test_0110_1039_adx_crossing.py` |
| ADX Smoothed | XAUUSD M15+H4 | 两级指数平滑 DI 再交叉 | `test_0136_1226_adx_smoothed.py` |
| ADXDMI | XAUUSD M15+H8 | 8 小时信号周期 DI 交叉 | `test_0249_0852_adxdmi.py` |
| SuperTrend（CCI 版） | XAUUSD M15+H1 | CCI/ATR 状态翻转的 SuperTrend | `test_0085_0906_supertrend.py` |
| SuperTrend（Kolier 版） | XAUUSD M15 | ATR 带翻转即反手 | `test_0139_1232_supertrend.py` |
| ATR Trailing | XAUUSD M15 | ATR 通道突破 + 棘轮跟踪止损 | `test_0140_1257_atr_trailing.py` |
| NRTR | XAUUSD M15+H1 | Nick Rypock 跟踪反转线 | `test_0254_0904_nrtr.py` |
| NRTR Extr | XAUUSD M15 | NRTR 的外推变体 | `test_0253_0903_nrtr_extr.py` |
| TrendMagic | XAUUSD M15+H4 | CCI 定极性、ATR 画支撑/阻力线 | `test_0114_1085_trendmagic.py` |
| ADX v1 | XAUUSD M15 | ADX 家族的极简参数化 | `test_0126_1189_adx_v1.py` |
| ADX System | XAUUSD M15 | ADX 系统的完整 EA 移植 | `test_0238_0740_adx_system.py` |
| ADX Cross Hull | XAUUSD M15 | ADX 交叉 + Hull 风格平滑 | `test_0142_1266_adx_cross_hull_style.py` |
| Laguerre ADX | XAUUSD M15 | Laguerre 滤波改造的 ADX | `test_0096_0976_laguerre_adx.py` |
| PriceChannel Stop | XAUUSD M15 | 价格通道跟踪止损 | `test_0088_0913_pricechannel_stop.py` |

## 深读一：ADX + MA——先过门槛，再谈方向

[test_0064_0687_adx_ma.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0064_0687_adx_ma.py) 把 Wilder 的思想写成了一个闸门：中价（高低均值）的 15 周期 SMMA 给方向，12 周期 ADX 给"配重"——只有 ADX 站上阈值 `porog_adx=16`，MA 交叉信号才有资格下单：

```python
ma_prev = float(self.ma[-1])
adx_prev = float(self.adx[-1])
close_prev = float(self.data.close[-1])
close_prev2 = float(self.data.close[-2])
if adx_prev <= float(self.p.porog_adx):
    return                                   # 趋势强度不够，一律不开仓
if close_prev > ma_prev and close_prev2 < float(self.ma[-2]):
    self.signal_count += 1
    self.order = self.buy(size=float(self.p.lots))
    return
if close_prev < ma_prev and close_prev2 > float(self.ma[-2]):
    self.signal_count += 1
    self.order = self.sell(size=float(self.p.lots))
```

**诚实的回测结果**：这段三个月的黄金 M15 上，它交易了 409 笔，胜率 45.48%，终值 997,063.70（初始 100 万）——净亏 2,936，盈亏比拖累之下 PF 只有 0.80。测试把这些数字全部钉进断言。它提醒我们：ADX 过滤降低的是"无趋势开仓"，但门槛 16 对黄金 M15 来说太宽松，照样放进了大量震荡。**过滤器是剂量的艺术**。

同家族的 [test_0249_0852_adxdmi.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0249_0852_adxdmi.py) 则展示了分工的另一半：ADXDMI 里 +DI 上穿 -DI 做多、下穿做空——方向由 DI 交叉给出，且信号在 480 分钟（H8）重采样周期上计算、在 M15 上执行。慢信号周期把交易压到 10 笔（4 胜 6 负），终值 1,000,085.50。ADX 管"有没有"，DI 管"往哪边"，两兄弟各司其职。工程上这也是"多周期双数据源"的标准模板：执行 feed 与信号 feed 分开注入 cerebro，指标在重采样序列上计算、订单在低周期序列上成交——本篇表格里一半的策略都沿用这个骨架。

## 深读二：SuperTrend——一条会翻身的线

SuperTrend 是跟踪止损家族里最著名的"单线状态机"：以 ATR 通道包住价格，多头时止损线挂在 close − multiplier×ATR，空头时挂在 close + multiplier×ATR；价格打穿，方向状态就地翻转。[test_0139_1232_supertrend.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0139_1232_supertrend.py)（Kolier 版，`atr_period=5, multiplier=0.5`）的 `next()` 精炼到只剩状态翻转：

```python
d = float(self.st.direction[0])
if self._prev_dir is None:
    self._prev_dir = d
    return

flipped_bull = self._prev_dir < 0 and d > 0
flipped_bear = self._prev_dir > 0 and d < 0
self._prev_dir = d

if self.position:
    if self.position.size > 0 and flipped_bear:
        self.close()
        self.sell(size=self.p.lot)           # 翻转即平仓反手
        return
    elif self.position.size < 0 and flipped_bull:
        self.close()
        self.buy(size=self.p.lot)
        return
else:
    if flipped_bull:
        self.buy(size=self.p.lot)
        return
    if flipped_bear:
        self.sell(size=self.p.lot)
```

multiplier 压到 0.5 意味着轨道几乎贴着价格走——于是三个月翻了 2,640 笔（多空各 1,320），胜率 47.23%，终值 1,000,984.40，PF 1.009：几乎打平。对照 [test_0085_0906_supertrend.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0085_0906_supertrend.py) 的 CCI/ATR 状态翻转版（`cci_period=50, atr_period=5`，信号在 H1 计算）：84 笔，终值 998,092.70。两个变体、两种参数哲学，同一数据集上的差异被断言基线完整记录——这正是回归测试库做横向比较的价值。

## 深读三：ATR 吊灯式跟踪止损——止损即反手

吊灯止损（Chandelier Exit）的经典画法是"区间最高点 − k×ATR"，像从天花板垂下的吊灯，只升不降——它的价值不在预测，而在承认一个事实：你不知道趋势能走多远，但可以用波动的倍数给利润留出呼吸空间。[test_0140_1257_atr_trailing.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0140_1257_atr_trailing.py) 移植的 Exp_ATR_Trailing 是它的近亲：轨道以收盘价为锚（`buy_factor=sell_factor=2.0, atr_period=14`），空头突破上一根的轨道入场，持仓后止损线像棘轮一样只朝有利方向移动：

```python
upper = close + self.p.sell_factor * atr_val
lower = close - self.p.buy_factor * atr_val

if self.position:
    if self.position.size > 0:
        new_stop = close - self.p.buy_factor * atr_val
        if self._trail_stop is None or new_stop > self._trail_stop:
            self._trail_stop = new_stop      # 棘轮：只上移，不下移
        if close < self._trail_stop:
            self.close()
            self.sell(size=self.p.lot)        # 止损打穿，立即反手
            self._trail_stop = close + self.p.sell_factor * atr_val
            return
else:
    prev_upper = prev_close + self.p.sell_factor * prev_atr
    prev_lower = prev_close - self.p.buy_factor * prev_atr
    if close > prev_upper:
        self.buy(size=self.p.lot)
        self._trail_stop = lower
        return
```

这段数据上它交出 290 笔交易、**胜率仅 35.52%**，但 PF 1.117、终值 1,005,009.20、Sharpe 4.40。胜率三分之一却赚钱——小亏多次、靠少数大波段回本，这是趋势跟踪最典型的收益画像。把它和深读一放在一起看更有意思：ADX+MA 胜率 45.5% 却亏钱，这里胜率 35.5% 却赚钱——胜率与盈亏比孰轻孰重，两条断言基线已经替你回答了。

## 其余策略，快速点将

- **NRTR**（`test_0254`）：Nick Rypock 跟踪反转线，回撤比例 dK 由平均波幅自适应；H1 信号驱动，750 笔、胜率 46.8%、终值 993,796.90——同为"跟踪+翻转"思想的另一份对照样本。
- **TrendMagic**（`test_0114`）：CCI≥0 时跟踪 `low − ATR` 的支撑线、CCI<0 时跟踪 `high + ATR` 的阻力线，H4 颜色翻转驱动进出场——把"极性"与"距离"拆成两个指标。
- **ADX Crossing**（`test_0110`）：`adx_period=50` 的长周期 Wilder 平滑 DI 交叉，信号更慢更稀。
- **ADX Smoothed**（`test_0136`）：`alpha1=0.25, alpha2=0.33` 两级平滑 DI 再取交叉——先降噪、后定向。
- **Laguerre ADX / ADX v1 / ADX Cross Hull**（`test_0096` / `test_0126` / `test_0142`）：ADX 与 Laguerre、Hull 等滤波器的三种杂交，适合研究"平滑器换掉之后信号分布怎么变"。

## 一条命令跑起来

```bash
# 整个 trend_following 分类（runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/trend_following/ -v

# 只跑 ATR 吊灯跟踪止损
pytest tests/functional/strategies/trend_following/test_0140_1257_atr_trailing.py -v
```

每个测试都会在向量化（`runonce=True`）与事件驱动（`runonce=False`）两种引擎模式下各跑一遍并比对指标——引擎改版若引入偏差，这里第一时间报警。

## 为什么在这个项目上研究趋势强度与跟踪止损

ADX 阈值、ATR 乘数、信号周期——这类策略的参数敏感度极高，一个系数从 0.5 调到 3.0 交易数能差出一个数量级，最需要**大规模、可复现**的回测基础设施。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
