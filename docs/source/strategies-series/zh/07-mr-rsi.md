# RSI 超买超卖族：Connors RSI2 与它的 67 个变体

> 量化策略图鉴 · 第 07 篇 · 分类 `mean_reversion`（331 个策略）· 2026-09-02

1978 年，Wells Wilder 在《New Concepts in Technical Trading Systems》里发明 RSI 时，给出的标准用法是：14 期，高于 70 超买——考虑卖出，低于 30 超卖——考虑买入。三十年后，Larry Connors 把这套规矩掀了个底朝天：把周期砍到 2，阈值砍到 5，而且**只在上升趋势里买超卖**。

这是对"超卖"一词的彻底重新解读。在 Wilder 的框架里，RSI 跌到 20 意味着跌势凶猛、应该回避；在 Connors 的框架里，一个长期趋势向上的品种出现短期的极度超卖，恰恰是趋势内回调的黄金买点——因为均值回归的"均值"，是一条向上的均线。本篇解读 `tests/functional/strategies/mean_reversion/` 下的 RSI 族策略：从经典 RSI2、复合 ConnorsRSI，到双重平滑的 Cronex RSI 与颜色状态机 RSI Histogram。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Connors RSI2（经典版） | XAUUSD D1 2008-2025 | RSI(2)<5 且价在 100 日 SMA 上方做多，RSI 回升穿 30 平仓 | `test_0004_rsi2_mean_reversion.py` |
| ConnorsRSI（复合版） | XAUUSD D1 2008-2025 | RSI(3)+连胜连败 RSI(2)+百分位排名(100) 三合一，200 日趋势上方挂限价买 | `test_0020_connorsrsi_mean_reversion.py` |
| ConnorsRSI（简化版） | XAUUSD D1 | CRSI<40 进、>60 出，20 日 SMA 趋势过滤 | `test_0015_simple_connorsrsi_sp500.py` |
| Larry Connors RSI2（M15 版） | XAUUSD M15 | RSI(2)<6 且价在 200SMA 上做多、>95 且价在下做空，5SMA 穿越离场 | `test_0134_0488_larry_conners_rsi_2.py` |
| RSI 超卖反转 | XAUUSD D1 | 连续 50 日新低 + RSI(2)<5 做多，持有 5 日离场 | `test_0028_rsi_oversold_reversal.py` |
| 连续新低 RSI | XAUUSD D1 | 连续新低 + RSI(2)<10 入场，固定持有期 | `test_0029_consecutive_low_rsi.py` |
| Improved RSI | GLD D1 2018-2025 | EMA 平滑 RSI 与成交量加权 RSI 取均值，窗口随波动率自适应 | `test_0233_improved_rsi_strategy.py` |
| RSI EA v2 | XAUUSD M15 | 30/70 水平穿越双向开仓 + 移动止损 + 交易时段过滤 | `test_0236_0146_rsi_ea_v2.py` |
| RSI Slowdown | XAUUSD M15/H4 | RSI(2) 触及 90/10 极值且走平（\|ΔRSI\|<1）时反转入场 | `test_0259_0811_rsi_slowdown.py` |
| RSI Histogram | XAUUSD M15/H4 | RSI 按 60/40 阈值染成三色状态，颜色翻转触发交易 | `test_0271_0932_rsi_histogram.py` |
| Cronex RSI | XAUUSD M15/H4 | RSI(25) 双重 SMA 平滑出快慢线，交叉反转 | `test_0289_1072_cronex_rsi.py` |

## 深读一：Connors RSI2——在趋势内买超卖

经典 RSI2 的规则可以浓缩成一句话：**长期趋势向上时，短期超卖就是买点**。仓库实现（[test_0004_rsi2_mean_reversion.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0004_rsi2_mean_reversion.py)）在 XAUUSD 日线上跑了 2008 到 2025 共 17 年：

```python
params = dict(
    rsi_period=2,           # 极短周期：只捕捉两根 K 线内的衰竭
    rsi_buy_threshold=5,    # 阈值不是 30，是 5——极度超卖
    rsi_sell_threshold=30,  # RSI 修复到 30 即离场，不贪
    sma_period=100,         # 趋势过滤：只在 100 日均线上方做多
)

# Entry: RSI 低于买阈值，且收盘价仍在 SMA 上方（趋势内超卖）
out['buy_signal'] = ((out['rsi'] < rsi_buy) &
                     (out['close'] > out['sma'])).astype(float)
# Exit: RSI 回升穿越卖阈值
out['sell_signal'] = (out['rsi'] > rsi_sell).astype(float)
```

两个设计值得咀嚼。其一，`rsi_period=2` 让 RSI 变得极其敏感——两天连跌就能把它打到 5 以下，这正是 Connors 想要的"恐慌计"。其二，`sma_period=100` 是安全带：2008、2013、2021 这类单边崩跌里 RSI(2) 天天贴地，但只要价格在均线下方，信号一个都不会触发。

回测数字（断言钉死的基线）：4,538 根日线、311 笔交易、胜率 67.85%，终值从 100 万做到 1,703,436.24（+70.34%），最大回撤 17.37%，SQN 2.06。这不是暴利策略，但作为一个只有四个参数的规则系统，17 年翻 1.7 倍、三分之二交易赚钱——这就是它被封为短线均值回归教科书的原因。

## 深读二：ConnorsRSI——把三个维度揉成一个振荡器

Connors 后来的进化版 ConnorsRSI（[test_0020_connorsrsi_mean_reversion.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0020_connorsrsi_mean_reversion.py)）不再只看价格动量，而是把三个互补的维度平均成一个复合分数：

```python
price_rsi = _calculate_rsi(close, 3)                        # 价格动量 RSI(3)
streak_rsi = _calculate_rsi(_calculate_streaks(close), 2)   # 连胜/连败天数序列的 RSI(2)
percent_rank = _calculate_percent_rank(close, 100)          # 当前价在 100 日内的百分位
out['crsi'] = pd.concat([price_rsi, streak_rsi, percent_rank], axis=1).mean(axis=1)

# 入场：CRSI 深度超卖 + 距 26 周高点不远（趋势没坏）+ 价在 200 日均线上方
out['setup_signal'] = (
    (out['crsi'] < float(params.get('crsi_entry', 20.0)))
    & (out['days_since_high'] <= float(params.get('recent_high_max_days', 30)))
    & (out['close'] > out['trend_ma'])
).astype(float)
```

`streak_rsi` 是点睛之笔：先数出"连续上涨/下跌天数"序列，再对这个序列算 RSI——它衡量的是**连胜连败本身的衰竭程度**，和价格 RSI 相互印证。入场端还多了一层工程味道：不是市价追入，而是挂**低于昨收 0.3% 的限价单、次日作废**：

```python
limit_price = float(self.data.close[-1]) * (1.0 - float(self.p.entry_discount_pct) / 100.0)
valid_until = current_dt + timedelta(days=1)
self.order = self.buy(size=..., exectype=bt.Order.Limit, price=limit_price, valid=valid_until)
```

结果：17 年只有 38 笔成交（52 次信号中 14 张限价单过期作废——等不到更便宜就放弃），胜率 78.95%，盈利因子 3.38，最大回撤仅 6.42%。信号更挑剔、入场更便宜、回撤更浅，这是"少即是多"的量化样本。

## 深读三：Cronex RSI——给 RSI 做两次平滑

如果说 Connors 的方向是把 RSI 变得更"快"，Cronex RSI（[test_0289_1072_cronex_rsi.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0289_1072_cronex_rsi.py)）则反其道而行：把 RSI 变得更"慢"——先算 RSI(25)，再用 SMA(14) 平滑一次得到快线 `ind`，对 `ind` 再做 SMA(25) 平滑得到慢线 `sign`：

```python
rsi = compute_rsi(price, rsi_period)                      # RSI(25)，Wilder 平滑
ind = smooth_series(rsi, fast_period, xma_method)         # SMA(14) → 快线
sign = smooth_series(ind, slow_period, xma_method)        # SMA(25) → 慢线（对快线再平滑）

# 快线上穿慢线做多，下穿做空（信号在 H4 上评估，M15 执行）
if ind_curr > sign_curr and ind_prev <= sign_prev:
    buy_open = True
```

双重平滑牺牲灵敏度换来极少的信号——3 个多月只有 7 次买入信号、9 笔成交，5 胜 4 负，但盈利因子仍有 2.07。这个测试还是**双周期工程**的好范本：指标在重采样的 H4 框架上计算（368 根信号 K 线），订单在 M15 执行框架（6,129 根）上成交，两套 feed 通过 `resampledata` 挂进同一个 cerebro——想做"高周期信号、低周期执行"的读者可以直接抄这个骨架。

## 其余策略，快速点将

- **Larry Connors RSI2 M15 版**（`test_0134`）：经典规则的非对称版——做多看 RSI(2)<6 + 200SMA 上方，做空看 >95 + 200SMA 下方，5SMA 穿越离场，外加 30/60 点止损止盈；173 笔交易赢下 83 笔。
- **RSI Slowdown**（`test_0259`）：极值 + 走平才入场——RSI(2) 冲到 90 以上且与上一根相差不足 1 时，认定上行动量"熄火"反手做空。
- **RSI Histogram**（`test_0271`）：把 RSI 按 60/40 染成 0/1/2 三色状态，只交易颜色翻转的瞬间，天然去抖。
- **RSI EA v2**（`test_0236`）：30/70 双向开仓 + 移动止损 + 时段控制，128 笔交易 59 胜，是 MT4/MT5 老手熟悉的"指标 EA"形态。
- **连续新低双兄弟**（`test_0028`/`test_0029`）：把"连续创 50 日新低"与 RSI(2) 极值叠加，持有 5 天强制离场——把恐慌兑现成统计优势。

## 一条命令跑起来

```bash
# 整个分类（331 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/mean_reversion/ -v

# 只跑经典 Connors RSI2
pytest tests/functional/strategies/mean_reversion/test_0004_rsi2_mean_reversion.py -v
```

## 为什么在这个项目上研究 RSI 均值回归

RSI 族是参数最敏感的策略家族之一——周期 2 还是 3、阈值 5 还是 10、均线 100 还是 200，每个旋钮都直接改变交易分布，不跑大规模对拍根本分不清"有效"和"运气"。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的用武之地：纯 Python 引擎比原版快 46%，1,152 个策略回归测试全套基线在握；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，扫一遍 RSI 周期×阈值网格从"过夜任务"变成"喝口咖啡"；runonce/runnext 双模式对拍与指标断言基线，保证你比较的是策略差异，而不是引擎的数值漂移。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
