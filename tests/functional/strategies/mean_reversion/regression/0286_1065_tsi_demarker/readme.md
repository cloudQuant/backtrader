# 1065 Exp_TSI_DeMarker

## 策略概述

该示例是 MT5 EA `1065_Exp_TSI_DeMarker` 的 Backtrader 迁移版本。

原 EA 使用 `TSI_DeMarker` 指标，在已完成信号柱上依据 `tsi` 与其平滑信号线 `xtsi` 的相对位置翻转触发交易。

## 原始信号逻辑

EA 读取指标两条缓冲线：

- `Ind` = `tsi`
- `Sign` = `xtsi`

交易条件：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`TSI_DeMarker` 的计算步骤为：

- 先计算标准 `DeMarker(period=25)`
- 对 `DeMarker` 做 `mom_period` 周期动量
- 分别对动量和绝对动量做两级平滑
- 构造 `tsi = 100 * xxmtm / xxabsmtm`
- 再对 `tsi` 做第三级平滑得到 `xtsi`

## 风控逻辑

- 固定 `stop_loss`
- 固定 `take_profit`
- 固定手数 `size`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_tsi_demarker.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 时间区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 初始资金：`100000`
- 最终权益：`99606.80`
- 净收益：`-393.20`
- 成交笔数：`9`
- 买入信号：`5`
- 卖出信号：`5`
- 胜率：`55.56%`
- Profit Factor：`0.78`
- 最大回撤：`1.44%`
