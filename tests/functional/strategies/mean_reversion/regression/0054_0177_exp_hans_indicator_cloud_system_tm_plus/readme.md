# 0177 Exp_Hans_Indicator_Cloud_System_Tm_Plus

## 策略来源

- MT5 源码：`ea/0177_Exp_Hans_Indicator_Cloud_System_Tm_Plus/exp_hans_indicator_cloud_system_tm_plus.mq5`
- 指标源码：`ea/0177_Exp_Hans_Indicator_Cloud_System_Tm_Plus/hans_indicator_cloud_system.mq5`

## 策略逻辑

- 信号部分与 `0176` 相同：基于 `Hans_Indicator_Cloud_System` 的两段日内区间突破颜色切换开平仓。
- 当收盘价突破上轨时进入多头颜色状态；跌破下轨时进入空头颜色状态。
- 从非多头切换到多头时开多并平空；从非空头切换到空头时开空并平多。
- 在 `0176` 基础上增加固定持仓时间离场：持仓超过 `hold_minutes` 后立即平仓。

## 与源码一致/差异说明

- 当前实现直接按指标源码重建 `Hans` 通道和颜色状态，不依赖 MT5 的 `TradeAlgorithms.mqh`。
- 原版默认示例为 `EURJPY M30`，当前仓库没有对应原始数据，因此这里使用 `XAUUSD_M15.csv` 并重采样到 `M30` 信号层做可运行验证。
- Backtrader 无法逐 tick 复刻 MT5 的订单服务器校验细节，因此结果应视为可运行的逻辑迁移样例。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_exp_hans_indicator_cloud_system_tm_plus.py`：策略实现入口。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
