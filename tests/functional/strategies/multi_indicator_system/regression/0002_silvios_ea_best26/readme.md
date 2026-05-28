# 0001 Silvios EA Best26

## 策略概述

该策略是对 MT5 EA `0001_SilviosEAbest26` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M5.csv` 进行回测，保留了原 EA 的核心思想：

- 使用 RSI 作为主要入场过滤条件
- 基于固定止损/止盈进行仓位管理
- 支持保本移动
- 支持追踪止损
- 每次仅管理当前单一净头寸

## 核心逻辑

1. 从 MT5 导出的 `XAUUSD M5` 数据中读取 OHLCV 与 `spread`
2. 计算 RSI 指标
3. 当价格与指标条件满足时开多或开空
4. 开仓后按照原 EA 风格管理仓位：
   - 初始止损/止盈
   - 盈利达到阈值后移动到保本
   - 继续盈利后启动追踪止损
5. 订单关闭后重置内部状态，等待下一次信号

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `rsi_period`
- `rsi_buy_level`
- `rsi_sell_level`
- `stop_loss_points`
- `take_profit_points`
- `breakeven_trigger_points`
- `trailing_stop_points`
- `point`
- `price_digits`

具体数值以当前 `config.yaml` 为准。

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M5.csv`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 该版本优先保留原 EA 的交易逻辑与参数结构
- 已处理 backtrader 中订单成交后内部状态同步问题
- 当前实现基于单净头寸模型运行，适合作为 backtrader 回测样例
