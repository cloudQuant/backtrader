# 迭代42 完成度审计清单（2026-10-10 起草；周一实盘后终版）

把目标逐条映射到交付物与证据；本清单即 R9 验收报告的主干，周一结果落地后只更新
状态与数值。

## 目标分解 × 证据矩阵

| # | 目标要求 | 交付物 | 证据（仓库内） | 状态 |
| --- | --- | --- | --- | --- |
| 1 | 8 个示例收敛标准四件套（README.md + config.yaml + `<name>_strategy.py` + run.py）；dry/`--replay`/`--live`；退出码 0/1/2/3；证据 JSON | 8 个目录 | `r9-offline-sweep-2026-10-10.md`（dry/replay 8/8 全绿）+ 登记离线冒烟 8/8 PASS + r1–r8 各记录 + **修复轮后 8/8 dry+replay 复跑于当日 HEAD 全绿（2026-10-10 午后：012_1/012_2 FORMULA_CHECK_PASS；013_1/013_2/013_3/014_1/014_2/015 DRY+LOCAL_REPLAY_PASS）** | ✅ 完成 |
| 2 | 期货/期权示例 SimNow **有界真实成交往返** | 013_3 / 013_1 / 013_2 / 014_1 写 drill；014_2 观察层 | R1/R4/R5/R6/R7 记录（实现与离线链）；014_1 首跑彩排（7x24 涨跌停闸门干净 BLOCKED，R6 记录）；014_2 7x24 陈旧事件钟 BLOCKED（r7 记录）；**周一六步计划待执行** | ⏳ 周一窗口 |
| 3 | 015 tick 高频真实贯通（HFT 结论明确排除） | 观察层 | `c13177459` + `r8-015-observation-tier-2026-10-10.md`（真实三腿 tick、零写、`OBSERVATION_PASS`；准入边界诚实标注） | ✅ 完成（观察层口径） |
| 4 | 加密示例 OKX/Binance Demo 往返 | 012_1 / 012_2 | R2 记录（资格窗口过期→零代码翻转，属冻结研究工件治理=用户决策）；R3 记录（HFT 准入结构门=迭代外） | ⛔ 外部门（证据化 BLOCKED+翻转路径） |
| 5 | 过程中按最佳实践改进迭代计划 | 修订案 | `a7d2cfc52`（R7/R8 观察层修订）；计划内 R0/R6–R8 修订；`monday-live-run-plan-2026-10-12.md`（含 argv 预检与彩排事实） | ✅ |
| 6 | bt_api_py 及其子包按需修复 | — | 本轮记录审计（r1–r9 + 组件记录）：无遗留 SDK 待修项；唯一 SDK 相关注记为既有环境性基线（anaconda 深层子模块 identity） | ✅（无待修） |
| 7 | 用 gateway/risk/monitor/execution 组件测试策略并修复问题 | 边界 + 矩阵 | `test_iteration42_component_boundaries.py` 42 项（入口零组件导入）+ optional16 dry 矩阵 32/32 + 假场所×真 SDK 挂载 5 项 + iteration-41 optional16 真实矩阵 16/16（binance C01+T03 参考；okx/simnow 按设计保持直连） | ✅ |
| 8 | 验收后提交各自 dev | 提交链 | 主仓 dev：`eb3da84f3`(R1) `7cfad68bc`(R2) `90cf8914a`(R3) `0150641a3`(R4) `e91e3638b`(R5) `8c067982b`+`8c5414496`(R6) `adb1fb7a9`(R7) `c13177459`(R8) `972a183b2`/`7b68e19be`/`41929f556`/`92d5a3378`/`cebde48f6`(R9 离线) + 周一前修复轮 `1477ad469`/`4d66770cb`/`c453ae069`/`0b971a55e`（drill 竞态/打标接线）`e5ec6ebc7`+`4ce647a9e`（门栈+原生成交里程碑）`65d2087d3`（014_1 平仓映射+harness 回归）`175518c89`（选择器语义修正）`3e9d05d92`+`dc595340b`（前选失败细节持久化）；本迭代无 SDK 源码改动需提交 | ✅ 逐轮 |
| 9 | R9 收尾（终版 tracker/记录/报告） | `iteration42-example-tracker.{json,md}` 终版 + 最终提交 | 现为 R6–R8 态快照（`7b68e19be`），周一后重生成。**生成器已于 2026-10-10 以 `--out D:/temp/iter42_tracker_check` 冒烟通过**（两文件正常产出、自动取各例最新 live 证据；committed tracker 未动）；周一后以默认 `--out` 重生成 + 更新 EXAMPLE_STATUS 的 commit/note 字段 | ⏳ 周一后 |

## 唯一未完成项（时窗门）

周一 2026-10-12（北京）六步串行（命令与判据见 `monday-live-run-plan-2026-10-12.md`；
六条命令 argv 预检通过 `41929f556`）：

1. 09:00 013_3 写 drill → 2. 09:55 014_1 写 drill → 3. 10:50 014_2 观察
   → 4. 11:10 015 观察 → 5. 13:35 013_1 写 drill → 6. 21:05 013_2 写 drill。

每步：实跑 → 结果数值/证据哈希并入 r1/r4/r5/r6/r7 记录 → 终版 tracker 再生成 →
R9 收尾提交（AGENTS 段状态更新为 completed）。

## 已记录的翻转路径（外部门）

- 012_1：运营重发资格工件窗口（≥当前日期）→ 刷新 manifest → 复跑（零代码）。
- 012_2：iteration21/30 HFT 准入流程通过 `event_path_models`（本迭代不做 HFT 结论）。
- 014_2/015 决策路径（若未来要求）：生产 `ctp.quote.v2` 证明 + 校准决策边界时钟的
  专用适配轮（本迭代不伪造）。
