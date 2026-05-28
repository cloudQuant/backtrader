# 0176 Exp_Hans_Indicator_Cloud_System

## 策略来源

- MT5 源码：`ea/0176_Exp_Hans_Indicator_Cloud_System/exp_hans_indicator_cloud_system.mq5`
- 指标源码：`ea/0176_Exp_Hans_Indicator_Cloud_System/hans_indicator_cloud_system.mq5`

## 策略逻辑

- 指标按日内固定区间先后统计两个通道：`04:00-08:00` 与 `08:00-12:00`。
- 每个区间结束后，用该区间高低点加减 `pips_for_entry` 构造突破通道。
- 当收盘价突破上轨时，颜色切换到多头状态；跌破下轨时切换到空头状态。
- EA 读取颜色状态：从非多头切换到多头时开多并平空；从非空头切换到空头时开空并平多。
- 保留固定 `SL/TP` 和方向开平仓许可。

## 与源码一致/差异说明

- 当前实现不依赖 MT5 的 `TradeAlgorithms.mqh`，而是直接按源码中的颜色切换规则重建信号。
- 原版默认示例为 `EURJPY M30`，当前仓库没有对应原始数据，因此这里使用 `XAUUSD_M15.csv` 并重采样到 `M30` 信号层做可运行验证。
- Backtrader 无法逐 tick 复刻 MT5 服务器成交细节，因此结果应视为可运行的逻辑迁移样例。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_exp_hans_indicator_cloud_system.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
