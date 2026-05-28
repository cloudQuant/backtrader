# 1157 SHE_kanskigor

## 策略概述

该策略是对 MT5 EA `1157_SHE_kanskigor` 的 Backtrader 迁移版本。

原 EA 在指定时刻读取上一根日线 K 线方向，并以**相反方向**开仓：前日收阳则做空，前日收阴则做多。

## 交易逻辑

- 在 `start_time_hour:start_time_minute` 附近的 5 分钟窗口内检查是否开仓
- 若当前无持仓，读取上一根日线 `open/close`
- 前日收阳时反向做空
- 前日收阴时反向做多
- 每个交易日只触发一次

## 风控逻辑

- 开仓后按固定点数设置 `Stop` 与 `Profit`
- 参数中的 `Symb=*` 在本地迁移中默认使用当前回测数据符号

## 文件

- `strategy_she_kanskigor.py` - 数据加载、定时开仓与风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`profit=350`、`stop=550`、`start_time_hour=0`、`start_time_minute=5`
- 信号次数：`0`
- 已平仓交易：`0`
- TradeAnalyzer 统计交易：`0`
- 胜率：`0.00%`
- 期初资金：`100000.00`
- 期末现金：`100000.00`
- 期末权益：`100000.00`
- 净收益：`0.00`
- 最大回撤：`0.00%`
- SQN：`0.00`

说明：本样本区间内未触发有效定时反向入场信号，样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
