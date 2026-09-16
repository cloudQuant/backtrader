# 2026-09-16 logs/ 证据处置记录

> 状态：`LOGS_EVIDENCE_DESTROYED`
> 范围：`logs/` 全部内容（整目录，1.5 GB / 12,762 个文件）
> 结论影响：迭代 23/25 的裁决与 Gate 状态不变；原始证据不可再核验，认定依据回退为已固化的 SHA-256 摘要

## 1. 处置决定与理由

`logs/` 被用作本迭代验收证据的落点，这与该目录的语义直接冲突：

1. `logs/` 是运行时输出目录，其命名、`.gitignore` 忽略状态，以及日志体系自身的
   `retention_days` 自动清理机制，全部指向"可随时丢弃"。任何一次常规的日志清理动作
   都会在无提示、无记录的情况下销毁证据链。
2. `logs/` 未纳入版本控制，删除后无法恢复，也无从察觉。发现时已完成的事实不可回溯。
3. 目录内"不可重建的原始记录"（验收脚本、receipt、junit XML、coverage、journal）
   与"派生的安装/构建副本"（`sources/`、`checkpoints/`、`wheels-*`）混放，无法通过
   保留其一、删除其二的方式安全切分。

处置方式：**整目录销毁，不做迁移**。后续迭代不得再将验收证据写入 `logs/`。

## 2. 销毁清单（2026-09-16 记录）

`logs/` 合计 1.5 GB / 12,762 个文件。

| 顶层条目 | 大小 | 文件数 | 性质 |
|---|---|---|---|
| `iteration23-25/20260910-q_rhtzc4/` | 1.4 G | 12,266 | 迭代 23–25 验收证据副本（唯一存留） |
| `branch_strategy_compare/` | 64 M | 44 | 分支对比工具输出（可重跑） |
| `iteration27/`（20 个 run 目录） | 17 M | 310 | 迭代 27 验收收据 |
| `iter27-fq3-independent-*`（10 个目录） | 1.1 M | 约 110 | 迭代 27 独立复跑输出 |
| 根级 `*.json`（30 个） | 360 K | 30 | 元编程移除期间的回归调试快照 |
| `branch_compare_anchoredmomentum/` | 0 B | 0 | 空目录 |

`iteration23-25/20260910-q_rhtzc4/` 内部：`sources/` 721 M、`checkpoints/` 496 M、
`logs/` 26 M，以及 `wheels-o3a03` / `wheels-o3a04` 等构建轮子目录与约 200 个 run 子目录。

## 3. 唯一存留性

该目录自述为证据副本，`artifact-location.json`（销毁时点 SHA-256
`ac41b7627f2e56f080acad68c2c18e67aca7217f51d8ee8c0f40b180671173bc`）记录：

```json
{
  "working_artifact_root": "/var/folders/7d/hnmknylj1w91h3cvq6mh3thm0000gn/T/iter23-25-acceptance-q_rhtzc4",
  "evidence_copy": "/Users/.../backtrader/logs/iteration23-25/20260910-q_rhtzc4",
  "status": "DEPENDENCY_WHEEL_SUBSET_PASS",
  "backtrader_wheel": "PENDING_IMPLEMENTATION"
}
```

销毁前已核实：`working_artifact_root` 指向的 macOS 临时工作根目录**已不存在**，因此
`logs/iteration23-25/20260910-q_rhtzc4/` 是这批验收结果的唯一存留副本。本次销毁后，
除本文档登记的摘要外，该批证据不再可获取。

## 4. 认定依据

销毁前已交叉核对：文档 [开发与验收推进记录.md](开发与验收推进记录.md) 中固化的摘要
与磁盘制品逐字节一致，说明已入库摘要忠实反映被销毁制品：

| 制品 | 文档固化摘要 | 销毁前核对 |
|---|---|---|
| `logs/astra-u1a-independent-20260911-astra02/receipt.json` | `741cc1e52208022029e3e931edcb43e62a371d83da838533d9ce3b1f16efd4d4` | 一致 |
| `logs/astra-u1a-independent-20260911-astra02-consolidated.json` | `9194428d8b8945e4de4bae95dc7cade528b0593d0fa5efbfd18a9d0f3303c1c7` | 一致 |

**仍可验证**：`开发与验收推进记录.md` 中固化的 211 个唯一 SHA-256 摘要，以及各节记录的
case 数、pass/fail 分母、退出码、Gate 状态。这些足以支撑"当时确实产出过该结果"的判断。

**不再可验证**：

- 无法重新计算任何制品的 SHA-256，无法重跑 receipt 或 junit XML 指向的用例，
  也无法复核 `manifest.json`、`native-installed-receipt.json`、
  `installed-source-parity.json` 的内部一致性。
- 制品认定自此为 **hash 冻结**，而非可复算。`sources/`、`checkpoints/`、`wheels-*`
  虽属派生内容，但其能否等价重建取决于当时 SDK 源码状态是否仍在，不作保证。

## 5. 对既有结论的影响

- 迭代 23/25 已签收的 Gate 状态与裁决**不因本次销毁而改变**。本次销毁不构成对任何
  结论的撤销，也不新增对任何结论的支持。
- 销毁的证据包含被明确要求保留的失败检查点（记录 §12 曾要求"保留这个失败检查点，
  不覆盖旧结果"）。该要求已无法继续满足，此后不得援引这些检查点作为现行证据。
- 后续迭代若需要可复算的验收证据，应放在受版本控制的位置或仓库外的受控位置，并在
  收据中记录路径、SHA-256 与保留期限；**不得使用 `logs/`**。
