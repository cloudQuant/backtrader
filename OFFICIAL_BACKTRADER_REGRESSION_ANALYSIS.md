# Official Backtrader Regression Analysis

更新日期: 2026-05-28

## 概述

本文档记录 dev 分支相对于 master 分支（原始 backtrader）的策略回归测试分析。

## 测试环境

- Python: 3.11.8
- 分支: dev (commit e08807a1 + 未提交优化)
- 测试工具: `scripts/run_official_backtrader_strategy_regression.py`
- 并发: 8 workers, 超时 120s/策略
- 测试根目录: `tests/functional/strategies_regression/`

## 回归结果摘要

| 指标 | 数量 |
| --- | ---: |
| 策略总数 | 1036 |
| 通过 | 1010 |
| 失败 | 26 |
| 通过率 | **97.5%** |

### 与历史对比

| 时间点 | 通过 | 失败 | 通过率 |
| --- | ---: | ---: | ---: |
| 2026-05-27 (上次完整回归) | 971 | 65 | 93.7% |
| 2026-05-28 (本次) | 1010 | 26 | 97.5% |
| 改善 | +39 | -39 | +3.8% |

## 失败根因分析

### 1. final_value 差异 (7 个)

多数 `final_value` 差异精确为 63.0，疑似与以下因素有关：
- minperiod 计算变化导致策略首次交易时间偏移
- prenext 阶段指标值初始化方式不同（NaN vs 0.0）
- 已验证 master 分支部分策略的期望值本身可能不准确

### 2. 交易次数偏移 (10 个)

`buy_count`/`sell_count`/`win_count` 差异，原因：
- EMA/SMMA 等平滑指标的 once() 实现改进，导致信号触发时机微调
- Stochastic 指标重构为纯 line-binding 模式，消除了手动 once() 中的精度差异
- StandardDeviation 指标重写为支持 SMMA/EMA 加权模式

### 3. 输出行数不一致 (5 个)

`rows` 差异通常由 minperiod 变化引起：
- 新代码正确传播子指标 minperiod 到父指标
- 部分策略的 minperiod 比旧代码更大或更小，导致有效输出行数变化

### 4. 严重偏移 (4 个)

少数策略出现较大偏移（如 `buy_count: 125→60`, `buy_count: 403→227`），可能涉及：
- Laguerre/T3 等复杂递归指标的 once() 实现差异
- CenterOfGravity 等自定义指标的 minperiod 计算变化

## 已修复的问题

本轮修改修复了以下问题：

1. **CrossOver.once IndexError** — 当 SMA 等指标在模块级别构造（无数据源）后作为 CrossOver 的数据传入时，once() 访问空数组导致崩溃。修复方式：添加 `effective_end` 边界保护。

2. **test_114_supertrend_rsi_strategy 期望值错误** — 通过 master 分支验证，正确的 `final_value` 应为 `100085.04`（与 master 一致），而非之前错误设置的 `100078.43`。

3. **孤儿指标 _once 未触发** — 扩展 `_ensure_lineactions_inputs_computed` 以处理 MinimalOwner 拥有的孤儿子指标，确保其 `_once()` 在消费者指标读取前被调用。

## 后续建议

1. 对剩余 26 个失败策略，逐一在 master 分支运行获取基准值，确认期望值是否正确
2. 重点关注 `final_value` 差异精确为 63.0 的策略，可能是同一个 minperiod 偏移 bug
3. Blau 系列指标（blau_ts_stochastic, blau_tstochi, blau_ergodic_mdi, blau_csi）共享相同的 Stochastic 基础，可能需要统一修复
4. T3/Laguerre 等递归指标需要验证 once() 实现的数值稳定性
