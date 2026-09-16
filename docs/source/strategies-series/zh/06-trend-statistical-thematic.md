# 把市场装进状态机：HMM、数字滤波与黄金/宏观/加密主题趋势

> 量化策略图鉴 · 第 06 篇 · 分类 `trend_following`（约 57 个策略）· 2026-09-02

"现在是牛市还是熊市？"——人类交易员靠盘感回答，统计模型靠状态机回答。本篇是这个系列里最"跨界"的一集：一边是隐藏马尔可夫模型（HMM）、Burg 自回归、FIR 数字滤波器这些听起来像信号处理课本的东西；另一边是朴素到近乎固执的规则——"价格在 200 日线上方才持有"。约 57 个策略里，37 个属于统计模型，20 个属于主题趋势（黄金、宏观、加密风格）。

反直觉的结论先放在这里：在这个仓库的回归基线里，最复杂的 HMM 两年只做 6 笔交易，最简单的风险平价 18 年赚 23.6%——模型复杂度和盈利能力没有必然关系。但前者教你"市场状态"如何变成可计算的量，后者教你组合层面对趋势的另一种用法。两边都值得读。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 黄金 HMM 趋势跟踪 | XAUUSD 日线 2024-2025 | 高斯 HMM 识别 BULL/BEAR/NEUTRAL 状态 | `test_0002_gold_hmm_trend_following.py` |
| 瞬时趋势滤波 | XAUUSD M15+H4 | Ehlers 瞬时趋势线，alpha=0.07 | `test_0099_0989_instantaneous_trendfilter.py` |
| 分形自适应均线 MBK | XAUUSD M15+H4 | 用分形维度自适应的 FRAMA | `test_0102_1002_fractalama_mbk.py` |
| Burg 外推器 | XAUUSD M15 | Burg 自回归预测高低点 | `test_0211_0551_burg_extrapolator.py` |
| FATL/SATL OsMA | XAUUSD M15+H12 | 39/65 阶 FIR 低通滤波器差值 | `test_0258_1048_fatl_satl_osma.py` |
| 鳄鱼指标（Alligator） | XAUUSD M15 | Bill Williams 颚/齿/唇三条 SMMA | `test_0170_1348_alligator.py` |
| 鳄鱼极简版 | XAUUSD M15 | 同思想的轻量参数化 | `test_0183_0165_alligator_simple_v1_0.py` |
| Laguerre 滤波 | XAUUSD M15 | Laguerre 滤波器去噪 | `test_0097_0977_laguerrefilter.py` |
| 改进最优椭圆滤波 | XAUUSD M15 | 最优椭圆滤波器变体 | `test_0259_1051_modified_optimum_elliptic_filter.py` |
| MAMA | XAUUSD M15 | Mesa 自适应均线 | `test_0297_1233_mama.py` |
| 风险平价趋势 | 金/银/日元/瑞郎/美债 日线 | 逆波动率权重 + 200 日线闸门 | `test_0003_risk_parity_trend.py` |
| 宏观趋势跟踪 | GLD+IVV+DBC+IEF 日线 | 0.7 市场分 + 0.3 宏观分择时黄金 | `test_0008_trend_following_macro_strategy.py` |
| 加密风格趋势跟踪 | XPDUSD 日线 | MA 状态 + Donchian 突破 + 波动率目标 | `test_0009_crypto_trend_following_strategy.py` |
| 趋势因子 | 多资产日线 | 趋势强度的横截面表达 | `test_0012_trend_factor.py` |
| 金叉/死叉反转 | XAUUSD 日线 | 经典均线交叉的严肃参数化 | `test_0175_golden_cross.py` / `test_0174_death_cross_reverse.py` |

## 深读一：黄金 HMM 趋势跟踪——市场状态变成可交易信号

[test_0002_gold_hmm_trend_following.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0002_gold_hmm_trend_following.py) 是全篇最手写的测试（431 行，非模板生成），也是"状态机"思想的完整落地。它对黄金日线（2024-01-01 至 2025-12-31）做三件事：

**第一，滚动拟合。** 用 252 个交易日窗口、每 21 天重训一次 `GaussianHMM(n_components=3, covariance_type="full")`，特征只有两个——对数收益与 20 日年化波动率。模型输出 3 个隐藏状态后，按训练集上的平均收益**贴标签**：均值最高的是 BULL，最低的是 BEAR，剩下的是 NEUTRAL。

**第二，三重置信度门。** 光有状态不够，还要确信：

```python
vol_factor = min(target_volatility / max(float(current_row["volatility_20"].iloc[0]), 1e-6),
                 max_target_percent / max(base_target_percent, 1e-6))
dynamic_target = min(max_target_percent, base_target_percent * current_confidence * vol_factor)
if current_confidence < state_persistence_min or persistence < state_persistence_min or consistent < 0.5:
    dynamic_target = 0.0
```

仓位 = min(0.10, 0.03 × 状态置信度 × 波动率目标因子)；而"状态后验概率、转移矩阵对角线（状态黏性）、连续 3 日同状态"三个置信度任一低于 0.7，目标仓位直接归零——宁可错过，不可误判。

**第三，保本武装。** 浮盈一旦达到 8%，止损线从 −3% 上移到 0；此外还有状态反转平仓与 NEUTRAL 状态减半仓。**回测结果**：两年 245 根日线只做 6 笔（3 胜 3 负），终值 1,000,059.99——含 0.02% 佣金后约打平。工程上两处值得学：`pytest.importorskip("hmmlearn")` 让可选依赖缺席时整模块优雅跳过；HMM 特征在 pandas 里预计算、经自定义 `PandasData` 行注入策略，回测引擎保持纯净。

## 深读二：FATL/SATL——把趋势线做成数字滤波器

均线是"滤波器"的粗糙形态，俄罗斯技术分析学派干脆按频域设计指标：FATL（Fast Adaptive Trend Line）是 39 项固定系数的 FIR 低通滤波器，SATL（Slow）是 65 项——系数直接写死在数组里（FATL 首项 0.4360409450，SATL 首项 0.0982862174），无任何参数可调。[test_0258_1048_fatl_satl_osma.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0258_1048_fatl_satl_osma.py) 在 H12 周期上计算两者之差构成 OsMA 振荡器，拐头即入场：

```python
def compute_fatl_satl_osma(frame, point=0.01):
    price = frame['close'].to_numpy(dtype=float)
    values = np.full(len(frame), np.nan, dtype=float)
    min_rates_total = int(max(len(FATL_COEFFS), len(SATL_COEFFS)))
    for idx in range(min_rates_total - 1, len(frame)):
        fatl = float(np.dot(FATL_COEFFS, price[idx - np.arange(len(FATL_COEFFS))]))
        satl = float(np.dot(SATL_COEFFS, price[idx - np.arange(len(SATL_COEFFS))]))
        values[idx] = (fatl - satl) / point     # 快慢趋势的背离程度
    out = frame.copy()
    out['fatl_satl_osma'] = values
    return out.dropna(subset=['fatl_satl_osma'])
```

FIR 卷积被一行 `np.dot` 向量化——指标即数据。**回测结果**同样诚实：16 笔交易只赢 3 笔，终值 992,663.99。滤波器把噪声滤掉了，也把这段行情的趋势滤掉了；65 根 H12 的暖机窗口就要吃掉样本的一大半。它留在测试库里的价值不是收益，而是"零参数指标"这个流派的完整参照。

## 深读三：风险平价 + 趋势闸门——黄金的"避险组合"

主题趋势策略里工程完成度最高的是 [test_0003_risk_parity_trend.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0003_risk_parity_trend.py)。五个资产——金、银、日元强度（1/USDJPY）、瑞郎强度（1/USDCHF）、美债 ETF IEF——对齐到 2008-2025 的共同交易日历，每月末做两件事：按 252 日波动率的倒数分配等风险权重，然后用 200 日均线做闸门，价格在下方的资产权重归零、转为现金：

```python
if bool(month_end.loc[dt]):
    vol_row = rolling_vol.loc[dt].dropna()
    if len(vol_row) > 0:
        inv_vol = 1.0 / vol_row
        rp_weights = inv_vol / inv_vol.sum()      # 等风险贡献
        active_weights = {}
        for asset in ASSET_ORDER:
            base_weight = float(rp_weights.get(asset, 0.0))
            signal = float(trend_signal.loc[dt, asset]) if asset in trend_signal.columns else 0.0
            active_weights[asset] = base_weight * signal   # 趋势闸门
        total_active = float(sum(active_weights.values()))
        current_weights.update(active_weights)
        current_cash = max(0.0, 1.0 - total_active)        # 熊市权重让给现金
```

细节见功力：`invert_price_frame` 把 USDJPY 取倒数变成"日元强度"序列时，high/low 必须互换——倒数会反转高低顺序，这种坑只有真做过的人知道。**回测结果**：18 年、4,287 根日线、206 次再平衡、89 笔交易只赢 23 笔（胜率约 26%），终值 1,235,742.09（+23.6%，佣金 0.1%）。又一次，低胜率与正收益并存——趋势闸门把熊市的仓位让给现金，剩下的小亏是门票，少数大波段是奖品。

## 其余策略，快速点将

- **鳄鱼组线**（`test_0170`）：Bill Williams 的 Alligator——颚 SMMA(13) 前移 8、齿 SMMA(8) 前移 5、唇 SMMA(5) 前移 3；唇>齿>颚且三线张口加大多头，颚反穿唇平仓。混沌理论的遗产，参数其实相当保守。
- **瞬时趋势滤波**（`test_0099`）：Ehlers 用希尔伯特变换思想构造的 Instantaneous Trendline，`alpha=0.07`，trigger 线穿越 trend 线即反转。
- **分形自适应均线**（`test_0102`）：FRAMA 用高低点区间的分形维度动态调整平滑速度——市场越"分形"，均线越慢。
- **Burg 外推器**（`test_0211`）：对 200 根历史 K 线拟合 Burg 自回归（`model_order=0.37`）外推短期高低点，结合 160 点最小利润/130 点最大损失阈值入场。
- **宏观趋势跟踪**（`test_0008`）：黄金多空平三态由 0.7×市场分（金 SMA200 + 股票动量 252）+ 0.3×宏观分（DBC 通胀动量 126 + IEF 利率 SMA252）决定，阈值 ±0.3。
- **加密风格趋势跟踪**（`test_0009`）：MA 50/200 定状态 + Donchian(50) 突破触发 + ATR(14)×2.5 止损、单笔风险 2% 的波动率目标仓位——数据用钯金日线作高波动代理。

## 一条命令跑起来

```bash
# 整个 trend_following 分类（runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/trend_following/ -v

# 只跑黄金 HMM 趋势跟踪
pytest tests/functional/strategies/trend_following/test_0002_gold_hmm_trend_following.py -v
```

每个测试都会在向量化（`runonce=True`）与事件驱动（`runonce=False`）两种引擎模式下各跑一遍并比对指标——引擎改版若引入偏差，这里第一时间报警。

## 为什么在这个项目上研究统计模型与主题趋势

HMM 要滚动重训、FIR 要长暖机、多资产要日历对齐——这类策略的回测是计算密集且极易被实现细节污染的。这正是 [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 的着力点：纯 Python 引擎比原版快 46%，1,152 个策略回归测试跑完只要几分钟；装上 C++ 后端（`pip install back-trader-cpp`）可获得中位 128 倍加速，参数扫描从"过夜任务"变成"喝口咖啡"。而每个策略的指标断言基线，保证你优化的是策略本身，而不是被引擎的数值漂移误导。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
