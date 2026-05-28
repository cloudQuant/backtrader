# 0922 ASCtrend

## 策略概述

该示例是 MT5 EA `Exp_ASCtrend` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `ASCtrend` 指标，并在指标箭头出现时交易。

## 指标重建

- 使用三个 Williams %R 句柄（周期 3 / 4 / 3+RISK*2）
- 通过 `MRO1/MRO2` 检测近期 WPR 是否突破 `x1=67+RISK` 或 `x2=33-RISK` 阈值
- 选择对应 WPR 周期后，判断当前值与阈值关系
- 若 WPR 从中性区穿越到对侧，生成买入/卖出箭头信号
- ATR 风格的平均波幅用于计算箭头价格偏移

## 交易逻辑

- 买入箭头出现 → 做多，同时平掉空头
- 卖出箭头出现 → 做空，同时平掉多头
- 若当前柱无信号但持有仓位，回扫历史寻找最近反向箭头来决定平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_asctrend.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
