# 1156 starter

## 策略概述

该策略是对 MT5 EA `starter` 的 Backtrader 迁移版本。

原 EA 使用 `Laguerre + MA + CCI` 的组合触发入场：`Laguerre` 落到极值区、均线方向确认、`CCI` 超阈值配合；平仓则依据 `Laguerre` 回到反向区间触发。

## 交易逻辑

- `Laguerre` 接近 `0`、均线上行且 `CCI < -CCILevel` 时做多
- `Laguerre` 接近 `1`、均线下行且 `CCI > CCILevel` 时做空
- 多头在 `Laguerre > 0.9` 时平仓
- 空头在 `Laguerre < 0.1` 时平仓
- `Shift` 控制信号取当前柱还是前一根完整柱

## 风控逻辑

- 支持固定手数，或在 `lots=0` 时按 `maximum_risk` 估算手数
- 支持连续亏损后的手数递减
- 支持真实或虚拟 `SL/TP`
- 当 `virtual_sltp=true` 时，不在经纪商层挂止损止盈，而是在策略内部触发平仓

## 文件

- `strategy_starter.py` - 数据加载、Laguerre 指标、信号与风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`maximum_risk=0.05`、`decrease_factor=0`、`stop_loss=100`、`take_profit=0`、`virtual_sltp=true`、`lag_gamma=0.7`、`cci_period=14`、`cci_price=0`、`cci_level=5`、`ma_period=5`、`ma_shift=0`、`ma_method=ema`、`ma_price=4`、`shift=0`
- 信号次数：`508`
- 已平仓交易：`381`
- TradeAnalyzer 统计交易：`381`
- 胜率：`45.93%`
- 期初资金：`100000.00`
- 期末现金：`100216.40`
- 期末权益：`100216.40`
- 净收益：`216.40`
- 最大回撤：`1.88%`
- SQN：`0.10`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
