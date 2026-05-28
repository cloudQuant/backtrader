# 0014 Simple Price

## 策略概述

该策略是对 MT5 EA `0014_简单价格/simple_price_ea.mq5` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M1.csv` 回测，保留了原 EA 的极值触达开仓思想：

- 统计最近 `Check_Bars` 根 K 线的最低价与最高价
- 触达最低价时尝试开多
- 触达最高价时尝试开空
- 开仓后只设置固定止盈，不设置固定止损

## 核心逻辑

1. 每根新 K 线到来时，读取最近 `Check_Bars` 根数据
2. 计算：
   - `move_up` = 最近区间最低价
   - `move_down` = 最近区间最高价
3. 如果当前价格触达区间低点，则开多
4. 如果当前价格触达区间高点，则开空
5. 开仓后按原 EA 风格设置固定止盈，止盈距离会叠加当前 spread 点数
6. 平仓后继续等待下一次极值触发

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `check_bars`
- `lots`
- `tp_points`
- `point`
- `price_digits`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M1.csv`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 原 EA 只有一个主要输入参数 `Check_Bars`
- 当前 backtrader 版本按照 bar 级别复现“触及极值即开仓”的行为
- 由于 backtrader 是 bar 级别回测，无法逐 tick 精确判断 `Bid == move_up` 或 `Ask == move_down`，因此这里使用当前 bar 触达区间极值进行近似实现
- 当前版本已完成可运行回测验证
