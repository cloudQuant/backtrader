# 0733 Exp_BykovTrend_ReOpen

## 策略概述

该策略是对 MT5 EA `0733_Exp_BykovTrend_ReOpen` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主结构：

- 通过 `BykovTrend` 指标箭头产生入场方向
- 反向箭头用于平掉相反持仓
- 按 `PriceStep` 在顺势运行中继续同向加仓
- 加仓次数受 `PosTotal` 约束

## 指标重建说明

`BykovTrend` 本体按源码近似重建：

- 使用 `WPR(SSP)`
- 使用 `ATR(15)`
- 依据 `RISK` 计算阈值 `K = 33 - RISK`
- 趋势状态切换时在图上产生买卖箭头

## 核心交易逻辑

1. `buy_arrow` 出现时做多，并关闭空头。
2. `sell_arrow` 出现时做空，并关闭多头。
3. 若价格继续向持仓有利方向移动超过 `PriceStep`，则允许继续同向加仓。
4. 达到 `PosTotal` 后停止再开仓。
5. 仓位统一按固定 `SL/TP` 管理。

## 主要参数

- `price_step`
- `pos_total`
- `risk`
- `ssp`
- `stop_loss`
- `take_profit`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
