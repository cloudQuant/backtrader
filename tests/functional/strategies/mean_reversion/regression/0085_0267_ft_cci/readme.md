# 0267 FT_CCI

## 策略来源

- MT5 源码：`ea/0267_FT_CCI/ft_cci.mq5`

## 策略逻辑

- EA 仅在新柱线上处理信号。
- 当 `CCI < cci_down` 时，先平空后开多。
- 当 `CCI > cci_up` 时，先平多后开空。
- 源码实际开仓时附带固定 `SL/TP`。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `CCI` 阈值反手和固定 `SL/TP` 主流程。
- readme 文字称“未设止损和止盈”，但源码实际定义并传入了 `Stop Loss / Take Profit`；当前实现以源码行为为准。
- 当前 `CCI` 使用本地安全实现，避免平盘段触发除零。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ft_cci.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
