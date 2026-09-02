# K 线形态交易：吞没、晨星、锤子，以及振荡器的第二次投票

> 量化策略图鉴 · 第 15 篇 · 分类 `price_patterns`（44 个策略）· 2026-09-02

Steve Nison 1991 年的《Japanese Candlestick Charting Techniques》把德川时代的酒田战法带进华尔街，从此"锤子""吞没""晨星"成了全球交易员的通用语。K 线形态的直觉很诱人：一根长下影线代表抛压被吸收，两根反向 K 线的包裹代表多空易帜——**它是肉眼可见的供求快照**。但当你把这些形态逐字翻译成代码、放到 15 分钟黄金数据上回测时，会发生什么？

本篇拆解 `tests/functional/strategies/price_patterns/` 下 44 个策略中的蜡烛图家族。它们全部来自 MT5 专家顾问的移植，统一跑在 XAUUSD M15 数据上（2025-12 到 2026-03，约三个月），初始资金 100 万、固定 0.1 手——小仓位、零佣金、看信号本身成色。一个耐人寻味的结构是：这个目录里存在**单形态版**与**形态+RSI 确认版**的成对实现，正好做对照实验。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 三内含形态 EA | XAUUSD M15→H1 | 三内含涨/跌反转 + bracket 单固定点数止损止盈 | `test_0001_0033_simple_three_inside_pattern_ea.py` |
| 十字星突破 | XAUUSD M15 | 开收价接近成十字星，破其高低点追突破 | `test_0005_0495_doji_trader.py` |
| 黄昏星 | XAUUSD M15 | 三根 K 线见顶反转，可选相对实体/缺口过滤 | `test_0009_0587_eveningstar.py` |
| 多空吞没 | XAUUSD M15 | 第二根实体完整包裹第一根，opposite_signal 反手 | `test_0010_0588_bullish_bearish_engulfing.py` |
| 乌云盖顶/刺透线 + RSI | XAUUSD M15 | 乌云盖顶与刺透线形态，RSI 超买超卖确认 | `test_0017_1311_darkcloud_rsi.py` |
| 晨星/昏星 + CCI | XAUUSD M15 | 星线家族形态，CCI 通道做确认与出场 | `test_0019_1318_morningstar_cci.py` |
| 相遇线 + RSI | XAUUSD M15 | 两根反向 K 线收盘几乎同价，RSI 确认转折 | `test_0020_1319_meetinglines_rsi.py` |
| 锤子/上吊线 + RSI | XAUUSD M15 | SMA 下方锤子且 RSI<40 做多，上方上吊线且 RSI>60 做空 | `test_0023_1323_hammer_rsi.py` |
| 孕线 + RSI | XAUUSD M15 | 小实体孕于前根大实体，RSI(37) 确认反转 | `test_0025_1335_harami_rsi.py` |
| 吞没 + RSI | XAUUSD M15 | 吞没形态加实体大小与 RSI(11) 双重确认 | `test_0028_1339_engulfing_rsi.py` |

## 深读一：三内含形态——把 MT5 的 bracket 单翻译成 backtrader

[test_0001_0033_simple_three_inside_pattern_ea.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0001_0033_simple_three_inside_pattern_ea.py) 在 H1 周期（由 M15 重采样而来）上识别三内含涨/跌：一根长阳（阴）线、一根被其包裹的反向小 K 线、再一根收盘突破首根极值的确认 K 线。形态判定是八个布尔条件的直译：

```python
return (
    older_open > older_close and            # 首根阴线
    middle_open < middle_close and          # 中间阳线
    middle_open > older_low and
    middle_close < older_high and           # 且被首根包裹（inside bar）
    latest_open < latest_close and
    latest_open > middle_open and
    latest_open < middle_close and
    latest_close > older_high               # 确认收盘突破首根高点
)
```

工程上最有看头的是出场——它没有写止损循环，而是把止损止盈直接交给 `buy_bracket` 一组三腿订单：

```python
sl = close_price - self.p.stop_loss * self.p.point_size    # 500 点止损
tp = close_price + self.p.take_profit * self.p.point_size  # 500 点止盈
orders = self.buy_bracket(size=size, stopprice=sl, limitprice=tp)
```

点数 ×0.01 的换算、0.1 手的合法化（lot_min/lot_max/lot_step 夹逼）都忠实还原了 MT5 EA 的习惯。结果：终值 999,745.50（−0.03%），胜率 36.36%，最大回撤仅 0.08%——1:1 的盈亏比配上不足四成的胜率，数学上注定贴地飞行。**入场靠形态、盈亏比靠 bracket，两件事得分开学**；三内含作为一个"确认后再入场"的谨慎形态尚且如此，更激进的单 K 线形态可想而知。

## 深读二：多空吞没——最著名形态的成绩单

吞没形态是 Nison 体系里知名度最高的反转信号。[test_0010_0588_bullish_bearish_engulfing.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0010_0588_bullish_bearish_engulfing.py) 的判定比教科书还严格——不但实体要包裹，上下影线也要全面覆盖，还要留出 `distance` 点的余量：

```python
dist = float(self.p.distance) * self._point()
bullish = (
    c0_open < c0_close and                 # 当根阳线
    c1_open > c1_close and                 # 前根阴线
    c0_high > c1_high + dist and           # 高点也吞没
    c0_close > c1_open + dist and
    c0_open < c1_close - dist and          # 低点也吞没
    c0_low < c1_low - dist
)
```

`opposite_signal=True` 意味着反向形态出现时先平仓再反手。三个月 M15 数据上，这份"教科书标准实现"终值 990,348.20（−0.97%），**胜率 0.0%**，Sharpe −8.34。一个参考解释：M15 级别的吞没在黄金这种趋势性市场里更多是噪声而非共识翻转——回测的意义就是让这类"图很美、数很难看"的假设现出原形。顺带一提，`shift` 参数把形态检测整体右移一根 K 线，配合 `pending_direction` 的两段式下单（先平后开），EA 的时序语义被原样保留。

## 深读三：锤子 + RSI——给形态加第二次投票

对照实验的关键组来了。[test_0023_1323_hammer_rsi.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0023_1323_hammer_rsi.py) 同样交易锤子，但加了双重确认：位置（相对 SMA）与超卖（RSI）：

```python
def _is_hammer(self):
    ...
    mid1 = (o1 + c1) / 2.0
    rng = h1 - l1
    body_low = min(o1, c1)
    return mid1 < avg2 and body_low > (h1 - rng / 3.0) and c1 < c2 and o1 < o2
    # 锤子悬在 SMA5 下方、实体居K线上 1/3（长下影）、且处于下跌中
```

入场条件是 `self._is_hammer() and rsi0 < self.p.rsi_entry_long`（RSI14 < 40），做空镜像要求 RSI > 60；出场交给 RSI 对 30/70 的穿越。加了确认器之后：终值 999,635.80（−0.04%），**胜率 52.38%**，Sharpe −0.65——胜率从吞没版的 0% 拉回五成以上，代价是交易更少。单形态 vs 形态+确认，同一份数据、同一套框架，这就是这个目录成对实现的教学价值。

## 其余策略，快速点将

- **十字星突破**（`test_0005`）：不把十字星当反转，而是当突破锚——收盘越过十字星高/低点才追，把"犹豫"变成"待发的扳机"。
- **黄昏星**（`test_0009`）：三根 K 线见顶形态，自带相对实体、中根实体类型、缺口三档可选过滤，`opposite_signal` 反手机制与吞没版同源。
- **孕线 + RSI**（`test_0025`）：RSI 周期取了少见的 37、SMA 取 7——同族不同参数，适合做敏感性对照。
- **吞没 + RSI**（`test_0028`）：在吞没之上加"实体大于滚动平均实体"与 RSI(11) 确认，是深读二的确认版对照组。
- **相遇线 + RSI**（`test_0020`）：两根反向 K 线收在同一价位，"减速即转折"的小众形态。

## 一条命令跑起来

```bash
# 整个分类（44 个策略）
pytest tests/functional/strategies/price_patterns/ -v

# 只跑锤子 + RSI
pytest tests/functional/strategies/price_patterns/test_0023_1323_hammer_rsi.py -v
```

内联回归测试在 `runonce=True` 下对终值、胜率、回撤逐项断言基线；引擎侧另有 runonce/runnext 双模式对拍机制，守住向量化与事件驱动的数值一致性。

## 为什么在这个项目上研究 K 线形态

形态策略参数多、信号密、成败差距细微（盈亏比 1:1 还是 1:2 就是天壤之别），最需要可复现的对照实验。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 提供 1,152 个策略回归测试与逐项指标断言基线——你改一个 RSI 阈值，立刻知道哪些数字动了、动了多少。纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，配合 runonce/runnext 双模式对拍，形态定义的每个布尔条件都可以放心做消融实验。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
