# 0356 Exp_AbsolutelyNoLagLwma_X2

## 策略来源

- MT5 源码：`ea/0356_Exp_AbsolutelyNoLagLwma_X2/exp_absolutelynolaglwma_x2.mq5`
- 指标源码：`ea/0356_Exp_AbsolutelyNoLagLwma_X2/absolutelynolaglwma.mq5`
- 当前实现：`examples/0356_exp_absolutelynolaglwma_x2/`

## 策略逻辑

- 使用两个 `AbsolutelyNoLagLwma` 层：
  - 慢层颜色决定趋势过滤方向。
  - 快层颜色翻转决定入场时机。
- 当慢层颜色为上升色时，只接受快层切回上升色的多头触发。
- 当慢层颜色为下降色时，只接受快层切回下降色的空头触发。
- 保留慢层方向平仓开关，以及固定 `SL/TP` 主流程。

## 与源码一致/差异说明

- 当前版本按源码结构保留了“慢层趋势过滤 + 快层颜色翻转触发”的双时间框架主流程。
- `TradeAlgorithms` 库文件未直接收录在当前目录中；当前迁移按同仓库内同类模板的单品种单仓语义处理开仓。
- 原 `AbsolutelyNoLagLwma` 指标通过内部平滑后的无滞后 LWMA 斜率给出三色线；当前版本用 `WMA` 斜率近似保留颜色语义。
- 原文示例为 `USDJPY` 上 `H6` 慢层、`M30` 快层；当前使用 `XAUUSD_M15.csv` 重采样近似运行环境。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
