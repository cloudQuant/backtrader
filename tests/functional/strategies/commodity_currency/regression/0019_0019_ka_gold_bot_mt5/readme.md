# 0019 KA-Gold Bot MT5

## 策略概述

该策略是对 MT5 EA `0019_KA-Gold_Bot_MT5/ka-gold_bot.mq5` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M5.csv` 作为单周期回测样例，保留了原 EA 的主要结构：

- `EMA10`
- `EMA200`
- 基于均线中轨和平均波幅构造的 Keltner 通道
- 固定 `SL/TP`
- 时间过滤
- 百分比资金管理 / 固定手数
- 追踪止损

## 核心逻辑

1. 计算三组核心量：
   - `EMA10`
   - `EMA200`
   - `Keltner Mid = EMA(period)`，上下轨 = 中轨 ± 最近 `period` 根 K 线平均波幅
2. 多头信号同时满足：
   - 最新收盘价站上 Keltner 上轨
   - 最新收盘价高于 `EMA200`
   - `EMA10` 从上一根位于上轨下方，到当前上穿上轨
3. 空头信号同时满足：
   - 最新收盘价跌破 Keltner 下轨
   - 最新收盘价低于 `EMA200`
   - `EMA10` 从上一根位于下轨上方，到当前下穿下轨
4. 仅在允许交易时间窗口内开仓
5. 开仓后设置固定 `SL/TP`，并在盈利达到阈值后启动追踪止损

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `inp_keltner_period`
- `inp_ema10`
- `inp_ema200`
- `inp_sl_pips`
- `inp_tp_pips`
- `inp_max_spread`
- `inp_trailing_trigger`
- `inp_trailing_stop`
- `inp_trailing_step`
- `inp_time_filter`
- `inp_start_hour`
- `inp_end_hour`
- `isvolume_percent`
- `inp_risk`
- `inpuser_lot`

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

- 原 EA 使用当前图表周期；当前 backtrader 迁移版本先采用现有可用的 `M5` 数据进行验证
- 当前版本保留了原 EA 的单周期信号结构、时间过滤、仓位控制和 trailing stop 主流程
- 已在策略目录中保留独立 `config.yaml`、`run.py` 和本说明文件，便于后续迭代
