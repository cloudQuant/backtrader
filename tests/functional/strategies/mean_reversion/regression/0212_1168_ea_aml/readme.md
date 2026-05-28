# 1168 EA_AML

## 策略概述

该策略是对 MT5 EA `1168_EA_AML` 的 Backtrader 迁移版本。

原 EA 使用 `AML` 指标作为主信号线，并在上一根已完成 K 线上判断蜡烛实体是否穿越指标线。

## 交易逻辑

- 当上一根 K 线满足 `open <= AML <= close` 时做多
- 当上一根 K 线满足 `close <= AML <= open` 时做空
- 若已有持仓且 `use_opposite=true`，则在反向信号出现时先平仓再反手
- 开仓后立即设置固定 `SL/TP`
- 若启用 `use_multpl`，则按 `lots * balance / max_drawdown` 动态放大手数，并受 `max_lot` 限制

## 指标逻辑

`AML` 根据原始指标源码迁移，核心步骤为：

- 计算两个 `Fractal` 窗口与一个 `2 * Fractal` 窗口的波动范围
- 由三段范围估算分形维度 `dim`
- 计算自适应系数 `alpha = exp(-Lag * (dim - 1))`
- 用加权价格 `(high + low + 2 * open + 2 * close) / 6` 递推平滑线
- 当当前平滑值与 `Lag` 步前的差异不足 `Lag^2 * point` 时，沿用前一柱 AML 值
- 平滑序列在启动阶段按原始 MQL 实现保持零初始化参考，以减少早期柱偏差
- 当前回测实现使用 `pandas` 预计算 `AML` 序列，并以独立 signal feed 提供给策略消费，价格 K 线仍由主数据 feed 提供

## 文件

- `strategy_ea_aml.py` - 数据加载、AML 指标与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

 - 数据：`XAUUSD_M15.csv`
 - 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
 - 参数：`lots=0.1`、`tp=3500`、`sl=500`、`use_opposite=true`、`use_multpl=false`、`fractal=70`、`lag=18`
 - 信号次数：`334`
 - 已平仓交易：`313`
 - TradeAnalyzer 统计交易：`313`
 - 胜率：`35.14%`
 - 期初资金：`100000.00`
 - 期末现金：`99125.60`
 - 期末权益：`99125.60`
 - 净收益：`-874.40`
 - 最大回撤：`2.84%`
 - SQN：`-0.36`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。

当前 `run.py` 已额外输出以下字段，便于验证时直接记录：

- `signal_count`
- `final_cash`
- `final_value`
- `open_position_size`
- `open_position_price`
