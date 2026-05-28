# 1003 Forecast Oscilator

## 策略概述

该示例是 MT5 EA `Exp_ForecastOscilator` 的 Backtrader 迁移版本。

原 EA 基于 `ForecastOscilator` 指标生成的买卖箭头，在信号周期收盘后读取箭头缓冲区并执行开平仓。

## 交易逻辑

- 重建 `ForecastOscilator`：
  - 先按原公式计算加权预测价格 `WT`
  - 再计算 `forecastosc=(price-WT)/WT*100`
  - 用原始 T3 平滑参数 `t3` 与 `b` 生成信号线
  - 当振荡器与信号线满足原始箭头条件时产生买卖箭头
- 出现买箭头时开多并平空
- 出现卖箭头时开空并平多
- 默认使用 `H12` 信号周期

## 风控逻辑

- 固定 `stop_loss_points`
- 固定 `take_profit_points`
- 固定手数 `lot`
- 反向箭头到来时先平仓再反手

## 文件

- `strategy_forecastoscilator.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
