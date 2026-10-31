# 迭代 53：RegisteredSim provider callback UNKNOWN 写阻断轮次记录

- 日期：2026-10-31
- 仓库：`D:\source_code\backtrader`
- 分支：`dev`
- Backtrader 基线：`3f0dee2ccad239844e34859d99ec8b85c86a88ca`
- 代码范围：`backtrader/stores/registered_sim.py`
- 当前源码 SHA-256：`dc64886dfda48be96263fed645d3af797b087d0bfcce471524ce0fa5e200be5f`
- 交付状态：源码与本轮记录尚未提交；保留工作区其他改动。

## 本轮处理

`RegisteredSimWrapper._handle_order()` 将 provider 回调中的 CTP 状态码 `a`、缺失或空状态、未识别的未来状态码以及状态提取/识别异常记录到独立的 callback-UNKNOWN latch。该 latch 与 native dispatch UNKNOWN 分开保存；不会把 callback `a` 写成 `terminal`，也不会把它降格为 `active`。已知状态 `0–5`、`b`、`c` 继续沿用原有的状态处理。

latch 按 wrapper 实例生命周期保留最多 1,024 个订单引用，不逐出未解决订单。超过上限时设置 sticky overflow。缺失 OrderRef 或身份不完整会单独标记，并使订单 ID 投影不可完整读取。只有 session filter 成功读取到明确、有效且不匹配的正 FrontID/SessionID，才将回调认定为 foreign 并跳过；无法读取、身份缺失或过滤异常时保守地记录未解决项。latch 不因后续 callback 自动清除。

`_require_armable_locked()`、native submit/cancel 入口和共享 callback/dispatch admission 的 observation lock 检查会拒绝新的 arm 或 native dispatch。Store 的 submit/cancel/cancel_order_ref 写入口也在边界上 fail closed。健康状态、执行 facts 与 query summary 投影 callback-UNKNOWN 的 ID/count/incomplete/overflow 状态，并把未解决或未观测状态显示为阻断原因。

共享 observation lock 将 latch 发布和 native dispatch 最终 admission 排序：若未知回调先发布，后续 dispatch 会被拒绝；若 dispatch 已通过最终 admission，后来抵达的回调不撤回该次已开始的调用，但 latch 保留并阻止下一次写入。这不是对在途 API 调用的回滚机制。

## 源码锚点

以下行号对应上方 SHA-256 锁定的当前 `registered_sim.py`：

- 初始化、有界 latch、sticky 投影和 facts：`1214`、`1232–1236`、`2045–2123`。
- arm 检查及 native dispatch 最终 admission：`1401–1408`、`2241–2310`。
- callback 身份过滤、异常 fail-closed 和状态分流：`2409–2499`。
- Store 写入口检查：`3682–3697`、`5137–5165`、`5336–5338`。
- health、execution summary 与 query summary 投影：`4111–4215`、`5102–5126`。
## 验证

- `python -m py_compile backtrader/stores/registered_sim.py`：通过。
- `git diff --check -- backtrader/stores/registered_sim.py`：通过。
- 一次性纯 fake 探针：SDK 假方法在同步重入时投递 `OrderStatus='a'` 后返回 `0`；即使返回路径随后更新普通订单投影为 active，独立 latch 仍保持未解决，后续 native 写、arm 和 Store 写边界均拒绝，health/summary 显示阻断。
- 一次性纯 fake 探针：缺失/空状态、未来状态码、缺失 OrderRef 均形成 latch；已知 `0–5`、`b`、`c` 的既有 active/terminal 投影保持不变，后续 active callback 不清除 latch；达到有界上限后 overflow 保持阻断。
- 一次性纯 fake 探针：`Mapping.get`、属性 descriptor、`str()`/字段提取和 session filter 读取异常导致 identity-incomplete latch；只有身份字段成功读取且明确显示 foreign 的回调被过滤。
- 本轮没有增加持久测试文件，也没有运行账户、provider 或 SDK 调用；这些 fake 结果只证明 Backtrader 本地分支行为。

## 配套工作与限制

- `bt_api_ctp/status.py` 对原始 CTP 状态 `a` 的 SDK `Unknown` 映射及对应 SDK 测试属于配套工作，未由本轮修改或验收。需要与本分支结果共同验证状态合同。
- Broker 的 normalized order event/status 路径仍走既有父类处理。本轮仅增加 RegisteredSim 回调层的独立未解决标记与写阻断；没有证明 Broker `Order` 状态已修复或 UNKNOWN 已被完整保留。
- latch 仅在当前 `RegisteredSimWrapper` 实例内存中存在。新建/替换 wrapper 或进程重启会重新初始化；没有持久化、受信查询解析、人工恢复或安全解冻协议。完整恢复语义仍待设计和验收。
- fake 与源码检查不证明真实 SDK 回调线程、账户状态、provider 行为、完整 Broker 状态或 paper/live 接受结果。SDK 配套、Broker 状态传播和恢复协议完成前，不应把此轮描述为端到端 UNKNOWN 状态修复。

## 复审结论

**GO：** 仅限 Backtrader RegisteredSim 回调 UNKNOWN latch 对新 arm、新 submit/cancel dispatch 及 Store 写入口的进程内 fail-closed 阻断；异常身份读取与同步重入场景由纯 fake 探针覆盖。

**HOLD：** SDK 状态表配套、Broker 状态传播、跨 wrapper/进程持久恢复，以及任何真实账户或 provider 验收。