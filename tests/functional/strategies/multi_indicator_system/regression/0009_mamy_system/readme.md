# 0188 MAMy 智能系统

## 策略概述

该样例是对 MT5 EA `0188_MAMy_智能系统` 的 Backtrader 迁移版。
EA 使用自定义指标 `MAMy v3` 的两个缓冲区：

- `buffer 0` 负责入场信号
- `buffer 1` 负责平仓信号

源码在新 K 线到来时读取最近值，并依据缓冲区的过零切换进行交易。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H1`，对应原 readme 中的典型示例周期
2. 复刻 `MAMy v3` 指标内部三条均线：`PRICE_CLOSE`、`PRICE_OPEN`、`PRICE_WEIGHTED`
3. 其中 `PRICE_WEIGHTED` 按 MQL 定义使用 `(H + L + 2*C) / 4`
4. 按指标源码重建 `MAMyOpenBuffer` 与 `MAMyCloseBuffer`
5. 按 EA 源码条件生成信号：
   - 开多：`buffer0` 上穿 0
   - 开空：`buffer0` 下穿 0
   - 平多：`buffer1` 下穿 0
   - 平空：`buffer1` 上穿 0
6. 保持原 EA 的固定手数逻辑，不额外添加止损或止盈

## 主要参数

- `lots`
- `ma_period`
- `ma_method`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 原文说明把中间均线描述成 `MA(H+L+O+C)/4`，但源码实际调用的是 MQL `PRICE_WEIGHTED`，当前迁移版以源码为准
- 原 EA 在 `OnTick` 的新 bar 触发点直接读取 `buffer[0]` 和 `buffer[1]`；当前 Backtrader 版本用 `cheat_on_open` 在新 bar 开盘时执行，保持接近的时序
- 当前回测结果：`245` 笔成交，净收益 `+736490.00`，胜率 `94.29%`，Profit Factor `94.92`，最大回撤 `3.40%`
