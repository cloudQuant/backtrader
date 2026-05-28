# 0784 DVD Level

## 策略概述

该策略是对 MT5 EA `0784_DVD_Level` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的多周期评分与挂单入场框架：

- 使用 `H1` 与 `D1` 的 `EMA(2/24)` 构造 `RAVI`
- 围绕 `Level100` 对价格结构进行打分
- 满足条件时放置 `BuyLimit` / `SellLimit`
- 使用固定 `StopLoss/TakeProfit`
- 默认不开启 trailing stop，与源码默认参数一致

## 核心逻辑

1. 从统一 `M15` 数据构造 `M30 / H1 / D1` 重采样序列
2. 计算 `RAVI0_2_24_H1` 与 `RAVI0_2_24_D1`
3. 根据 `Level100` 及多周期高低点条件累积评分 `BAL`
4. 当 `BAL >= 50` 时下达对应方向的限价单
5. 入场后根据固定 `SL/TP` 管理仓位

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `money_management`
- `trade_size_percent`
- `lots`
- `stop_loss`
- `take_profit`
- `margin_cutoff`
- `use_trailing_stop`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

已完成一次可运行验证，结果如下：

- 数据区间：`2025-12-03 01:15:00` ~ `2026-03-10 09:00:00`
- K线数量：`M15=6129`，`M30=3071`，`H1=1538`，`D1=68`
- 最终权益：`100000.00`
- 净收益：`0.00`
- 总收益率：`0.00%`
- 总交易数：`0`
- 最大回撤：`0.00%`

在当前 `XAUUSD_M15` 数据窗口与近似条件下，策略未触发有效成交，但脚本、数据加载、多周期重采样、限价单框架与风险管理流程均已验证可运行。

## 对齐说明

- 原 EA 依赖 `M1 / M30 / H1 / D1` 多周期数据；当前统一验证环境只有 `XAUUSD_M15.csv`，因此使用 `M15` 近似源码里的 `M1`，并由其重采样得到更高周期
- 原 EA 通过 `BuyLimit/SellLimit` 挂单进场；当前版本同样使用 Backtrader 限价单而非直接市价追单
- 原源码里资金管理会把仓位上限推到 `MaxLots`；当前版本保留这一默认行为以接近原始参数语义
