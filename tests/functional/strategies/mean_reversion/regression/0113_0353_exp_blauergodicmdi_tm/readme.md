# 0353 Exp_BlauErgodicMDI_Tm

## 策略来源

- MT5 源码：`ea/0353_Exp_BlauErgodicMDI_Tm/Exp_BlauErgodicMDI_Tm.mq5`
- 指标源码：`ea/0353_Exp_BlauErgodicMDI_Tm/BlauErgodicMDI.mq5`
- 当前实现：`examples/0353_exp_blauergodicmdi_tm/`

## 策略逻辑

- 基于 `BlauErgodicMDI` 振荡器交易，支持三种源码模式：
  - `breakdown`：直方图突破零线。
  - `twist`：直方图方向反转。
  - `cloudtwist`：信号云颜色变化。
- 默认使用源码默认模式 `twist`。
- 保留 `TimeTrade` 交易时段控制：超出设定时段时，平掉现有仓位且不再开新仓。
- 保留固定 `SL/TP` 主流程。

## 与源码一致/差异说明

- 当前版本按源码结构保留了三种入场模式和交易时段控制主流程。
- `TradeAlgorithms` 库文件未直接收录在当前目录中；当前迁移按同仓库内同类模板的单品种单仓语义处理开仓。
- 原指标内部使用多层 `XMA` 平滑、云层与彩色直方图；当前版本用 `EMA` 链式近似保留 `hist/up/dn` 三类交易判定序列。
- 原文示例为 `AUDUSD H4`；当前仓库没有对应数据，因此这里使用 `XAUUSD_M15` 重采样到 `H4` 做可运行验证。

## 首轮回测结果

- 数据区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 平仓笔数：`164`
- 期末权益：`100515.10`
- 最大回撤：`1.59%`
- 多头开仓：`51`
- 空头开仓：`113`

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
