# 1111 Blau TS Stochastic

## 策略概述

该策略是对 MT5 `Exp_BlauTSStochastic` 的 Backtrader 迁移版本。

原 EA 使用 `BlauTSStochastic` 振荡器，可基于零轴突破、柱体方向扭转以及信号云颜色切换三种模式发出交易信号。

## 交易逻辑

- 基于本地重建的 `BlauTSStochastic` 指标生成信号
- `mode=breakdown` 时检测直方图穿越零轴
- `mode=twist` 时检测直方图方向扭转
- `mode=cloudtwist` 时检测主线与信号线的相对位置翻转
- 出现反向信号时先平仓再反手
- 默认使用 `H4` 指标周期

## 风控逻辑

- 固定 `stop_loss_points`
- 固定 `take_profit_points`
- 固定手数 `lot`

## 文件

- `strategy_blau_ts_stochastic.py` - 数据加载、`BlauTSStochastic` 指标与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`mode=twist`、`indicator_timeframe=H4`、`signal_bar=1`、`stop_loss_points=1000`、`take_profit_points=2000`、`lot=0.1`
- 买入信号：`0`
- 卖出信号：`0`
- 已完成订单：`0`
- 已拒绝订单：`0`
- 已平仓交易：`0`
- 期初资金：`100000.00`
- 期末现金：`100000.00`
- 期末权益：`100000.00`
- 净收益：`0.00`
- 最大回撤：`0.00%`

说明：Backtrader 迁移版在验证前修复了 `BlauTSStochastic` 信号线构造错误，避免 `LineBuffer` 迭代异常。修复后在当前 `H4` 重采样与 `mode=twist` 参数下，样本区间内没有触发开仓条件，期末也没有未平仓头寸。
