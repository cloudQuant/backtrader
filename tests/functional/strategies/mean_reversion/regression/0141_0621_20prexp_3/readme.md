# 0621 20PRExp-3

## 策略概述

该策略是对 MT5 EA `0621_20PRExp-3` 的 Backtrader 迁移版本。

- 日内区间突破 + M30 成交量放大过滤
- 以前一交易日高低点作为买卖止损参考
- Parabolic SAR 反向离场 + trailing stop

## 核心逻辑

1. 每日更新前一交易日高点 `MLP`、低点 `MLM`，并计算区间宽度。
2. 若当前价格向上突破 `MLP`，且 `M30` 最新成交量 / 前一根成交量 `> 1.5`，且日区间宽度 `> gap`，则做多。
3. 若当前价格向下跌破 `MLM`，且量能过滤与区间宽度条件满足，则做空。
4. 多头在 `SAR > close[-1]` 时平仓，空头在 `SAR < close[-1]` 时平仓。
5. 持仓盈利后按 `trailing_stop` / `trailing_step` 推进止损，并同步更新止盈。

## 迁移说明

- 原 EA 使用 `MoneyFixedRisk` 手数管理；迁移版简化为固定手数。
- 原版使用 `PERIOD_M5` 的 `SAR` 和 `PERIOD_M30` 的成交量过滤；迁移版保留 `M30` 成交量过滤，并在当前回测数据上用 Parabolic SAR 近似其离场逻辑。
- 原版绘图水平线逻辑未迁移到 Backtrader。

## 主要参数

- `take_profit`
- `trailing_stop` / `trailing_step`
- `gap`
- `volume_ratio_threshold`
- `start_hour`
- `sar_af` / `sar_afmax`

## 运行方式

```bash
python run.py
```
