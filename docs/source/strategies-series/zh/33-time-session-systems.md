# 时段交易：夜盘通道与开盘定价，把时钟当信号

> 量化策略图鉴 · 第 33 篇 · 分类 `time_session_system`（7 个策略）· 2026-09-02

外汇与黄金市场 24 小时不眠，但流动性有明显的心跳节律：亚盘时段波动收敛、欧洲开盘后活跃度抬升、纽约时段接力放大，每个"开盘"都伴随一次短暂的定价重置——做市商调价、止损单堆积、新闻脉冲释放。如果这个日内节律足够稳定，那么**时钟本身就是信号**：不需要任何指标，在固定时刻开仓、固定时刻离场，赌的是两个钟点之间那段日复一日的漂移。

这听起来像玄学，但它在微观结构研究里有正经名目——时段效应（time-of-day effect），开盘定价与跨市场接力正是其来源。本篇解读 `tests/functional/strategies/time_session_system/` 下的 7 个策略，全部移植自真实 MT5 EA，在 XAUUSD（黄金）数据上运行，初始资金 100 万美元、零佣金、100 倍乘数。它们构成一个从"极简时刻表"到"时段+价格混合"的完整光谱。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| Simple Pending Orders Time | XAUUSD M1 | 15:00 在现价上下挂突破 stop 单，窗口结束清仓撤单 | `test_0001_simple_pending_orders_time.py` |
| Night Flat Trade | XAUUSD M1 执行 / H1 信号 | 夜盘用前 3 根 H1 高低点构通道，四分位均值回归入场 | `test_0002_night_flat_trade.py` |
| OpenTime | XAUUSD M15 | 每天 18:45 定时开空、20:45 定时平仓 | `test_0003_opentime.py` |
| 21hour | XAUUSD M5 | 08:00/22:00 挂对夹突破单，21:00/23:00 强平 | `test_0004_21hour.py` |
| Opening Closing on Time v2 | XAUUSD M15 | 05:00 按 EMA50/200 方向入场，21:01 定时平仓 | `test_0005_opening_closing_on_time_v2.py` |
| Exp_TimesDirection | XAUUSD M15 | 固定方向的定时开平（纯时刻表） | `test_0006_times_direction.py` |
| Open Close on Time | XAUUSD M15 | 首根越过开仓时刻的 K 线入场、越过平仓时刻的 K 线离场 | `test_0007_open_close_on_time.py` |

## 深读一：Night Flat Trade——夜盘的箱体，四分位的回归

七个策略里工程最讲究的一个。[test_0002_night_flat_trade.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_session_system/test_0002_night_flat_trade.py) 的假设是：**深夜盘口冷清，价格被压缩在箱体里，贴边即回归**。M1 数据执行、`resampledata` 重采出 H1 信号，只在 `open_hour`（配置为 0 点）前后的两小时窗口内评估信号：

```python
hour = signal_dt.hour
if hour < int(self.p.open_hour) or hour > int(self.p.open_hour) + 1:
    return
if self.position:
    return

highs = [float(self.data1.high[-i]) for i in range(3)]
lows = [float(self.data1.low[-i]) for i in range(3)]
highest = max(highs)
lowest = min(lows)
diff = highest - lowest

pip = self._pip_value()
diff_min = float(self.p.diff_min_pips) * pip
diff_max = float(self.p.diff_max_pips) * pip
if not (diff > diff_min and diff < diff_max):
    return
```

三道闸门次第落下：先看时钟，再取**前 3 根 H1** 的高低点构成通道，最后要求通道宽度落在 100-400 点之间——太窄没有肉、太宽不是盘整。入场则精确到四分位：

```python
if bid > lowest and bid <= lowest + diff / 4.0:
    sl = lowest - diff / 3.0
    tp = ask + float(self.p.take_profit_pips) * pip if int(self.p.take_profit_pips) > 0 else None
```

价格落入通道**下四分位**做多、止损放在通道底下三分之一处（`lowest - diff/3`），上四分位对称做空；出场靠 50 点固定止盈加 15/5 点移动止损保护。仓位端也不含糊：`lots=0.1` 固定手数，或按 `risk=5.0%` 与 `margin_per_lot=1000` 从可用资金反推——把风险预算写进仓位公式，而不是拍脑袋。诚实的代价是信号极挑剔：2026-03-05 至 03-10 五天窗口、4,562 根 M1，只触发 **1 笔**空头交易——恰好盈利，终值 1,000,061.30。一箭双雕地示范了两件事：session 过滤+波动率闸门如何工作，以及样本量过小时任何胜率都毫无统计意义。

## 深读二：OpenTime——时钟即信号，别无他物

把时段交易删到只剩骨架，就是 [test_0003_opentime.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_session_system/test_0003_opentime.py)。它的 `next()` 里没有一个价格条件：

```python
def next(self):
    self.bar_num += 1
    dt = self.data.datetime.datetime(0)
    if self.order is not None:
        return
    if bool(self.p.time_close) and dt.hour == int(self.p.close_hour) and dt.minute == int(self.p.close_minute) and self.position:
        self.order = self.close()
        return
    self._manage_position()
    if self.order is not None or self.position:
        return
    if dt.hour == int(self.p.trade_hour) and dt.minute == int(self.p.trade_minute):
        key = self._window_key(dt)
        if self.last_open_key == key:
            return
        self.last_open_key = key
        if bool(self.p.use_buy):
            self._arm('buy', float(self.data.close[0]))
            return
        if bool(self.p.use_sell):
            self._arm('sell', float(self.data.close[0]))
```

每天 18:45 开一笔空单（`use_sell=True`，`stop_loss=0/take_profit=0`——纯裸仓），20:45 定时平掉；`_window_key` 这个日期+时刻的键值防止同一窗口重复开仓。实现细节还有一处值得圈点：数据加载时每根 K 线的时间戳整体前移 15 分钟、按**收盘时刻**标记，所以配置里的 18:45 指的是"这根 M15 收在 18:45"——时段策略移植中最常见的坑，就是源 EA 与回测引擎对时间戳语义理解不一致，差一根 K 线，全部开仓时刻跟着漂移。三个月窗口 67 笔交易、37 胜 30 负、胜率 55.2%、盈利因子 1.53、终值 1,002,199.70。每天两小时固定敞口的黄金空头能有此成绩，说明这段数据的傍晚漂移确实偏向下行——但请注意它同时是**一个自由度极少的假设检验**：没有指标、没有参数可调，"这个钟点该做空吗"的答案一目了然。`Exp_TimesDirection`（`test_0006`）与 `Open Close on Time`（`test_0007`）是它的近亲，区别只在"固定方向"与"首根越过时刻的 K 线"这类窗口判定的细节，三者摆在一起，恰好是一组隔离了窗口判定算法的对照实验。

## 深读三：21hour——两个窗口里的对夹突破

纯时刻表赌漂移毕竟是裸赌，更稳的变体是**定时布阵、让价格自己选方向**。[test_0004_21hour.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_session_system/test_0004_21hour.py) 在每天两个窗口的整点挂出一对突破 stop 单：

```python
def _maybe_place_orders(self):
    dt = self._dt(0)
    if self.position or self.pending_buy_stop is not None or self.pending_sell_stop is not None:
        return
    if (dt.hour == int(self.p.hour_start_first) and dt.minute == 0) or (dt.hour == int(self.p.hour_start_second) and dt.minute == 0):
        price_buy = self._round(float(self.data.close[0]) + float(self.p.step) * self._point())
        price_sell = self._round(float(self.data.close[0]) - float(self.p.step) * self._point())
        self.pending_buy_stop = price_buy
        self.pending_sell_stop = price_sell
        self.take_profit_buy = self._round(price_buy + float(self.p.take_profit) * self._point())
        self.take_profit_sell = self._round(price_sell - float(self.p.take_profit) * self._point())
```

08:00（日盘窗口，21:00 收）与 22:00（夜盘窗口，23:00 收）各布一次：现价上下 5 点挂买/卖 stop，先触发的一边成交、另一边作废，仓位挂 40 点止盈，窗口整点强平——**时段截断 + 对夹突破 + 强制收盘**三件套，把隔夜风险和方向判断一起外包给了时钟。M5 数据 18,328 根 K 线、129 笔交易、胜率 56.6%，但盈利因子只有 0.836、终值 996,443.90——胜率过半仍亏钱，盈亏比不够的经典样本。对比 OpenTime 的裸时刻表，"更复杂的结构"并没有自动兑换成"更好的结果"。

## 其余两席，快速点将

- **Simple Pending Orders Time**（`test_0001`）：与 21hour 同族的极简版——每天 15:00 挂一对 offset 突破单，窗口结束撤单清仓，跑在 M1 精度上。
- **Opening Closing on Time v2**（`test_0005`）：给时刻表配上方向过滤——05:00 开仓时看 EMA50 在 EMA200 之上做多、之下做空，21:01 定时平仓，30 点止损/50 点止盈——MA 趋势框架与时段纪律的杂交种。

## 一条命令跑起来

```bash
# 整个分类（7 个策略，固定 runonce=True，断言迁移时捕获的指标基线）
pytest tests/functional/strategies/time_session_system/ -v

# 只跑 Night Flat Trade
pytest tests/functional/strategies/time_session_system/test_0002_night_flat_trade.py -v
```

## 为什么在这个项目上研究时段交易

时段策略高度依赖**时间戳的精确处理**：K 线按开盘还是收盘对齐、重采样的边界归属、"每个窗口只动一次"的门闩逻辑，任何一处差一根 K 线，定时开仓就会整体漂移。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把这些细节全部钉进断言基线，runonce/runnext 双模式对拍确保向量化与事件驱动两个引擎在同一时刻开出同一笔仓；纯 Python 引擎比原版快 46%，装上 C++ 后端（`pip install back-trader-cpp`）更可获得中位 128 倍加速——把 trade_hour 从 18 扫到 23 只需要几分钟，时段假设的稳健性一验便知。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
