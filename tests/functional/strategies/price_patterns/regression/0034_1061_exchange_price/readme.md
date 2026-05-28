# 1061 Exp_ExchangePrice

## 策略概述

该示例是 MT5 EA `1061_Exp_ExchangePrice` 的 Backtrader 迁移版本。

原 EA 使用 `ExchangePrice` 指标，在 `H8` 信号周期上依据两条历史价格差值线的交叉触发交易。

## 原始信号逻辑

EA 读取指标两条缓冲线：

- `Ind = (current - price[countBarsS]) / point`
- `Sign = (current - price[countBarsL]) / point`

交易条件：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`ExchangePrice` 的计算非常直接：

- 使用指标输入价格序列（原指标通过 `OnCalculate(..., const double &price[])` 接收 applied price；本迁移按默认 `close` 重建）
- 计算当前价格相对 `countBarsS` 和 `countBarsL` 根之前价格的点差值
- 用两条差值线的相对位置变化生成信号

## 风控逻辑

- 固定 `stop_loss`
- 固定 `take_profit`
- 固定手数 `size`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_exchange_price.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 时间区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 初始资金：`100000`
- 最终权益：`100000.00`
- 净收益：`0.00`
- 成交笔数：`0`
- 买入信号：`0`
- 卖出信号：`0`
- 胜率：`0.00%`
- Profit Factor：`None`
- 最大回撤：`0.00%`
- **注意**：因 `H8` 信号周期下 `count_bars_l=288` 预热需求过高，当前样本窗口内无可用信号柱，故结果为零成交。
