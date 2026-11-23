# SPLIT-03b 离线热路径性能护栏报告（T-037 / S-11）

> 采集日期：2026-11-23　证据等级：**UNIT / OFFLINE_BENCHMARK**（无网络、无真实账户）
> 环境：Windows / CPython 3.11.5，5,000 条终态 bar × 3 轮中位数 + 20,000 次校验微基准

## 1. 实测指标

| 指标 | 基线 / 目标 | 实测结果 | 相对变化 | 结论 |
| --- | --- | ---: | ---: | --- |
| `BtApiFeed`（5,000 bars 线投递） | 兼容基线 | `136.34 ms`（`27.27 us/bar`） | `0.00%` | 基线锚定 |
| `DirectBtApiFeed`（5,000 bars 线投递） | 劣化 <= 5% | `135.30 ms`（`27.06 us/bar`） | `-0.76%` | PASS |
| `GatewayBtApiFeed`（5,000 bars 线投递） | 劣化 <= 5% | `135.50 ms`（`27.10 us/bar`） | `-0.62%` | PASS |
| `validate_gateway_readiness_proof`（20,000 次） | 轻量热路径 < 20 us/call | `3.20 us/call` | — | PASS |
| `normalize_shutdown_summary`（20,000 次） | 轻量收尾 < 10 us/call | `0.75 us/call` | — | PASS |

## 2. 边界声明

- 本报告仅验证 Backtrader 进程内 Feed/Broker 拆分引入的对象投递、门禁与收尾归一化开销；不代表实盘交易所/网络延迟或 SimNow 性能。
