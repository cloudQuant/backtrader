# 0045 Raymond Cloudy Day For EA

## 策略概述

该策略迁移自 `ea/0045_Raymond_Cloudy_Day_For_EA/raymond_cloudy_day_for_ea.mq5`。

源码会先根据 `RayMondTimeframe` 上一根K线的高、低、开、收计算 Raymond Cloudy Day 点位，再在当前图表周期上根据上一根K线与关键线位的相对位置触发买卖。

## 核心逻辑

1. 取上一根 `RayMondTimeframe` K线的 `high / low / open / close`
2. 计算：
   - `TradeSS`
   - `ETB / ETS`
   - `TPB1 / TPS1`
   - `TPB2 / TPS2`
3. 在当前周期上检查上一根K线：
   - 若 `low[1] < TPS1` 且 `close[1] > TPS1`，则买入
   - 若 `low[1] > TPS1` 且 `close[1] < TPS1`，则卖出
4. 每笔订单使用固定 `500 point` 止损和止盈

## 参数

主要参数位于 `config.yaml`：

- `raymond_timeframe`
- `lot_size`
- `stop_points`
- `take_profit_points`
- `point_size`
- `comment`

## 数据与运行方式

当前验证方式：

- 数据：`../../../datas/XAUUSD_M15.csv`
- Raymond 主计算周期：`D1`
- 触发周期：`M15`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 源码本身包含较多图表绘制与营销文本输出；迁移版本仅保留交易相关计算与执行逻辑
- 当前实现保留源码中的入场条件与固定 `500 point` 的 `SL/TP` 处理
