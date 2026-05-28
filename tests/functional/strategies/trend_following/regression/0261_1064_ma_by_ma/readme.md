# 1064 Exp_MaByMa

## 策略概述

该示例是 MT5 EA `1064_Exp_MaByMa` 的 Backtrader 迁移版本。

原 EA 使用 `MaByMa` 指标，在已完成信号柱上依据两条均线缓冲线的交叉触发交易。

## 原始信号逻辑

EA 读取指标两条缓冲线：

- `Ind` = 第一层平滑均线
- `Sign` = 第二层基于 `Ind` 的再平滑均线

交易条件：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`MaByMa` 的计算步骤为：

- 先按 `IPC` 选择价格源
- 对价格做第一层平滑得到 `Ind`
- 再对 `Ind` 做第二层平滑得到 `Sign`
- 通过 `Ind` 与 `Sign` 的相对位置变化触发信号

在 Backtrader 版本中：

- `SMA/SMMA/LWMA` 按常规定义重建
- `JJMA/JurX/ParMA/T3/VIDYA/AMA` 统一按 `EMA` 近似，以保持与仓库内其他 `XMA` 迁移的一致性

## 风控逻辑

- 固定 `stop_loss`
- 固定 `take_profit`
- 固定手数 `size`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_ma_by_ma.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 时间区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 初始资金：`100000`
- 最终权益：`100771.20`
- 净收益：`771.20`
- 成交笔数：`7`
- 买入信号：`4`
- 卖出信号：`3`
- 胜率：`42.86%`
- Profit Factor：`1.45`
- 最大回撤：`1.69%`
