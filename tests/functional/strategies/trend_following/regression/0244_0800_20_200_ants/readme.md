# 0800 20/200 AntS

## 策略概述

该策略是对 MT5 EA `0800_20_200_expert_v_4.2_AntS` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的核心结构：

- 固定交易时段入场
- 比较两根历史开盘价的差值来判断多空方向
- 每笔订单挂固定止损和止盈
- 持仓超过最大存活时间后强制平仓
- 亏损后按倍数放大下一笔仓位

## 核心逻辑

1. 在每根新 K 线时读取 `t1` 和 `t2` 对应历史开盘价
2. 当 `Open[t2] - Open[t1] > Delta_L * Point` 时生成做多信号
3. 当 `Open[t1] - Open[t2] > Delta_S * Point` 时生成做空信号
4. 仅在 `trade_hour` 对应小时允许开新仓
5. 开仓后同时设置固定 `SL/TP`
6. 如果上一笔交易亏损，则下一笔仓位按 `big_lot_size` 放大
7. 如果持仓超过 `max_open_hours`，则强制平仓

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `t1`
- `t2`
- `delta_l`
- `delta_s`
- `take_profit_l`
- `stop_loss_l`
- `take_profit_s`
- `stop_loss_s`
- `auto_lot`
- `big_lot_size`
- `one_mult`
- `trade_hour`
- `max_open_hours`

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

当前参数下的回测结果：

- Trades: `103`
- Buy Entries: `48`
- Sell Entries: `55`
- Net P&L: `-95,280.91`
- Win Rate: `73.79%`
- Profit Factor: `0.48`
- Max Drawdown: `97.34%`
- Sharpe Ratio: `-2.47`

## 对齐说明

- 原 EA 文档明确推荐在 `EURUSD H1` 上使用
- 当前统一验收环境为 `XAUUSD M15`，与原策略推荐品种和周期不一致
- 原 EA 的自动手数和亏损后放大量机制非常激进，在当前数据集上造成了极深回撤
- 当前 Backtrader 迁移版本重点在于保留原始入场、止盈止损、超时平仓和仓位放大框架，而不是重新优化参数
