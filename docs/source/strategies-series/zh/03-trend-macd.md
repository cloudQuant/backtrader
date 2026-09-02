# MACD 趋势系统：零轴过滤、永远在场，与一个诚实的 A 股回测

> 量化策略图鉴 · 第 03 篇 · 分类 `trend_following`（MACD 子族 23 个策略）· 2026-09-02

1979 年，Gerald Appel 发明了 MACD（Moving Average Convergence Divergence）。它只由三个部件组成：快线（12 期 EMA）、慢线（26 期 EMA）、两者之差再平滑出的信号线（9 期 EMA）。四十年过去，它仍然挂在几乎每一个行情软件的默认副图上——也仍然是刚入门的人亏钱最快的地方。

为什么？因为"金叉买入"四个字省略了太多前提：金叉发生在零轴上方还是下方？MACD 离零轴多远？要不要反手？本篇解读 `trend_following` 分类里 23 个 MACD 策略给出的三种答案：官方模板的零轴过滤、裸交叉的永远在场、以及与 KDJ 的二重奏。三份回测基线恰好构成一部"同一指标的三种命运"。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| MACD Sample（MT5 官方） | XAUUSD M15 | 零轴下金叉 + EMA26 趋势 + 追踪止损 | `test_0116_1107_macd_sample.py` |
| MACD Cross（SAR） | XAUUSD M15 | 12/26/9 金叉死叉，止损即反手永远在场 | `test_0163_1327_macd_cross.py` |
| MACD+KDJ | sh600000 日线 | MACD 金叉定方向，KDJ 死叉择时离场 | `test_30_macd_kdj_strategy.py` |
| Digital MACD | XAUUSD M15 | FIR 数字滤波器替代 EMA 对构造 MACD | `test_0275_1104_digital_macd.py` |
| XMACD | XAUUSD M15 | 四种信号模式：线叉/零叉/斜率反转 | `test_0324_1298_xmacd.py` |
| Simple MACD | XAUUSD M15 | 不看交叉看斜率：MACD 走强持多、走弱持空 | `test_0231_0702_simple_macd.py` |
| MACD EA（慢周期版） | XAUUSD M15 | 120/260/90 慢 MACD + 部分止盈/保本 | `test_0036_0451_macd_ea.py` |
| MACD（柱形态版） | XAUUSD M15 | 柱状图峰谷反转形态确认后入场 | `test_0049_0628_macd.py` |
| MACD+EMA 快慢 | ORCL 日线 | MACD 交叉与 EMA 过滤的叠加 | `test_06_macd_ema_fase_strategy.py` |
| MACD+DMI | ORCL 日线 | MACD 方向 + DMI 趋势强度双确认 | `test_93_macd_dmi_simple_strategy.py` |
| 水位线交叉 | XAUUSD M15 | MACD 与自定义水位线的交叉期望 | `test_0117_1128_macd_waterline_cross_expectator.py` |
| MAMCD | XAUUSD M15 | MA 平滑版 MACD 的变体参数化 | `test_0206_0533_mamacd.py` |

## 深读一：MACD Sample——MT5 官方模板的零轴哲学

MetaTrader 5 安装完自带的第一个 EA 就叫 MACD Sample。[test_0116_1107_macd_sample.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0116_1107_macd_sample.py) 是它的忠实移植，入场信号浓缩了全部零轴哲学——**做多只在零轴下方接金叉**，还要过三道关：

```python
def _long_open_signal(self):
    macd_now = float(self.macd.macd[0])
    macd_prev = float(self.macd.macd[-1])
    signal_now = float(self.macd.signal[0])
    signal_prev = float(self.macd.signal[-1])
    ema_now = float(self.ema[0])
    ema_prev = float(self.ema[-1])
    return (
        macd_now < 0.0                       # 金叉必须发生在零轴下方
        and macd_now > signal_now
        and macd_prev < signal_prev
        and abs(macd_now) > self._open_level()   # MACD 距零轴至少 3 pips
        and ema_now > ema_prev               # 26 期 EMA 必须向上
    )
```

为什么是零轴下方？零轴下的金叉意味着"下跌动能衰减处的反转"，位置低、赔率好；零轴上的金叉则是"强势中的更强"，位置高、容易接到顶部。再加 EMA26 斜率同向，等于把动能反转与趋势方向两个独立证据都凑齐。出场同样分层：50 pips 固定止盈、30 pips 追踪止损、反向交叉强制离场。工程上还有个值得抄的细节：策略用 `warmup = max(ma_trend_period + 5, 35)` 根 K 线做指标预热，前 35 根一律不交易——EMA 和信号线的初始值需要一段历史才能收敛，预热期不足时头几个交叉信号基本是假的。

**诚实的基线**：3 个月 XAUUSD M15，107 笔交易，48 胜 59 负（胜率 44.86%），终值 998,080.30（-0.19%），盈利因子 0.60。连官方模板都亏——这不是移植错误，断言把每个数字钉死了。注意信号统计里离场信号（161 + 134 个）远多于入场信号（54 + 53 个）：官方模板对"什么时候走"比"什么时候进"讲究得多，这本身就是一堂风控课。

## 深读二：MACD Cross——裸交叉 + 永远在场

把所有过滤器拆掉会怎样？[test_0163_1327_macd_cross.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0163_1327_macd_cross.py) 给出了对照答案：裸的 12/26/9 交叉，**止损即反手（Stop and Reverse）**，仓位永远在场：

```python
self.macd = bt.indicators.MACD(
    self.data.close,
    period_me1=self.p.fast_period,       # 12
    period_me2=self.p.slow_period,       # 26
    period_signal=self.p.signal_period,  # 9
)

diff1 = float(self.macd.macd[-1]) - float(self.macd.signal[-1])
diff2 = float(self.macd.macd[-2]) - float(self.macd.signal[-2])

buy_sig = diff2 < 0 and diff1 > 0      # 用前两根已收 K 线判交叉
sell_sig = diff2 > 0 and diff1 < 0

if self.position:
    if self.position.size > 0 and sell_sig:
        self.close()
        self.sell(size=self.p.lot)      # 平多立开空
        return
    if self.position.size < 0 and buy_sig:
        self.close()
        self.buy(size=self.p.lot)
        return
```

结果：474 笔交易（237 多 237 空，恰好对称），189 胜 284 负（胜率 39.87%），终值 992,770.60（-0.72%），盈利因子 0.88。M15 上的 MACD 交叉密如雨点，每次反手都在磨损点差。把这篇和深读一放在一起看结论自明：**同一颗 MACD，零轴过滤 + 分层出场能守住血条，裸交叉 SAR 则稳定失血**。中间的差距就是"过滤器"三个字的定价。

## 深读三：MACD+KDJ——动量定方向，摆动择时机

中文世界最流行的组合之一：MACD 管趋势、KDJ 管拐点。[test_30_macd_kdj_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_30_macd_kdj_strategy.py) 在浦发银行 22 年日线（2000-2022）上给出了一个**必须写进教材的反面基线**：

```python
# MACD 金叉：方向信号
macd_golden_cross = (self.macd.macd[0] > self.macd.signal[0] and
                     self.macd.macd[-1] < self.macd.signal[-1])
# KDJ 死叉：时机信号
kdj_death_cross = (self.kdj.K[0] < self.kdj.D[0] and
                   self.kdj.K[-1] > self.kdj.D[-1])

if self.marketposition == 0:
    if macd_golden_cross:
        size = int(self.broker.getcash() / data.close[0])   # 全仓买入
        if size > 0:
            self.buy(size=size)
            self.marketposition = 1
    elif kdj_death_cross:
        size = int(self.broker.getcash() / data.close[0])
        if size > 0:
            self.sell(size=size)                            # 全仓做空
            self.marketposition = -1
elif self.marketposition == -1:
    if macd_golden_cross:
        self.close()
        self.marketposition = 0
elif self.marketposition == 1:
    if kdj_death_cross:
        self.close()
        self.marketposition = 0
```

信号设计本身没错：MACD 金叉开多、KDJ 死叉平多（开空/平空对称），"慢指标定方向、快指标掐时机"的分工在逻辑上完全成立。致命的是仓位那一行——`int(cash / close)` **全仓进出**：赚的时候全仓赚，错的时候也全仓错，且空头同样全仓。基线：212 笔交易，100,000 本金做到终值 5,870.49，最大回撤 98.63%。同一个信号引擎，把 sizing 从全仓改成固定比例，命运就完全不同——这份"惨案基线"被断言原样保存，正是为了随时可复现地演示：**仓位管理不是可选项，它是策略的一部分**。

## 其余策略，快速点将

- **Digital MACD**（`test_0275`）：用两组固定系数的 FIR 数字滤波器替代 EMA 对，差值再除以 point 得到 MACD 线——把信号处理视角引入指标构造的代表。
- **XMACD**（`test_0324`）：一个 EA 四种信号模式（线叉/零轴穿越/两线斜率反转），是研究"信号定义敏感性"的天然实验台。
- **Simple MACD**（`test_0231`）：完全不交叉，MACD 值升即持多、降即持空——把 MACD 当趋势斜率计而非交叉器。
- **MACD EA 慢周期版**（`test_0036`）：120/260/90 的"慢速 MACD"过滤噪音，配保本移动与部分止盈。
- **柱形态版 MACD**（`test_0049`）：识别柱状图峰谷后的反转确认形态再入场，把柱状图当形态学素材。

## 一条命令跑起来

```bash
# 整个 trend_following 分类（300+ 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/trend_following/ -v

# 只跑 MT5 官方 MACD Sample
pytest tests/functional/strategies/trend_following/test_0116_1107_macd_sample.py -v
```

MACD 这类多指标策略最容易在"当根值还是上一根值"上出错——测试统一用 `[-1]`/`[-2]` 已收 K 线判定交叉，并用双引擎对拍与指标断言守住这条底线。

## 为什么在这个项目上研究 MACD

MACD 的每个组件都能换：均线类型、周期、信号定义、过滤条件、仓位规则——组合空间极大，最怕在不可复现的回测里自欺。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 提供的正是对照实验的环境：纯 Python 引擎比原版快 46%，1,152 个策略回归测试几分钟跑完；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，23 个 MACD 变体的参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略钉死的指标断言基线，保证你优化的确实是策略，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
