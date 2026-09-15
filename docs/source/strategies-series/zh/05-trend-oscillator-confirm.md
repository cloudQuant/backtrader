# 单指标会骗人，确认器会吗？——振荡器与 K 线确认的趋势入场

> 量化策略图鉴 · 第 05 篇 · 分类 `trend_following`（约 53 个策略）· 2026-09-02

每个入门者都经历过均线金叉的死法：信号出现，追进去，行情原地掉头，止损，再信号，再掉头——震荡市里单指标信号像坏掉的转向灯。老手的药方朴素得可疑：**再加一个指标**。一个管方向，一个管时机；或者让 K 线形态先走出反转的样子，再由振荡器出具"超买超买"的旁证。这就是"确认器"（confirmator）逻辑——它不能预言未来，但能要求证据链更长。

本篇解读 `trend_following` 分类下约 53 个确认型策略：38 个振荡器确认（CCI、RSI、TRIX、Schaff 趋势循环……）加 15 个 K 线形态确认（吞没、启明星、乌云盖顶、锤子……）。数据统一为 XAUUSD M15、2025-12-03 至 2026-03-10 的 6,129 根 K 线——同一考场，谁的证据链有效一目了然。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| MA2CCI | XAUUSD M15 | EMA 定方向 + CCI 穿零定时机 | `test_0063_0686_ma2cci.py` |
| Woodies CCI | XAUUSD M15+H4 | 快慢双 CCI 云带翻转 | `test_0082_0887_cci_woodies.py` |
| Schaff 趋势循环（WPR） | XAUUSD M15+H4 | WPR 差值双重随机化成 STC 色环 | `test_0104_1019_color_schaff_wpr_trend_cycle.py` |
| Schaff 趋势循环（TRIX） | XAUUSD M15+H4 | 同框架换 TRIX 输入 | `test_0105_1020_color_schaff_trix_trend_cycle.py` |
| Schaff 趋势循环（RSI） | XAUUSD M15+H4 | 同框架换 RSI 输入 | `test_0107_1022_color_schaff_rsi_trend_cycle.py` |
| RSI Expert | XAUUSD M15 | RSI 阈值回归 + 阶梯追踪止损 | `test_0027_0286_rsi_expert.py` |
| Dual TRIX | XAUUSD M15 | 快慢 TRIX 双线交叉 | `test_0128_1193_dual_trix.py` |
| RSI + CCI | XAUUSD M15 | 双振荡器互证 | `test_0149_1285_rsi_cci.py` |
| T3 TRIX | XAUUSD M15 | T3 平滑版 TRIX | `test_0276_1106_t3_trix.py` |
| 吞没 + CCI | XAUUSD M15 | 吞没形态 + CCI 超卖/超买确认 | `test_0152_1308_engulfing_cci.py` |
| 吞没 + Stoch | XAUUSD M15 | 吞没形态 + 随机指标确认 | `test_0153_1309_engulfing_stoch.py` |
| 启明星 + Stoch | XAUUSD M15 | 启明星/黄昏星 + %D 位置确认 | `test_0154_1310_morningstar_stoch.py` |
| 启明星 + RSI | XAUUSD M15 | 同形态换 RSI 确认 | `test_0155_1313_morningstar_rsi.py` |
| 乌云盖顶 + MFI | XAUUSD M15 | 乌云/刺透 + MFI 资金流确认 | `test_0157_1315_darkcloud_mfi.py` |
| 锤子 + CCI | XAUUSD M15 | 锤子线 + CCI 确认 | `test_0161_1325_hammer_cci.py` |

## 深读一：MA2CCI——均线给方向，CCI 给时机

[test_0063_0686_ma2cci.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0063_0686_ma2cci.py) 是"确认器"思想的教科书实现：EMA(10)/EMA(37) 交叉声明方向，CCI(39) 上穿/下穿零轴声明动量启动，**两者同根 K 线同时成立**才入场；止损取 `max(ATR(3), 15 点)`，仓位按 2% 风险反推：

```python
if (maf > mas and maf_p <= mas_p) and (icc > 0 and icc_p <= 0):
    entry = float(self.data.close[0])
    stop = entry - max(atr, min_indent)
    size = self._calc_size(entry, stop)
    if size > 0:
        self.signal_count += 1
        self._stop_price = round(stop, self.p.price_digits)
        self.order = self.buy(size=size)
        return
if (maf < mas and maf_p >= mas_p) and (icc < 0 and icc_p >= 0):
    entry = float(self.data.close[0])
    stop = entry + max(atr, min_indent)
    size = self._calc_size(entry, stop)
    if size > 0:
        self.signal_count += 1
        self._stop_price = round(stop, self.p.price_digits)
        self.order = self.sell(size=size)
```

**诚实的回测结果**：双重门槛把 6,053 根 K 线压缩成 34 笔交易（14 多 20 空），但只对了 7 笔，终值 822,600.53——**亏 17.7%**。这是确认器逻辑必须直面的另一面：条件越苛刻，信号越稀、越迟；当 CCI 穿零与均线交叉终于会师时，波段往往已走完一半。确认器减少假信号，也让你系统性地迟到。测试把这 34 笔钉死成基线——它不是反面教材，是"证据链成本"的计量样本。

工程上值得抄走的是 `_calc_size`：`risk_cash / (|entry − stop| × 100)` 反推手数、按 `lot_step` 取整、夹在 `lot_min/lot_max` 之间——把"每笔风险 2%"落成三行可复用的代码。

## 深读二：Woodies CCI——一个指标的社区进化史

经典 CCI(14) 在 Ken Wood 的社区手里进化成了一整套体系：多条不同周期、不同适用价格的 CCI 构成"云带"。[test_0082_0887_cci_woodies.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0082_0887_cci_woodies.py) 移植的版本用快 CCI(6) 与慢 CCI(14)，都作用于**中价** `(high+low)/2`（MT5 枚举 `fast_price=4`），信号在 H4 周期计算、M15 执行：

```python
# BUY: transition from bearish (up < dn) to bullish (up >= dn)
if up_cur >= dn_cur and up_prev < dn_prev:
    if self.p.buy_pos_open: BO = True
    if self.p.sell_pos_close: SC = True

# SELL: transition from bullish (up > dn) to bearish (up <= dn)
if up_cur <= dn_cur and up_prev > dn_prev:
    if self.p.sell_pos_open: SO = True
    if self.p.buy_pos_close: BC = True
```

快线上穿慢线开多、下穿开空，还留了 `invert` 开关交换两线角色。这段数据上它交易 76 笔、胜率 47.37%、PF 1.274、终值 1,000,687.00，Sharpe 5.34、最大回撤仅 0.077%——本篇样本里风险调整后最体面的一个。单看 CCI 是振荡器，快慢两条 CCI 相减就成了**动量的动量**，这和 MACD 对均线做的事如出一辙：确认器的本质，是给原始信号加一阶导数。

顺带一提文件里的 `_applied_price`：把 MT5 的 `ENUM_APPLIED_PRICE`（0-6）逐项映射成收盘/开盘/高中/低/中价/典型价/加权价——移植 MQL 指标时逃不掉的细节，仓库里已经写好了模板。

## 深读三：乌云盖顶 + MFI——K 线也要"证据链"

K 线形态是最古老的趋势入场语言，也是噪声最大的。本仓库 15 个 K 线确认策略给了系统答案：形态 + 振荡器双门槛。[test_0157_1315_darkcloud_mfi.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0157_1315_darkcloud_mfi.py) 的规则对称而克制——**乌云盖顶做空需 MFI > 60、刺透线做多需 MFI < 40**，出场为 MFI 穿 70/30（MFI 周期 12）：

```python
def _is_dark_cloud_cover(self):
    o2, h2, c2 = float(self.data.open[-2]), float(self.data.high[-2]), float(self.data.close[-2])
    o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
    avg = self._avg_body()                    # 近 5 根 K 线平均实体
    mid2 = (o2 + c2) / 2.0
    cavg = float(self.close_avg[-1])
    return ((c2 - o2) > avg and               # 前一根是大阳线
            c1 < c2 and c1 > o2 and           # 当根收盘扎进前根实体
            mid2 > cavg and                   # 且发生在均线上方
            o1 > h2)                          # 当根跳空高开

if self._is_piercing_line() and mfi0 < self.p.mfi_entry_long:    # MFI < 40
    self.buy(size=self.p.lot)
    return
if self._is_dark_cloud_cover() and mfi0 > self.p.mfi_entry_short:  # MFI > 60
    self.sell(size=self.p.lot)
```

注意形态定义里没有一个硬编码的点数：实体大小与"上方"都用 SMA(5) 统计化——只有"有意义的 K 线"才配叫形态。结果也足够极端：**整段三个月行情只触发 1 笔交易**（1 胜 0 负，终值 1,000,031.10）。双门槛几乎不开枪，这是确认逻辑的极限形态：你要稀疏到什么程度，才肯为一次入场付费？

## 其余策略，快速点将

- **RSI Expert**（`test_0027`）：RSI(14) 上穿 20 做多、下穿 60 做空，15 点追踪止损每 5 点步进；272 笔、119 胜 153 负、终值 998,052.80——单指标高频对照样本。
- **Color Schaff WPR Trend Cycle**（`test_0104`）：把 WPR(23/50) 的差值当 MACD 用，经"随机化→平滑→再随机化→再平滑"得 STC，映射到 8 色状态机，颜色回落触发交易；同框架还有 TRIX/RSV/RSI/MACD/MFI 变体（`test_0105`-`test_0109`）。
- **Dual TRIX**（`test_0128`）：TRIX(5)/TRIX(14) 双线交叉——三重平滑 EMA 的变化率，天生抗噪。
- **吞没 + CCI**（`test_0152`）：看涨吞没需 CCI < −50、看跌吞没需 CCI > 50；35 笔、终值 1,000,011.10。
- **启明星 + Stoch**（`test_0154`）：三根 K 线的启明星/黄昏星，还需 %D 从 <30 或 >70 起步；同形态另有 RSI/MFI 确认版（`test_0155`/`test_0156`）。
- **同模板全家桶**：锤子、孕线、相逢线 × CCI/Stoch/MFI（`test_0161`/`test_0167`/`test_0160` 等）——15 个 K 线确认策略共享同一套统计化形态定义，换的只是确认器。

## 一条命令跑起来

```bash
# 整个 trend_following 分类（runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/trend_following/ -v

# 只跑乌云盖顶 + MFI
pytest tests/functional/strategies/trend_following/test_0157_1315_darkcloud_mfi.py -v
```

每个测试都会在向量化（`runonce=True`）与事件驱动（`runonce=False`）两种引擎模式下各跑一遍并比对指标——引擎改版若引入偏差，这里第一时间报警。

## 为什么在这个项目上研究振荡器与 K 线确认

"形态 + 确认器"是典型的组合爆炸问题：15 种形态 × 5 种振荡器就是 75 个变体，人工逐个调通再比对几乎不可能。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
