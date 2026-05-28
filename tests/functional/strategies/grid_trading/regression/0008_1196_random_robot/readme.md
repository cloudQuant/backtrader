# 1196 Random Robot

## 策略概述

该策略是对 MT5 EA `1196_真正随机的机器人` 的 backtrader 迁移版本。
当前版本保留了原 EA 的教学结构：

- 随机投掷决定多空方向
- 固定手数
- 固定止盈与止损
- 始终在平仓后再次寻找下一笔随机入场

## 核心逻辑

1. 当没有持仓时，生成一次随机投掷
2. 投掷结果为 0 时做多，为 1 时做空
3. 开仓后设置固定止损 `stop_loss` 和止盈 `profit_target`
4. 仓位离场后重新进行下一次随机入场
5. `really_random=false` 时使用固定种子，便于回测复现

## 主要参数

- `profit_target`
- `stop_loss`
- `lot`
- `really_random`
- `seed`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `909`
- Net P&L: `5,472.40`
- Win Rate: `66.23%`
- Profit Factor: `1.07`
- Max Drawdown: `5.40%`

## 对齐说明

- 原 EA 更推荐在 `M1` 上使用，而当前仓库统一验证环境是 `XAUUSD_M15`
- 为保证结果可复现，示例配置将 `really_random` 设为 `false`
- Backtrader 版本保留了随机方向、固定止盈止损和持续在场的教学特征
- 若将 `really_random` 改为 `true`，不同回测运行之间的结果会变化
