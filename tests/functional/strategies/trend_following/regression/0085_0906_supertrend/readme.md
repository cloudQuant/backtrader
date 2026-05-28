# 0906 SuperTrend

## 策略概述

该示例是 MT5 EA `Exp_SuperTrend` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `SuperTrend` 指标，并在趋势翻转信号出现时交易。

## 指标重建

- `CCI(CCIPeriod)` 与 `ATR(ATRPeriod)` 驱动
- `CCI >= Level` 且前值 `< Level` → 上升趋势启动
- `CCI <= Level` 且前值 `> Level` → 下降趋势启动
- `TrendUp = low - ATR`（棘轮上移），`TrendDown = high + ATR`（棘轮下移）
- 趋势翻转时生成 SignUp/SignDown 箭头

## 交易逻辑

- SignUp/SignDown 信号入场
- TrendUp/TrendDown 持续时的反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_supertrend.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
