# 1078 Exp_KaufWMAcross

## 策略概述

该示例是 MT5 EA `1078_Exp_KaufWMAcross` 的 Backtrader 迁移版本。
EA 在高周期上读取 `KaufWMAcross` 指标箭头，并在箭头出现时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer1`: `UpValue`，买入箭头
- `buffer0`: `DnValue`，卖出箭头

交易判断与源码一致：

- 当 `UpValue[0]` 非空且不为 `EMPTY_VALUE` 时，开多并平空
- 当 `DnValue[0]` 非空且不为 `EMPTY_VALUE` 时，开空并平多
- 若当前柱未直接给出平仓箭头，EA 会向后搜索最近一次反向箭头用于关闭持仓

## 指标迁移说明

`KaufWMAcross` 的核心逻辑是：

- 计算 `iAMA`（Kaufman AMA）
- 计算另一条 `iMA`（默认 `LWMA(13)`）
- 计算 `ATR(15)` 用于箭头偏移
- 若 `AMA[1] > MA[1] && AMA[0] < MA[0]`，在低点下方绘制买入箭头
- 若 `AMA[1] < MA[1] && AMA[0] > MA[0]`，在高点上方绘制卖出箭头

## 主要参数

- `ama_period`
- `fast_ma_period`
- `slow_ma_period`
- `ma_period`
- `ma_type`
- `signal_bar`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`14`
- 净收益：`12510.80`
- 胜率：`64.29%`
- 最大回撤：`3.23%`
