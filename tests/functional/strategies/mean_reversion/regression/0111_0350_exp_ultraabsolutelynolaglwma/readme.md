# 0350 Exp_UltraAbsolutelyNoLagLwma

## 策略来源

- MT5 源码：`ea/0350_Exp_UltraAbsolutelyNoLagLwma/Exp_UltraAbsolutelyNoLagLwma.mq5`
- 指标源码：`ea/0350_Exp_UltraAbsolutelyNoLagLwma/UltraAbsolutelyNoLagLwma.mq5`
- 当前实现：`examples/0350_exp_ultraabsolutelynolaglwma/`

## 策略逻辑

- 基于 `UltraAbsolutelyNoLagLwma` 的颜色区间变化交易。
- 当前近似颜色语义：
  - `1..4` 视为空头区。
  - `5..8` 视为多头区。
- 保留源码真正使用的状态迁移：
  - 上一根位于多头区，当前切回空头区时触发开多并平空。
  - 上一根位于空头区，当前切回多头区时触发开空并平多。
- 保留固定 `SL/TP` 主流程。

## 与源码一致/差异说明

- 当前版本按源码结构保留了 `UltraAbsolutelyNoLagLwma` 颜色区间切换开平仓主流程。
- `TradeAlgorithms` 库文件未直接收录在当前目录中；当前迁移按同仓库内同类模板的单品种单仓语义处理开仓。
- 原指标内部包含多层平滑与区间色阶；当前版本先保留影响交易决策的 `1..4 / 5..8` 颜色区间语义，并用价格区间归一化做可运行近似。
- 原文示例为 `GBPUSD H4`；当前仓库没有对应数据，因此这里使用 `XAUUSD_M15` 重采样到 `H4` 做可运行验证。

## 首轮回测结果

- 数据区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 平仓笔数：`26`
- 期末权益：`99538.00`
- 最大回撤：`2.70%`
- 多头开仓：`13`
- 空头开仓：`13`

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
