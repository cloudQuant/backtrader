# 迭代 53：CTP 直连 native 返回值 UNKNOWN 保护轮次记录

- 日期：2026-10-31
- 仓库：D:\source_code\backtrader
- 分支：dev
- 源码基线：b49938cb3f7aa40da6e0d2629a58584a00fd9547
- 本次检查工作区 HEAD：3f0dee2ccad239844e34859d99ec8b85c86a88ca
- 基线后源码路径沿袭：b49938cb3 到 3f0dee2cc 之间只有文档与脚本归档提交；核对的路径为两个迭代 53 文档和 scripts/verify_factor_research_installed.py、tests/unit/scripts/test_verify_factor_research_installed_archive.py，未改动本轮源码文件。
- 本轮代码范围：backtrader/stores/btapistore.py
- 当前源码 SHA-256：6e7cbbb658e99ddf7b58905d119e4fc73b9c400b1e8c4187cb0c56ba801b952c
- 交付状态：代码与本记录尚未提交；不包含其他工作区改动。

## 背景与处理

stock CTP wrapper 的 submit_order 与 cancel_order 原先使用 ret != 0 判断 native 返回值。Python 中 False == 0 且 0.0 == 0，因此错误类型的 False/0.0 会被当作同步成功，随后 submit 返回带身份的普通响应，cancel 也返回普通响应。Store/Broker 因而可能把未确认结果投影为已接受；非等待远端确认的直连 cancel 还可能把本地订单直接置为 Canceled。

本轮仅修改 Backtrader stock CTP wrapper 的 native 返回值校验：

- 新增内部异常 _CtpNativeResultTypeUnknown，携带 execution_unknown=True 和操作级稳定错误码；错误消息不包含原始返回对象的 repr。
- submit 和 cancel 均只把 exact int 类型的 0 当作 native 同步 ACK。bool、float、整数子类以及其他非 exact-int 返回值都抛出 UNKNOWN 异常，不返回普通成功响应。
- exact int 非零仍保留原来的 BtApiStoreError 路径，没有改成 UNKNOWN，也没有新增自动重试。
- 此改动没有改变 Store/Broker 的异常处理策略，也没有添加新的恢复、重试或账户查询流程。

Store 的 legacy submit/cancel 边界识别 execution_unknown 异常并投影为 unconfirmed。Broker submit 对该异常调用既有的 _accept_unknown_submission：订单保持非终态且 alive，设置 execution_unknown=True 并保留在 Broker orders 中，不走 reject/fill 分支。Broker cancel 对该异常保留原订单为 alive，标记 cancel_requested_remote、cancel_execution_unknown 与 execution_unknown，不在直连路径本地取消，也不盲目重发。stock wrapper 在收到非 exact-int 结果时不会向 _pending_orders 写入普通成功记录；Provider 是否已经处理请求仍然未知，应通过独立的只读对账流程处理。

## 源码锚点

行号对应本记录所列当前源码 SHA-256：

- 内部 UNKNOWN 异常：backtrader/stores/btapistore.py:411–424
- stock CTP submit 返回值校验：backtrader/stores/btapistore.py:3052–3056
- stock CTP cancel 返回值校验：backtrader/stores/btapistore.py:3181–3185
- Store submit/cancel 将 execution_unknown 映射为 unconfirmed：backtrader/stores/btapistore.py:9199–9202、9562–9565
- Broker submit 保留 UNKNOWN 订单：backtrader/brokers/btapibroker.py:3987–3995、4615–4632
- Broker cancel 保留 UNKNOWN 订单：backtrader/brokers/btapibroker.py:4405–4418

## 验证

- git diff --check -- backtrader/stores/btapistore.py：通过。
- 一次性内存 fake 探针实际经过 stock CTP wrapper、BtApiStore 及 BtApiBroker submit/cancel 分支。native insert fake 返回 False，Broker 没有 reject 该订单，而是将订单保留为 alive/非终态并标记 execution_unknown=True；native cancel fake 返回 0.0，Broker 保留订单为 alive 并标记 cancel_execution_unknown=True。两次 native fake 调用各一次，无自动重发；异常返回没有在 wrapper 中写入成功的 _pending_orders 记录。
- 另一个一次性内存探针确认 exact int 0 的 submit 和 cancel 仍能得到原成功路径；float 0.0 submit 与 bool False cancel 被投影为 UNKNOWN。exact int 非零 submit 仍产生原普通 BtApiStoreError，而非 execution_unknown。
- 探针使用本地生成的 stock wrapper 和 Store；Broker 使用保留真实 submit/cancel 方法的临时 ProbeBroker 子类，stub 了与该返回值分支无关的本地风控和准备步骤。当前本机安装的 bt_api_ctp 缺少 public fields 模块，因此探针仅在进程内替换最小方向/开平字段 map；没有修改 SDK 或写入持久测试。
- 没有连接 CTP SDK client，没有调用账户、provider、网络、行情或真实 native 写入口。没有运行持久测试套件或真实账户验收。

## 未覆盖问题

native typed 方法抛出的 raw exception 与“方法正常返回但值类型错误”是不同路径。本轮没有改变异常分类。Store 目前只将 TimeoutError 或显式带 execution_unknown=True 的异常记为 unconfirmed；其他 raw exception 在 legacy direct Store 路径仍会作为 reject 处理。若 SDK 在 native 调用后以未标记异常退出，这种现有分类可能无法表达未知交接结果，需要后续独立审查和修复；本轮不声称覆盖该场景。

本轮证据仅支持 Backtrader 本地 fake 下，非 exact-int native 返回值不会被误作成功，并由现有 Broker 路径保留为 UNKNOWN。它不证明 SDK 实际返回类型、Provider 是否收到请求、账户状态或 paper/live 接受结果。

## 复审结论

独立窄范围 review 为 GO，限于 stock CTP wrapper 非 exact-int native 返回值 fail-closed、exact-int 非零沿用旧行为、Broker UNKNOWN 保留及不自动重发。raw native exception 的分类仍是待修问题。