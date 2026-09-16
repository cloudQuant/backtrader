# 情绪策略：恐贪指数、PCR 与 VIX——巴菲特格言的量化版

> 量化策略图鉴 · 第 41 篇 · 分类 `sentiment`（4 个策略）· 2026-09-02

"别人恐惧我贪婪，别人贪婪我恐惧"——巴菲特这句格言人人会背，但"恐惧"怎么量化？CNN 的 Fear & Greed 指数把它压缩成 0-100 的一个数；期权市场用真金白银投票，产出 Put/Call Ratio；VIX 则直接给恐慌定价。三个指标，三种"恐惧计"。

有趣的是三者测的并不是同一种情绪：恐贪指数是动量、广度、波动等七个子指标的合成，偏"状态"；PCR 记录的是期权买方此刻的下注方向，偏"行为"；VIX 是未来 30 天波动的隐含报价，偏"预期"。情绪策略本质上是把这些**慢变量**当作择时过滤器——指标极值一年出现不了几次，所以策略一年也交易不了几回。先剧透一个反直觉的事实：**情绪策略的换手率低到惊人**——11 年数据里最"勤快"的策略也只下单 6 次。

本篇解读 `tests/functional/strategies/sentiment/` 下的 4 个回测。它们共享同一份数据文件（SPY + 三个情绪指标的 CSV），却演示了逆向投资的几种不同打开方式。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 恐贪指数 | SPY + 情绪 2011-2021 | F&G < 10 极度恐惧买入，> 94 极度贪婪卖出 | `test_22_fear_greed_strategy.py` |
| Put/Call Ratio | SPY + 情绪 2011-2021 | PCR > 1.0 恐慌拥挤则买，< 0.45 乐观泛滥则卖 | `test_23_put_call_strategy.py` |
| VIX | SPY + 情绪 2011-2021 | VIX > 35 恐慌买 SPY，< 10 岁月静好时离场 | `test_24_vix_strategy.py` |
| BTC 谷歌趋势 | BTC 周线 + Trends 2018-2020 | 搜索热度突破布林带做多/做空，回归中轨平仓 | `test_33_btc_sentiment_strategy.py` |

## 深读一：恐贪指数——极端才出手

[test_22_fear_greed_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/sentiment/test_22_fear_greed_strategy.py) 的全部交易逻辑只有十几行：

```python
def next(self):
    self.bar_num += 1
    size = int(self.broker.getcash() / self.close[0])

    # Buy when extremely fearful
    if self.fear_greed[0] < self.p.fear_threshold and not self.position:
        if size > 0:
            self.buy(size=size)
            self.buy_count += 1

    # Sell when extremely greedy
    if self.fear_greed[0] > self.p.greed_threshold and self.position.size > 0:
        self.sell(size=self.position.size)
        self.sell_count += 1
```

阈值 `fear_threshold=10`、`greed_threshold=94` 刻意放在标尺两端：0-100 的指数，只在最极端的 10% 区间行动。工程上值得学的是数据接入——情绪指标不是 K 线，测试通过扩展 `GenericCSVData` 把 Put/Call、F&G、VIX 作为三条额外 line 挂进数据流：

```python
class SPYFearGreedData(bt.feeds.GenericCSVData):
    lines = ('put_call', 'fear_greed', 'vix')
    params = (('put_call', 7), ('fear_greed', 8), ('vix', 9))
```

回测结果（2011-2021，SPY）：2,445 根日 K，仅 **6 次买入、2 次卖出**，已平仓 2 笔全胜，终值 280,859.60（年化 11.2%，Sharpe 0.89）。注意最后一笔买入未平仓——"恐惧抄底"之后若贪婪迟迟不来，仓位就一直暴露在市场里，最大回撤 24.3% 就是这期间的代价。11 年 6 次买入也解释了这类策略的统计尴尬：样本太少，胜率 100% 也说明不了什么——2011-2021 恰是美国股市的长牛，"极度恐惧必反弹"更像是牛市的属性而非情绪的规律。换一段 2000-2010 的数据，同样的 10/94 阈值可能给出完全不同的答案。

## 深读二：Put/Call Ratio——期权市场的情绪表决

PCR = 看跌期权成交量 / 看涨期权成交量。比值飙升说明大家在抢购"保险"，比值见底说明大家在裸奔追涨。[test_23_put_call_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/sentiment/test_23_put_call_strategy.py) 用同样的骨架换掉信号线：`PCR > 1.0` 视为恐慌极值买入，`PCR < 0.45` 视为贪婪极值清仓。同一份 SPY 数据上：6 买 3 卖、3 笔已平仓全胜，终值 240,069.35（Sharpe 0.83）。

与恐贪指数对照很有意思：两个指标高度相关（都源自恐慌），买入次数完全相同（6 次），但出场时机不同导致终值差 4 万美元——**情绪策略的 alpha 更多藏在出场规则里**。慢变量的另一个含义是统计样本极少：11 年 3-6 次交易，任何结论都过不了显著性检验，回测只能证"逻辑能跑通"，证不了"规律存在"。

## 其余策略，快速点将

- **VIX**（`test_24`）：恐慌指数直接定阈值——VIX > 35 买、< 10 卖。11 年里只触发 3 次买入（35 以上屈指可数），终值 261,273.50、Sharpe 0.92，是三者中最"懒"也最锋利的版本。VIX > 35 基本只出现在崩盘进行时——这是"接落刀"策略，回撤 33.7% 全程垫底，回报也最厚。
- **BTC 谷歌趋势**（`test_33`）：散户情绪的加密版——对 Google Trends 搜索热度算布林带（period=10、devfactor=1），热度突破上轨做多、跌破下轨做空、回到中轨平仓。工程上它演示了双数据流接法：BTC 价格是 `datas[0]`，搜索热度作为 `datas[1]` 的 close 挂进来，指标直接架在情绪线上。周线上 16 买 16 卖、胜负各半（终值 15,301.43，初始 10,000），换手率远高于 SPY 系——币圈情绪本身就是快变量，而且这里的情绪是**顺趋势**用法，与 SPY 三兄弟的逆向用法正好相反。

## 一条命令跑起来

```bash
# 整个分类（4 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/sentiment/ -v

# 只跑恐贪指数
pytest tests/functional/strategies/sentiment/test_22_fear_greed_strategy.py -v
```

## 为什么在这个项目上研究情绪策略

情绪策略交易稀疏、路径敏感——一笔订单的价格差异就能改变整段净值曲线，这让回测引擎的撮合保真度和可复现性变得至关重要。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把每个策略的成交次数、终值、Sharpe 全部钉成断言基线，runonce/runnext 双模式对拍确保两种引擎走出同一批交易；纯 Python 引擎比原版快 46%，C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速，扫描不同情绪阈值（10/94 改成 15/90 会怎样？）只需几分钟。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
