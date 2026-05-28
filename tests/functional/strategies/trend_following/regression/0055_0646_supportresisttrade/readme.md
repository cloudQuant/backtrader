# 0646 SupportResistTrade

## 策略概述

该策略是对 MT5 EA `0646_SupportResistTrade` 的 Backtrader 迁移版本。

- N-bar 最高/最低价计算阻力/支撑水平
- EMA 趋势过滤
- 突破入场 + 反向水平止损 + 移动止损

## 核心逻辑

1. 使用最近 `num_bars` 根 bar 的最高价作为阻力、最低价作为支撑。
2. EMA 判断趋势：价格在 EMA 上方为看涨，下方为看跌。
3. 看涨趋势下突破阻力 → 做多，SL 设在支撑。
4. 看跌趋势下跌破支撑 → 做空，SL 设在阻力。
5. 持仓期间使用移动止损。

## 迁移说明

- 原 EA 使用可配置的时间框架（默认 M1）和 MA 周期 500；迁移版保留参数。
- 原版有图表绘制对象（水平线/标签）；迁移版省略。

## 主要参数

- `num_bars`
- `ma_period`
- `trailing_stop` / `trailing_step`
- `lots`

## 运行方式

```bash
python run.py
```
