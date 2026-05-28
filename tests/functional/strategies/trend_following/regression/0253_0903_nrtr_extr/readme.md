# 0903 NRTR_extr

## 策略概述

该示例是 MT5 EA `Exp_NRTR_extr` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `NRTR_extr` 指标，并在趋势翻转信号出现时交易。

## 指标重建

- 与 NRTR 相同的棘轮结构，但使用 `high/low` 极值而非 `close` 跟踪价格
- 上升趋势：`price = max(price, high)`；`close < value` → 翻转
- 下降趋势：`price = min(price, low)`；`close > value` → 翻转
- 4 条输出线：TrendUp/TrendDown + SignUp/SignDown

## 交易逻辑

- SignUp/SignDown 信号入场
- TrendUp/TrendDown 持续时的反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_nrtr_extr.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
