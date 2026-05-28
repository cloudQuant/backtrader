# 0013 Simple Pending Orders Time

## 策略概述

该策略是对 MT5 EA `0013_简单待处理订单时间` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M1.csv` 回测，保留了原 EA 的固定时段双向挂单思路：

- 到指定交易开始时间后，同时挂出 `buy stop` 和 `sell stop`
- 两个挂单都带固定止损，不设置固定止盈
- 到指定交易结束时间后，撤销挂单并强制平仓

## 核心逻辑

1. 每到交易开始小时（默认 `15:00`），若当前无持仓、无挂单，则：
   - 在当前价格上方 `Indent` 点挂 `buy stop`
   - 在当前价格下方 `Indent` 点挂 `sell stop`
2. 任一方向成交后，对应形成真实持仓
3. 在交易窗口结束后（默认 `16:00`）：
   - 删除未成交挂单
   - 强制关闭未平仓持仓
4. 进入下一交易日后重复相同步骤

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `trading_start`
- `end_of_trade`
- `indent`
- `stop_loss`
- `lots`
- `magic_number`
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

- 当前版本重点保留原 EA 的“固定时间窗口 + 双向 stop 挂单 + 超时强制退出”结构
- 为了匹配整点时间逻辑，当前优先使用 `M1` 数据
- 该 backtrader 版本已完成可运行验证，并输出了触发次数、交易数和收益统计
