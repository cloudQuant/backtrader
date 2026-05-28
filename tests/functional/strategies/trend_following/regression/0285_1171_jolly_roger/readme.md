# 1171 Jolly Roger EA

## 策略概述

该策略是对 MT5 EA `1171_Jolly_Roger_EA_版` 的 Backtrader 迁移版本。

原 EA 的核心不是直接市价进场，而是：

- 用 `RSI(14)` 判断超买超卖
- 在无持仓、无挂单时批量挂 3 笔同方向 stop 单
- 每笔挂单使用总可用保证金推导出来的动态手数的三分之一
- 成交后按固定 `TP/SL` 管理，并不断向有利方向移动止损
- 未成交的挂单若离当前价格过远，则向现价方向重挂

## 迁移说明

Backtrader 版本保留了以下关键行为：

- `RSI < RSILevel` 时提交 3 笔 `BUY_STOP`
- `RSI > 100 - RSILevel` 时提交 3 笔 `SELL_STOP`
- `Lots = clamp(FreeMargin / 2000, 0.1, 15)` 后再均分成 3 笔
- 价格偏离挂单超过 `20 * Point` 时重挂剩余 stop 单
- 对已成交子仓位逐笔维护 `TP/SL` 与移动止损

## 近似项

由于 OHLC 回测数据不包含逐 tick `Ask/Bid` 与真实券商 `SYMBOL_TRADE_STOPS_LEVEL`：

- 使用 bar 级价格近似挂单与止损移动
- `spread_points` 与 `stop_level_points` 作为可调参数保留在配置文件中

## 文件

- `strategy_jolly_roger.py` - 数据加载与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 周期：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- Bars：`6129`
- Signal count：`363`
- Buy fills：`135`
- Sell fills：`429`
- Closed trades：`187`
- Wins：`94`
- Losses：`93`
- Win rate：`50.27%`
- Initial cash：`100000.00`
- Final value：`1.00`
- Net PnL：`-99999.00`
- Total return：`-100.00%`
- Profit factor：`0.72`
- Sharpe ratio：`-8.40`
- Annual return：`-100.00%`
- Max drawdown：`105.72%`
- SQN：`-1.13`
