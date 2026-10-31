# 迭代 53：CTP 直连 typed 调用异常 UNKNOWN 保护轮次记录

- 日期：2026-10-31
- 仓库：D:\source_code\backtrader
- 分支：dev
- 源码基线与当前 HEAD：a9990c3e86bf8a3c3a392f92814cd8c2825d5f93
- 本轮源码范围：backtrader/stores/btapistore.py
- 当前源码 SHA-256：1b6226a658c5cfa2eb353cf7281f52f0e4498e23ed4389815632eb659b0d60a9
- 交付状态：源码和本轮记录尚未提交；其他工作区改动保持不动。

## 本轮处理

stock CTP wrapper 的调用前能力检查与 typed 方法存在性检查仍在 typed 调用边界之外。缺少执行能力或 typed insert/action 方法时，wrapper 保持原有本地拒绝路径，不会进入 native 调用，也不会被改成 UNKNOWN。

进入 typed SDK insert/action 方法后，本 Store 尚未绑定足以证明 pre-dispatch 的逐请求证据。因此，未明确携带 execution_unknown 标记的调用异常会转换为操作级、通用文本的 UNKNOWN 异常，不复制原始异常消息。异常对象若已经携带 execution_unknown，则原样重抛，以保留原对象和已有错误码。此路径不根据 CtpExecutionGateError 的类名作 definite-reject 判定。

Store 现有 submit/cancel 异常处理会将该 UNKNOWN 投影为 unconfirmed。Broker submit 将订单保留在订单表中，状态保持非终态且 alive，并记录 execution_unknown=True；Broker cancel 保留原订单 alive 并记录 cancel_execution_unknown=True，不在直连路径本地取消或盲目重发。

上一轮已接受的 native 返回值检查保持不变：只有 exact int 的 0 是同步 ACK；exact int 非零继续使用既有 BtApiStoreError 路径；其他返回类型仍按 UNKNOWN 处理。

## 源码锚点

行号对应上方 SHA-256 锁定的源码：

- 新增 typed 调用 UNKNOWN 异常及调用边界：backtrader/stores/btapistore.py:427–463、1767–1805。
- Store submit/cancel 识别 execution_unknown 并投影 unconfirmed：backtrader/stores/btapistore.py:9247–9266、9610–9628。
- Broker submit 保留 UNKNOWN 订单：backtrader/brokers/btapibroker.py:3987–3995、4615–4632。
- Broker cancel 保留 UNKNOWN 订单：backtrader/brokers/btapibroker.py:4405–4418。

## 验证

- python -m py_compile backtrader/stores/btapistore.py：通过。
- git diff --check -- backtrader/stores/btapistore.py：通过。
- 一次性内存 fake 探针实际经过 stock wrapper、BtApiStore 及 BtApiBroker 的 submit/cancel 分支。fake typed insert/action 各调用一次并抛出未带 execution_unknown 的异常；异常类名使用 CtpExecutionGateError。Store/Broker 将其保留为 UNKNOWN，submit 与 cancel 的订单均保持 alive；每个操作只调用一次，没有自动重发，原始 fake 异常消息未进入 Broker 错误投影。
- 同一探针确认缺少执行能力或 typed 方法时，仍在调用前以普通拒绝结束，typed fake 调用数不增加；显式带 execution_unknown 的原异常对象、标记和错误码保持不变。
- 探针使用临时 ProbeBroker 子类执行真实 BtApiBroker.submit/cancel 方法，仅 stub 与该异常分支无关的本地预交易检查。当前本机安装的 bt_api_ctp 缺少 public fields 模块；探针只在进程内替换最小字段 map，未改 SDK，也未新增持久测试文件。
- 没有调用真实 SDK native 写入口、账户、Provider、网络或行情；没有真实账户验收。

## 限制与后续工作

现有 SDK 提供逐请求调用记录，但本 Store 的 stock 直连写路径尚未绑定足以证明 native call 未开始的逐请求证据。因此，实际属于 pre-dispatch 的 gate rejection 若从 typed 方法内部抛出，也会被保守投影为 UNKNOWN。这可能降低可用性并要求只读对账；本轮不会据此重试。

后续如需区分 definite pre-dispatch reject 与不确定交接，应独立完成 typed 方法来源、request ID 与权威逐请求 dispatch 记录的绑定；只有可验证的 native_call_started=False 证据才可保留 definite-reject 分类，缺失或不匹配证据仍须 UNKNOWN。本轮没有实现该证据绑定。

本轮 fake 只验证 Backtrader 代码分支和 Broker 的保留行为，不证明真实 SDK 调用结果、Provider 是否收到请求、账户状态或 paper/live 接受结果。

## 复审结论

行为复审为 GO，范围仅限 stock typed insert/action 调用异常的 UNKNOWN fail-closed、显式 UNKNOWN 原异常保留、调用前缺能力/缺方法仍拒绝，以及 Broker 不误拒、不自动重发。逐请求 pre-dispatch 证据绑定和真实账户验收仍未完成。