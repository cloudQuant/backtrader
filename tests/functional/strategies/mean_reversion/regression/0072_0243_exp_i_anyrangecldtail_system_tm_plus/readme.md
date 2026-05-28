# 0243 Exp i-AnyRangeCldTail System Tm Plus

## 策略来源

- MT5 源码：`ea/0243_Exp_i-AnyRangeCldTail_System_Tm_Plus/exp_i-anyrangecldtail_system_tm_plus.mq5`
- 指标源码：`indicators/1029_i-AnyRangeCldTail_System/i-anyrangecldtail_system.mq5`

## 策略逻辑

- EA 基于 `i-AnyRangeCldTail_System` 的颜色信号交易。
- 指标先在每日 `Time1` 到 `Time2` 的时间区间内统计通道高低点，然后在区间外监控收盘价是否向上或向下突破该通道。
- 颜色切换到多头时开多并平空，切换到空头时开空并平多。
- 开仓附带固定 `SL/TP`。
- 如果启用 `TimeTrade`，持仓超过 `nTime` 分钟后强制平仓。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `M30` 信号周期。

## 与源码一致/差异说明

- 保留了时间区间通道突破、颜色切换反手、固定 `SL/TP` 和按持仓时长强平的主流程。
- 当前版本根据本地指标源码，按 `Time1/Time2` 日内区间构建通道，并在区间外用收盘价突破通道的方式近似还原颜色缓冲区逻辑。
- 原说明使用 `USDJPY M30`，仓库当前没有对应 CSV，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `M30` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_i_anyrangecldtail_system_tm_plus.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `M30` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
