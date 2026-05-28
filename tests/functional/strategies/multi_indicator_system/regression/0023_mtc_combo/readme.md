# 0790 MTC Combo

## 策略概述

该策略是对 MT5 EA `0790_MTC_Сombo` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并按源码默认参数 `pass=10` 运行，此时策略退化为基础交易系统：

- 基础交易系统使用 `MA` 斜率决定方向
- `Supervisor()` 为感知机监督层预留扩展
- 默认参数下不启用训练后的感知机覆盖逻辑
- 使用固定 `SL/TP`
- 任意时刻只保持单一持仓

## 核心逻辑

1. 仅在新 bar 上进行决策
2. 若当前已存在本策略持仓，则不重复开仓
3. `basicTradingSystem()` 返回 `MA(bar) - MA(bar+1)`
4. 当 `Supervisor() > 0` 时做多，否则做空
5. 使用固定止损、止盈完成出场
6. 当 `pass_mode` 为 `2/3/4` 时，可分别启用源码中的感知机覆盖路径

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `bar`
- `ma_period`
- `tp1` / `sl1`
- `pass_mode`
- `p2/p3/p4`
- `x12..x44`

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

- Trades: `3021`
- Net P&L: `247.64`
- Win Rate: `48.96%`
- Profit Factor: `1.03`
- Max Drawdown: `0.33%`

## 对齐说明

- 原 EA 设计重点是配合多步优化训练的感知机网络；当前迁移版本保留了 `Supervisor()`、三组感知机和 BTS 组合框架
- 源码默认 `pass=10`，实际运行路径就是 `basicTradingSystem()`，因此当前验证先以该默认路径为准
- 原源码中 `iCCI` 相关路径被注释掉，当前版本同样仅实现活跃使用的 `MA` 基础系统与感知机分支
