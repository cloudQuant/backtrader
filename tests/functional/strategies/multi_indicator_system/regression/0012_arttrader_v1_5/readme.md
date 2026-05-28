# 0313 Arttrader v1.5

## 策略来源

- MT5 源码：`ea/0313_Arttrader_v1_5/arttrader_v1_5.mq5`

## 策略逻辑

- 使用 `H1 EMA(open, ema_speed)` 的斜率作为方向过滤。
- 当 EMA 斜率处于指定区间内，并且当前 K 线满足特定收盘位置条件时触发入场。
- 过滤过大单根蜡烛和双根跳变，避免异常波动期间入场。
- 使用 `open_price` 参考位驱动“smart stop”离场，同时保留 emergency SL/TP。
- 若上一根成交量不高于 `min_volume`，则强制结束当前持仓。
- 同时最多允许一笔持仓；若出现异常多仓，原 EA 直接全平，当前版本保持单净仓近似。

## 与源码一致/差异说明

- 保留了单仓限制、EMA 斜率过滤、大蜡烛过滤、智能退出、应急止损止盈和量能退出主流程。
- 原 EA 默认运行在 `H1` 图表；当前版本使用 `XAUUSD_M15` 数据并额外构造 `H1` 重采样 EMA 过滤，以近似原始执行环境。
- `smart stop` 中用到的 `open_price` 调整值和 imagined spread 调整被保留下来，但执行时仍遵循 Backtrader 单净仓模型。
- 由于原参数针对 `EURUSD H1`，为在 `XAUUSD` 数据上完成功能验证，当前 `config.yaml` 放宽了 `slope_small/slope_large`、`big_jump/double_jump` 以及 `slip_begin/slip_end` 的尺度，使其适配金价波动级别；这属于数据尺度调整，不改变策略结构。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_arttrader_v1_5.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
