### 背景

现在目前存在问题是是 backtrader 指标之间加减等向量操作存在问题，需要写一个单独的测试用例进行测试

### 任务步骤

1. 在 tests/add_tests 中新建一个 test_line.py 文件
2. 创建一个策略进行，使用随机生成的 100 个高开低手成交量，设定 seed，确保生成的数字会是一样的
3. 测试用例 1，参考 backtrader/tests/strategies/test_07_macd_ema_true_strategy.py 初始化指标的计算方式

```bash

# 计算 macd 指标 - 使用原始行操作方式

self.ema_1 = bt.indicators.ExponentialMovingAverage(self.datas[0].close, period=self.p.period_me1)
self.ema_2 = bt.indicators.ExponentialMovingAverage(self.datas[0].close, period=self.p.period_me2)
self.dif = self.ema_1 - self.ema_2
self.dea = bt.indicators.ExponentialMovingAverage(self.dif, period=self.p.period_dif)
self.macd = (self.dif - self.dea) *2

```bash
测试用例 2：参考 backtrader/tests/strategies/test_08_kelter_strategy.py 初始化指标的计算方式

```bash
 self.middle_price = (self.datas[0].high + self.datas[0].low + self.datas[0].close) / 3
self.middle_line = bt.indicators.SMA(self.middle_price, period=self.p.avg_period)
self.atr = bt.indicators.AverageTrueRange(self.datas[0], period=self.p.avg_period)
self.upper_line = self.middle_line + self.atr*self.p.atr_multi
self.lower_line = self.middle_line - self.atr* self.p.atr_multi

```bash
测试用例 3：参考 backtrader/tests/strategies/test_15_fenshi_ma_strategy.py 初始化指标的计算方式

```bash
self.day_avg_price = TimeLine(self.datas[0])
self.ma_value = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_period)

```bash
测试用例 4：参考 backtrader/tests/strategies/test_16_cb_strategy.py 初始化指标的计算方式

highest_price = bt.indicators.Lowest(data.low, period=20)
lowest_price = bt.indicators.Highest(data.high, period=20)

1. 针对每个测试用例，分别判断这些指标生成的指标值是否和预期一致，预期值使用 master 版本的 backtrader 生成的指标值，确保可以在 master 版本通过，即先切换到 master 版本，然后 pip install -U . 安装 master 版本的 backtrader，然后切换到当前的 remove-metaprogramming 这个分支，在这个分支上，实现这几个测试用例的代码(实际上使用的是 master 版本的 backtrader),使得这些测试用例能够通过，每个测试用例需要包含 bar_num, 各个指标值在 next 中运行中获取的值，用 assert 进行断言，结束之后判断 bar_num 等于多少，这个根据运行结果写预期值，确保 master 版本的 backtrader 能够通过。
