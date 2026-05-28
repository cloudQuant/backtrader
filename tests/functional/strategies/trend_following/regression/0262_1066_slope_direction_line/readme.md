# 1066 Exp_SlopeDirectionLine

## 策略概述

该示例是 MT5 EA `1066_Exp_SlopeDirectionLine` 的 Backtrader 迁移版本。

原 EA 使用 `SlopeDirectionLine` 主图指标，在已完成信号柱收盘后依据颜色切换触发交易。

## 原始信号逻辑

EA 只读取指标的颜色缓冲区：

- 颜色值 `2` 表示上升方向
- 颜色值 `0` 表示下降方向
- 若当前信号柱颜色切换为 `2`，则开多并平空
- 若当前信号柱颜色切换为 `0`，则开空并平多

## 指标迁移说明

`SlopeDirectionLine` 的核心计算为：

- 先按 `IPC` 价格源构造输入价格序列
- 对价格分别做 `Length1` 与 `Length1/2` 周期平滑
- 用 `2 * smooth(length1/2) - smooth(length1)` 构造中间线
- 再按 `sqrt(Length1)` 周期进行二次平滑得到主线
- 通过主线相对前一根的斜率方向生成颜色状态

## 风控逻辑

- 固定 `stop_loss`
- 固定 `take_profit`
- 固定手数 `size`
- 反向颜色信号到来时先平仓再反手

## 文件

- `strategy_slope_direction_line.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 时间区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 初始资金：`100000`
- 最终权益：`116594.30`
- 净收益：`16594.30`
- 成交笔数：`53`
- 买入信号：`27`
- 卖出信号：`27`
- 胜率：`47.17%`
- Profit Factor：`2.55`
- 最大回撤：`2.26%`
