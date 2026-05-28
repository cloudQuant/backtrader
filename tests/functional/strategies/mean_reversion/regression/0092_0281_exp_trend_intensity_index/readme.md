# 0281 Exp Trend Intensity Index

## 策略来源

- MT5 源码：`ea/0281_Exp_Trend_Intensity_Index/Exp_Trend_Intensity_Index.mq5`

## 策略逻辑

- 基于 `Trend_Intensity_Index` 振荡器颜色变化产生信号。
- 当颜色从低位区切出时，触发买入并允许平空。
- 当颜色从高位区切出时，触发卖出并允许平多。
- 可分别控制 `buy_pos_open/sell_pos_open` 与 `buy_pos_close/sell_pos_close`。
- 开仓附带固定 `SL/TP`。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `Trend_Intensity_Index` 颜色切换驱动的开平仓主流程。
- 原自定义指标当前以本地 `TII` 代理实现近似，不是逐缓冲复刻原指标。
- 原说明示例为 `USDJPY H4`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_exp_trend_intensity_index.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
