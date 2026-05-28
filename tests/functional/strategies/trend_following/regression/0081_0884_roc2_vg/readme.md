# 0884 ROC2_VG

## 策略概述

该示例是 MT5 EA `Exp_ROC2_VG` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `ROC2_VG` 指标，在两条 ROC 线云图颜色翻转时交易。

## 指标重建

- ROC1：`ROCPeriod1=8`，类型 `MOM`（价格差）
- ROC2：`ROCPeriod2=14`，类型 `MOM`（价格差）
- DRAW_FILLING：ROC1 > ROC2 → 多头色；ROC1 < ROC2 → 空头色
- 支持 5 种 ROC 计算类型：MOM, ROC, ROCP, ROCR, ROCR100

## 交易逻辑

- 云图从空头翻转为多头 → 买入
- 云图从多头翻转为空头 → 卖出
- 支持 `Invert` 反向交易模式
- 保留固定 `SL/TP`

## 文件

- `strategy_roc2_vg.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
