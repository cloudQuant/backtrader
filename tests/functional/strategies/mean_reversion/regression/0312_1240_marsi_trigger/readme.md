# 1240 MaRsi-Trigger

## 策略概述

该策略是对 MT5 EA `1240_Exp_MaRsi-Trigger` 的 Backtrader 迁移版本。
原 EA 并不直接依赖可视化的 `ColorMaRsi-Trigger` 指标 buffer，而是直接读取快慢 `MA` 与快慢 `RSI` 的相对关系来生成三态趋势。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算快慢两组 `RSI`
3. 计算快慢两组 `MA`
4. 若快 `MA` 大于慢 `MA`，趋势得分 `+1`；反之 `-1`
5. 若快 `RSI` 大于慢 `RSI`，趋势得分再 `+1`；反之再 `-1`
6. 将总得分压缩到 `-1/0/+1`
7. 当前趋势与上一个非零趋势方向相反时执行反手开仓；同向时仅执行对向平仓维护

## 主要参数

- `indicator_minutes`
- `n_period_rsi`
- `n_rsi_price`
- `n_period_rsi_long`
- `n_rsi_price_long`
- `n_period_ma`
- `n_ma_type`
- `n_ma_price`
- `n_period_ma_long`
- `n_ma_type_long`
- `n_ma_price_long`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

此迁移版按 EA 源码中的“当前趋势 + 最近非零历史趋势”规则实现，
而不是简单依据彩色指标的显示状态直接下单。
