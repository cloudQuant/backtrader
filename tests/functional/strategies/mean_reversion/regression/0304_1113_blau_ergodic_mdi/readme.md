# 1113 Blau Ergodic MDI

## 策略概述

该策略是对 MT5 `Exp_BlauErgodicMDI` 的 Backtrader 迁移版本。

原 EA 使用 `BlauErgodicMDI` 振荡器进行交易，可基于三种模式发出信号：零轴突破、柱体方向扭转、以及信号云颜色切换。

## 交易逻辑

- 基于本地重建的 `BlauErgodicMDI` 指标生成信号
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

- `strategy_blau_ergodic_mdi.py` - 数据加载、`BlauErgodicMDI` 指标与策略实现
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
- 买入信号：`25`
- 卖出信号：`25`
- 已完成订单：`100`
- 已拒绝订单：`0`
- 已平仓交易：`50`
- 胜率：`32.00%`
- 期初资金：`100000.00`
- 期末现金：`97313.00`
- 期末权益：`97313.00`
- 净收益：`-2687.00`
- 最大回撤：`2.93%`
- SQN：`-1.03`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。当前 `H4 + twist` 组合有稳定触发，但盈亏比与胜率组合不足以覆盖止损损耗，最终小幅亏损。
