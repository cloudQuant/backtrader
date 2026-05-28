# 0187 RNN

## 策略概述

该样例是对 MT5 EA `0187_RNN` 的 Backtrader 迁移版。
EA 基于 `RSI` 和一个小型固定参数网络计算卖出概率；在每根新 bar 到来时，若当前没有持仓，就根据该概率方向开仓，并设置对称的固定 `SL/TP`。

## 迁移思路

1. 直接在 `M15` 数据上运行，对应当前项目统一的 `XAUUSD_M15` 验证数据
2. 使用源码默认参数计算 `RSI(period=9, applied_price=open)`
3. 按源码从 RSI 数组中抽取三个输入：
   - `a1 = rsi[0] / 100`
   - `a2 = rsi[period] / 100`
   - `a3 = rsi[period*2] / 100`
4. 复刻 `GetProbability()` 中的 8 点插值网络：`x0..x7`
5. 将卖出概率从 `[0,1]` 线性映射到 `[-1,1]`：`signal = probability * 2 - 1`
6. 若 `signal < 0` 则开多，否则开空；持仓只依赖固定 `SL/TP` 退出，不根据信号反手平仓

## 主要参数

- `lots`
- `sltp_pips`
- `x0..x7`
- `rsi_period`
- `rsi_price`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 原 readme 示例周期是 `EURUSD M5`，但当前项目统一验证数据为 `XAUUSD M15`，因此这里只能在 `M15` 上做等价迁移验证
- 原 EA 若已有持仓则直接跳过新信号，不做加仓也不做基于概率的平仓；当前实现保持这一行为
- 当前回测结果：`3049` 笔成交，净收益 `-69921.00`，胜率 `46.47%`，Profit Factor `0.93`，最大回撤 `99.49%`
