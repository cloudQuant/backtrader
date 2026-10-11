# R5a（1/2 步）— 选层判定器 + `015` 模板落地（2026-10-11）

基线提交 `28767cc27`。本步只做一个示例（015）作为模板，其余 7 个在下一步照搬，
避免"八个文件同时改半成品"的不一致状态。

## 1. 新增件

- `examples/_support/entry_tier.py`：纯标准库、零仓库依赖的选层判定器。等级 `dry < replay < live`；
  **CLI 模式参数只能保持或下调 `entry.tier`，上调即冲突**；`entry` 非映射 / `tier` 非字符串 / 未知取值 /
  `entry: null` → `config_tier_invalid`（由调用方 BLOCKED，绝不回落到 live）。`--allow-write` 与选层正交，
  判定器不读它。返回的 `TierDecision` 带 `as_evidence()` 四个字段。
- `tests/unit/test_iteration43_entry_tier.py`：**26 项**（4×4 真值表 + 6 种畸形配置 + 冲突/证据/缺省兼容）。
- 015 目录内 `entry_tier.py` 为逐字节副本，已加入 `test_examples_self_contained.py` 的 vendored 漂移守卫。

## 2. 015 的接线

`run.py`：新增 `--dry`（进互斥组）→ 读原始配置 → 判定 → 冲突/非法在**任何 handler 之前**
`BLOCKED` 并输出 `tier` 证据 → 否则按 `effective_tier` 分发；dry/replay 报告加
`tier` + `write_grant_result`，live 的 summary 同样落这两个字段。

`legacy_runner.py:648-653`：按仓库既有的 `live_adapter` 先例，把 `entry` **投影掉**再进严格校验器
（比 012_1 的"允许且忽略"更严：`entry` 不进入回放契约的根键集合，其校验责任在 `run.py`）。

`README.md`：补 `--dry` 与 `entry.tier` 契约；并修正一处文档与实现不符 ——
`--mode/--purpose/--output-dir` 属 `legacy_runner.py` 的解析器（`:2637-2641`），原文误写成 `run.py`。

## 3. 行为验证（在**临时副本**里跑，因此顺带覆盖 R7 的"复制即可运行"）

| 场景 | 退出 | 结果 |
|---|---|---|
| 无 `entry`，无 flag | 0 | `DRY`，`tier=default_dry`（旧命令与旧行为逐字不变） |
| `tier: replay`，无 flag | 0 | `LOCAL_REPLAY_PASS`，`config_default` |
| `tier: backtest` + `--dry` | 0 | `DRY`，`cli_override` |
| `tier: dry` + `--live` | 2 | `BLOCKED/config_tier_conflict`（**不上调**） |
| `tier: replay` + `--live` | 2 | `BLOCKED/config_tier_conflict` |
| `tier: live` + `--replay` | 0 | `LOCAL_REPLAY_PASS`（下调允许） |
| `tier: live` + 无 flag（用 `--allow-write` 探活，零网络） | 2 | 到达 `run_live` 的零写拒绝 `write_tier_not_implemented…` ⇒ 证明确实分发到 live 通道 |
| `tier: nonsense` | 2 | `BLOCKED/config_tier_invalid`，`effective_tier` 仅作占位、未进任何 handler |

live 探活刻意用 `run_live` 内的零写拒绝来证明分发，**未触发任何 provider/网络路径**。

## 4. 门禁

`test_iteration43_entry_tier.py` + `test_examples_self_contained.py` 合计 **57 passed / 3 failed**
（3 项 = R0 命名的既有红）；`-k "highfreq or iteration43"` **242 passed**；015 仓库内 `dry` = `DRY`、
`--replay` = `LOCAL_REPLAY_PASS`；`ruff check examples` 维持 176。

## 5. 下一步（R5a-2）

其余 7 个入口照搬：012_1/012_2（其 `entry` 段已存在但语义是 venue/credentials/policy，且校验器"允许且忽略"，
需统一到"投影 + 严格校验 `tier`"）、013_1/013_2/013_3（先确认各自严格校验器是否会拒 `entry`）、
014_1/014_2。每个都要：`--dry`、判定器副本 + 守卫条目、`entry` 投影、`tier`/`write_grant_result` 证据、
README 契约、以及本文件 §3 那张表的原地复跑。014_2/015 的 `tier: live` 已可用；
其余 6 个在 R5b 补齐无写观察通道前，`tier: live` 只会得到各自的写授权 BLOCKED（诚实现状，不算 config-live 能力完成）。
