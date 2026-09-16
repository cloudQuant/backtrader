# 经典量化规则：Double 7s、连跌计数与波动率冲击——把研究论文钉成断言

> 量化策略图鉴 · 第 11 篇 · 分类 `mean_reversion`（约 30 个策略）· 2026-09-02

量化圈流传着一批"口口相传"的简单规则：Larry Connors 在《Short Term Trading Strategies That Work》里写下的 Double 7s、老交易员念叨的"连跌三天就买"、学术论文里的波动率均值回归。Connors 那本书 2009 年出版，随后十年被无数博客转述、删改、重新参数化，以至于今天你搜"Double 7s"能搜到七八个互相矛盾的版本。它们的问题不是没用，而是**传着传着就变了形**——参数漂移、条件增删、样本 cherry-pick，最后没人说得清原始规则到底赚不赚钱。

治这个病的办法只有一个：把规则原样冻进代码，把结果钉成断言。本篇解读 mean_reversion 分类下 30 余个源自研究论文规格（文件头标注 `source_spec`，指向 `research_papers_gold/strategy_specs/mean_reversion/` 下的规格文档）的经典规则回测。它们共享同一套实验纪律：18 年 XAUUSD 日线（2008-2025）、0.02% 佣金、100 万初始资金、期货式合约设定，唯一变化的是规则本身——这让"规则之间的比较"第一次有了可比性。规则简单到一行能说完，验证却一丝不苟——这正是"经典"该有的待遇。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Double 7s | XAUUSD D1 2008-2025 | 200 日均线上方的 7 日新低买入，7 日新高卖出 | `test_0002_double_7s_mean_reversion.py` |
| Double N（黄金版） | XAUUSD D1 | 同思想参数化：n_period=7，趋势过滤 200 日 | `test_0010_double_n_gold.py` |
| 连跌计数 | XAUUSD D1 | 连跌 3-5 天（日跌幅<-0.1%）买入，持有 1 天 | `test_0008_consecutive_down_days.py` |
| 波动率冲击 | XAUUSD D1 | 25 日波动率百分位<60 买入，>80 或持有 5 日离场 | `test_0019_volatility_mean_reversion.py` |
| 周度回归轮动 | XAUUSD D1 | 收盘区间位置<0.3 且趋势向上买，>0.7 卖 | `test_0025_weekly_mean_reversion_rotation.py` |
| 跨市场回归 | GLD/GDX/XAGUSD/IEF D1 | 周收益排名轮动多空 | `test_0027_mean_reversion_across_markets.py` |
| 假日反转 | XAUUSD D1 | 假日周 + 负动量买入，持有 4 天 | `test_0005_holiday_reversal.py` |
| 效率比率回归 | XAUUSD D1 | ER(10)<50 的震荡市 + RSI(2)<10 买入 | `test_0041_efficiency_ratio_mean_reversion.py` |
| N 日离场 | XAUUSD D1 | ROC 百分位极端超卖 + 上升趋势，固定持有 | `test_0018_n_day_exits.py` |
| 连续低 RSI | XAUUSD D1 | 连创 50 日新低且 RSI(2)<10 买入 | `test_0029_consecutive_low_rsi.py` |
| 最小利润门槛 | XAUUSD D1 | z-score 深度负偏离入场，回归足够才离场 | `test_0037_min_profit_mean_reversion.py` |
| 商品均值回归 | XAUUSD D1 | z-score 跌破负阈值买入，回到零附近离场 | `test_0013_commodity_mean_reversion.py` |
| 在线均值回归 | XAUUSD D1 | 价格跌破滚动均值容忍带买入 | `test_0032_online_mean_reversion.py` |

## 深读一：Double 7s——Connors 规则的黄金版体检

Connors 的原始规则针对标普 500：**价格站在 200 日均线上方、收盘创 7 日新低时买入；收盘创 7 日新高时卖出**。逻辑是"上升趋势中的短期恐慌是礼物"。[test_0002_double_7s_mean_reversion.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0002_double_7s_mean_reversion.py) 把它原样搬到黄金日线：

```python
out['sma'] = out['close'].rolling(sma_period).mean()      # 200 日趋势过滤
out['n_day_low'] = out['close'].rolling(n_low).min()      # 7 日低点
out['n_day_high'] = out['close'].rolling(n_high).max()    # 7 日高点

out['buy_signal'] = ((out['close'] > out['sma']) &
                     (out['close'] <= out['n_day_low'])).astype(float)
out['sell_signal'] = (out['close'] >= out['n_day_high']).astype(float)
```

```python
        if self.position:
            if float(self.data.sell_signal[0]) > 0.5:
                self.pending_order = self.close()   # 收盘创 7 日新高，离场
            return
```

**回测结果**（计入 0.02% 佣金）：18 年 148 笔交易，胜率 **66.89%**，终值从 100 万涨到 **2,138,567.90**，夏普 0.566——代价是 30.35% 的最大回撤。高胜率、无止损、吃趋势内回调，这正是 Connors 学派的招牌画像：他反复强调短期均值回归**不要设止损**，用时间离场（这里是 7 日新高）代替价格止损，避免在最恐慌的点位被洗出局。30% 的回撤就是这份哲学的账单，能否接受因人而异。另注意 `close <= rolling(7).min()` 用的是"含当根"的新低，差一个 shift 就是另一个策略。旁边的 [test_0010_double_n_gold.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0010_double_n_gold.py) 是同一思想把 7 换成可调 N 的变体，断言结果与 0002 完全一致（148 笔、终值 2,138,567.90）——两份独立实现互为对照，规则没有在搬运中走样。

## 深读二：连跌计数——统计优势的最低配置

"连跌 N 天买入"可能是最古老的均值回归直觉。[test_0008_consecutive_down_days.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0008_consecutive_down_days.py) 的实现只有一个循环：

```python
out['daily_return'] = out['close'].pct_change()
out['is_down_day'] = (out['daily_return'] < threshold).astype(float)   # threshold=-0.001
out['consecutive_down'] = 0
count = 0
for i in range(len(out)):
    if out['is_down_day'].iloc[i] > 0.5:
        count += 1
    else:
        count = 0
    out.loc[out.index[i], 'consecutive_down'] = count

# 连跌进入 [3, 5] 区间才入场
out['entry_signal'] = ((out['consecutive_down'] >= min_days) &
                       (out['consecutive_down'] <= max_days)).astype(float)
```

两个容易被忽略的规格：**下跌的定义带阈值**（-0.1%，不是 <0），微小波动不算数；**上限 5 天**——连跌超过 5 天说明可能有真实的坏消息，不接飞刀。持有期仅 1 天。结果：203 笔，胜率 56.65%，终值 1,167,207.74。胜率只比抛硬币高一点，但盈亏结构让它在 18 年里净赚 16.7%（终值 1,167,207.74）——均值回归策略的典型指纹：**优势很薄，靠次数和不对称离场堆积**。

## 深读三：效率比率——Kaufman 教你先问"这是什么市"

同样的超卖信号，在趋势市是刀口舔血，在震荡市才是送钱。Perry Kaufman 的效率比率（Efficiency Ratio）度量"每单位路径走了多远净距离"，是区分两种市场最经济的尺子。[test_0041_efficiency_ratio_mean_reversion.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0041_efficiency_ratio_mean_reversion.py)：

```python
def calculate_efficiency_ratio(close, period=10):
    total_change = abs(close - close.shift(period))       # 净位移
    daily_change = abs(close.diff())
    sum_daily_change = daily_change.rolling(window=period).sum()   # 路径长度
    er = 100 * total_change / sum_daily_change.replace(0, np.inf)
    return er

# ER < 50（震荡市）且 RSI(2) < 10（极端超卖）才入场
out['low_er'] = (out['er'] < er_threshold).astype(float)
out['entry_signal'] = ((out['rsi'] < rsi_oversold) &
                       (out['low_er'] > 0.5)).astype(float)
```

直线上涨时 ER 趋近 100，随机游走时趋近 0。加上这道闸门后，548 笔交易胜率 53.83%，终值 **2,700,065.50**——比不加过滤的裸 RSI 策略好了不止一个档次。ER 的妙处还在于它不是二选一的开关，而是一个连续的"市场质量"刻度：Kaufman 后来的 KAMA（Kaufman Adaptive Moving Average）正是用 ER 去动态调节均线速度——趋势市跑得快、震荡市挪得慢。同一个比率，既能当过滤器（本篇），也能当调速器（KAMA），这是指标设计里"一鱼两吃"的典范。对比第 10 篇里胜率 48% 的蜡烛组合，你会看到"什么时候不交易"往往比"交易什么形态"更值钱。

## 其余策略，快速点将

- **波动率冲击**（`test_0019`）：波动率百分位低于 60 买入、高于 80 离场，"低波动溢价"的直接兑现——终值 3,296,979.50，本组最能赚钱的一员。
- **周度回归轮动**（`test_0025`）：用收盘在 5 日区间的位置（<0.3 超卖）替代指标，59.77% 胜率、终值 1,479,976.06。
- **跨市场轮动**（`test_0027`）：四资产周收益排名做多弱者做空强者，终值 437,162.57——**亏掉一半以上**的反面教材，提醒你"价差回归"跨市场未必成立；排名动量与均值回归两股力量在此互相打架。
- **假日反转**（`test_0005`）：假日周 + 负动量买入，57.14% 胜率、终值 1,381,948.96，日历效应的温和证据——流动性稀薄的假日周过后，价格倾向于修复。
- **连续低 RSI / N 日离场 / z-score 家族**（`test_0029` / `test_0018` / `test_0013`）：同一"极端偏离 + 时间离场"骨架的三种偏离度量，适合做横向对比。

## 一条命令跑起来

```bash
# 整个分类
pytest tests/functional/strategies/mean_reversion/ -v

# 只跑 Double 7s
pytest tests/functional/strategies/mean_reversion/test_0002_double_7s_mean_reversion.py -v
```

这些测试全部带指标断言基线（终值、胜率、夏普、回撤逐项锁定），改任何一个参数——比如把连跌上限从 5 改成 7——断言立刻失败，逼你直面"规则变形"的后果。

## 为什么在这个项目上研究经典规则

经典规则的价值取决于复现的纪律。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用工程手段固化这份纪律：1,152 个策略回归测试、runonce/runnext 双模式对拍、指标断言基线，谁也别想"顺手调个参数"；纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速——把 Double 7s 的 N 从 2 扫到 30、每个配置跑完整 18 年，只是几分钟的事。论文规格 → 代码 → 断言，这条流水线正是量化研究该有的样子。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
