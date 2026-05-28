# 0375 Modified Moving Averages

## 策略来源

- MT5 源码：`ea/0375_改编版移动平均线/modified_moving_averages.mq5`
- 当前实现：`examples/0375_modified_moving_averages/`

## 策略逻辑

- 使用 `SMA(12)` 并施加 `MovingShift=6` 的位移均线。
- 当当前柱从均线下方向上穿越时开多；从均线上方向下穿越时开空。
- 持仓后若出现反向穿越则平仓，同时保留固定 `SL/TP`。

## 与源码一致/差异说明

- 原 EA 在 `Lots<0` 时直接把 `-Lots` 当作固定手数；默认参数 `Lots=-0.1` 因而等价于固定 `0.1` 手，当前迁移直接按固定手数实现该默认路径。
- 原 EA 还支持 `MaximumRisk/DecreaseFactor` 的动态手数调节；当前版本未额外复现该资金管理分支。
- 原源码在净值模式和对冲模式下都只选择当前品种的同 `magic` 仓位；当前 Backtrader 版本按单净仓语义执行。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
