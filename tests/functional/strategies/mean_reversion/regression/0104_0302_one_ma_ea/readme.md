# 0302 One MA EA

## 策略来源

- MT5 源码：`ea/0302_一款均线_EA/one_ma_ea.mq5`

## 策略逻辑

- 使用单条移动平均线构造上下通道：`MA + level_high` 与 `MA - level_low`。
- 当当前 bar 的低点回到 `MA` 与上沿之间，且开盘仍在上沿之外时，触发做多信号。
- 当当前 bar 的高点回到下沿与 `MA` 之间，且开盘仍在下沿之外时，触发做空信号。
- 同方向已有仓位时不重复开仓。
- 保留固定手数与固定止损止盈。

## 与源码一致/差异说明

- 保留了单 MA 通道回归入场的主信号逻辑。
- 原 EA 可直接指定 `MA/OHLC` 读取 bar 偏移；当前版本保留 `current_bar_ma` 与 `current_bar_ohlc` 参数做近似索引。
- 当前回测使用仓库可用的 `XAUUSD_M15.csv` 数据进行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_one_ma_ea.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
