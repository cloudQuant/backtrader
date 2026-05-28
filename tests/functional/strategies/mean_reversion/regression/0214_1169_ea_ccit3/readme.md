# 1169 EA_CCIT3

## 策略概述

该策略是对 MT5 EA `1169_EA_CCIT3` 的 Backtrader 迁移版本。

原 EA 使用两种可选的 `CCIT3` 指标变体：

- `CCIT3_Simple_v_2-01`
- `CCIT3_noReCalc_v_3-01`

EA 在上一根已完成 K 线的 `CCIT3` 穿越零线时开仓，并支持固定 `SL/TP`、盈利后 trailing 与可选反手。

## 迁移说明

Backtrader 版本保留了以下关键行为：

- 只能启用一个 `CCIT3` 变体
- 信号基于已完成柱的 `CCIT3` 零轴穿越
- `Trade_overturn=true` 时反手
- `SL/TP` 在开仓后立即生效
- `trail > 0` 且持仓盈利时向有利方向移动止损
- `Max_drawdown > 0` 时按 `lots * equity / max_drawdown` 计算动态手数

## 公式对齐

`CCIT3` 的核心为：

- 先计算 `CCI`
- 再用 T3 风格的六级平滑递推与系数组合输出
- `Simple` 版本沿历史连续递推
- `noReCalc` 版本对每个 bar 重新初始化平滑状态后计算当前值

## 文件

- `strategy_ccit3.py` - 数据加载、`CCIT3` pandas 信号预计算、信号 feed 与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=1.0`、`tp=1750`、`sl=0`、`trail=0`、`use_simple_ccit3=true`
- 信号次数：`31`
- 已平仓交易：`9`
- TradeAnalyzer 统计交易：`10`
- 胜率：`90.00%`
- 期初资金：`100000.00`
- 期末现金：`42446.00`
- 期末权益：`42696.00`
- 净收益：`-57304.00`
- 最大回撤：`98.64%`
- SQN：`8.03`

说明：样本结束时仍保留 `1` 笔未平仓空单，持仓数量 `-1.0`、开仓价 `4404.88`，因此闭合交易大多盈利，但期末权益仍受到未实现亏损拖累。
