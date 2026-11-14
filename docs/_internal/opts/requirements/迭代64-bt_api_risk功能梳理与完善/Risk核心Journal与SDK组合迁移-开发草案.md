# Risk 核心 Journal 与 SDK 组合迁移：开发草案

**状态：设计草案 / 开发中（2026-11-14）。** 本文是迭代 64 的实现方向，不表示新组合、fence、账户事实或写入能力已经可用。用户已允许破坏式重构和删除旧兼容；本期按开发及对应本地测试统计完成，整体及真实环境验收后置。设计或测试不能删除未决订单、持仓、占用、历史账本和已消费 generation，也不授权处置 retained host 或重跑实际账户操作。计划与当前状态分别见[迭代计划](迭代计划.md)和[开发验收状态矩阵](开发验收状态矩阵.md)。

## 1. 已核对的现状

- Risk 的 [核心 journal](../../../../../../bt_api_py/bt_api/bt_api_risk/src/bt_api_risk/risk_order_journal.py) 拥有账本与 writer fence；本机工作树中的 provisional owner、借用校验及来源隔离仍是未提交 WIP。其 fence 入口和借用身份检查要求 Risk 核心精确类型；`assert_borrowed_fence` 当前也未由 SDK 真实调用链接入。
- SDK 的 [RiskOrderJournal](../../../../../../bt_api_py/bt_api_py/service_risk_order_journal.py) 当前多重继承 SDK `RiskExecutionJournalBridge` 与 Risk 核心 journal。SDK 实例不是核心精确类型；在当前 WIP 的类型门下，不能假设其首次 fence 获取或借用可用。不能用 `isinstance` 或类名相同直接放宽。
- SDK bridge 提供撤单来源绑定、读取与证明构造；SDK 类另提供 provider profile 与 Gateway 仓位来源验证。Risk 核心在证明和历史重验路径动态调用这些能力。直接将 SDK 类改为核心类的别名，会丢失这些组合能力。位置、规则或证明对象存在不等于来源可信或账户授权。
- 同一工作树里，[组单证明](../../../../../../bt_api_py/bt_api_py/service_execution_group_proofs.py)在会话持有原 fence 后还有二次 `writer_fence` 校验；[CTP bridge](../../../../../../bt_api_py/bt_api_py/ctp_risk_dispatch_bridge.py)长期持有同一 journal 的 fence，[撤单 gate](../../../../../../bt_api_py/bt_api_py/service_execution_risk_cancel.py)还有独立获取路径。不能只改组单的两个调用点，就宣称所有重入已替换。
- Risk 服务 host 的核心 journal 与 CTP/执行组合的 SDK journal 是不同装配路径，不能假定已经共享实例或生命周期。工作树中初始化未知、锁进入、sticky cleanup 和 engine/ledger 仍存在未完成 WIP；当前源码及本草案都不是其已闭合的证据。

## 2. 拟采用的所有权与边界

1. **Risk core**：每个已选组合持有一个精确类型的 Risk 核心 journal；它持有账本连接、原始 fence context 和事务，管理同账户的身份、令牌及未知结果。短期使用的入口显式获取并退出自己的 context；长期 owner 持有原 context，只有明确完成关闭且可证明资源处理结果后才结束持有。不可从 scope、路径、名称或字符串匹配自行寻找 fence 并据此授权。
2. **SDK facade 与端口**：SDK 包装器固定引用唯一 core，在可信装配中一次性选择并实例级绑定 Execution 来源桥、provider profile、Gateway position verifier。Risk 不反向导入 SDK；SDK 负责 route 和证据桥的组合。端口在装配后的替换、缺失、类型/身份变化均应使相关路径不可用；通用 callable、可构造的 DTO、`verified=True` 或字段格式一致均不单独建立授权。进程内对象身份和类型也不是防恶意同进程 Python 的沙箱。
3. **原 context 借用**：仅在调用方已经持有并传回原 context 与原 fence 的情况下，按同一 core/journal、owner、进程、线程、scope、token 和 digest 及当前持有关系复核；复核前后检查同一身份和隔离状态。借用只验证当次本地关系，不重新获取或释放、不延长原 context 生命周期，也不证明 provider、账户事实或复核返回后的状态。
4. **来源与事务**：撤单证明应读取已绑定的 Execution store 和对应事件链，并在适用的原 fence/guard 期间验证 route、scope、run、单次派发及身份；provider profile 的选择还需覆盖历史重验。Gateway 仓位来源验证仍须验证原 receipt、账户/会话、完整性和适用覆盖；不得把一次外部校验替换成调用者提交的布尔值。`_execution_journal_authority` 与 `_gross_exposure_authority` 分别审计，不能未经核对将二者视为同一来源。
5. **失败与历史数据**：来源、owner、授权、事务或跨库结果无法证明时，对应路径失败关闭或保持 `UNKNOWN`，按原身份保留占用、意图和原资源；副作用可能已发生时不自动重发、不假称回滚或未发送。保留 v1/v2 和其他旧账本原文件；不能将无法迁移或不完整的旧行当空账，也不能用新进程取代仍可能运行的旧 owner。合法的旧 API 可以按本次决定删除，当前调用者和测试必须同步。

## 3. 实现顺序及本地测试

下列顺序用于拆分可实现的开发工作；前后步骤的 fake 测试只证明所覆盖的本地行为，不替代真实来源。不得因某个独立片段通过而打开缺少其余合同的写路径。

| 步骤 | 开发工作与依赖 | 对应本地检查 |
| --- | --- | --- |
| 1 | **只读投影前移：本地完成**。`strategy_ledger_journal_identity`、`strategy_ledger_events_after`、`has_intent_id` 已从 SDK journal 移入 Risk core，SDK 现有调用使用该能力；不改写/接管账本。已本地提交 Risk `139e975` / SDK `bb28c892`。这不表示 core/facade 组合或 fence 已完成。 | 独立源码快照的 fake 定向测试由主线程复跑：Risk **23 passed**、SDK **1 passed**；覆盖范围以相应测试为准，不证明真实来源或账本权限。 |
| 2 | 固定 core、facade、原 manager/fence 与三个来源端口的实例级合同；缺失能力的具体写操作保持不可用。借用、长持锁和短持锁为不同路径，不靠再次获取同一账户 fence 证明身份。 | 纯 fake 覆盖同一实例、第二 core、同路径不同对象、错 scope/线程/代际、原 context 退出和端口变化；不以 fake 证明真实锁。 |
| 3 | 把 Execution 撤单来源、provider profile 和 Gateway 仓位来源验证由继承钩子迁为实例绑定端口；同步原有 gate 的来源与历史重验。 | 假来源/错 store、scope、run、profile、receipt 或记录链必须拒绝；回调异常、事务中失效及不确定提交保持 `UNKNOWN`。 |
| 4 | 成组切换 SDK 装配、Gate authority、Risk entry、CTP bridge/cancel、Group 和 strategy-ledger host 的同一 core/facade 关系。CTP cancel 只能借用明确绑定的原 bridge/context/fence；首次获取、最终退出及没有持有凭证的独立路径仍各自获取。 | 同一 authority 正反例、CTP/Group 持有期与跨代、回调重入/关闭竞态、未决占用及不重发；本地替身仅证明对应模拟路径。 |
| 5 | 对旧 schema、旧写者及未决/在途/UNKNOWN 数据设计并实现可证明的读取、隔离和恢复路径；无法证明安全的情况明确拒绝，不以重建空库处理。 | 合成历史行、冲突身份、旧 writer/owner、进入和退出不确定的故障注入；保留原行与资源，检查不可误发或自动释放。 |

## 4. 当前独立欠项

- 账户快照与回报流共同切点、交易日/最新成交价/FX 的可信来源、母子单授权及跨代未发送证明仍为开发缺口；本次对象组合不填补这些事实。
- Risk 与 Gateway 独立持久化，政策/permit 最新性检查至 Gateway 派发仍存在跨进程非原子窗口；需要共同序列化、owner 与 UNKNOWN 合同，不能靠额外本地比较、类型或 token 名称宣称原子。
- provisional fence 入口的外层交付、原 OS 锁真值、初始化/关闭与其他 owner 的竞态，以及 retained host 的生命周期尚未闭合。共享 runtime 和 journal 工作树有其他未提交修改，实施时按实际 hunks 和各仓职责协调，避免覆盖或整体暂存不相关修改。
- 允许破坏旧版行为不等于重放历史实际调用或清理不确定资源；本草案不授予额外账户操作，也不将本地 UNIT/FAKE 解释为生产能力。
