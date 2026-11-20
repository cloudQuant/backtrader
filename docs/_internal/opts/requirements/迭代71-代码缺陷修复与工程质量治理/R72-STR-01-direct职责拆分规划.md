# R72-STR-01：direct mode 职责拆分规划

整理日期：2026-11-21
状态：**规划稿；本迭代不物理拆分，不改变代码或合同。**

## 1. 范围与结论

[待办清单](待办清单-TODO.md) 中的 R72-STR-01 指出 `backtrader/brokers/_btapi_direct_mode.py` 同时承担持仓、订单、拆单相关流程与生命周期工作，要求先明确边界和逐步剥离路径。本文件只记录规划，不代表实现、行为验收或真实账户验收。

当前 `BtApiDirectModeMixin` 位于模块约第 575–6358 行，`direct_params()` 在文件末尾。拆分应保留现有 `BtApiBroker` 委托入口和 direct 模式语义；不得借结构调整改变订单、成交、UNKNOWN、权限、持久状态或失败关闭行为。

## 2. 当前调用链与边界

`btapibroker.py` 导入并继承 `BtApiDirectModeMixin`，将 `BtApiBroker.start()`、`stop()`、`getposition()`、下单、撤单和 `next()` 分别路由至 direct mode 的对应方法。R72 规划不涉及改动该选择逻辑。

模块对 SDK facade 的实际调用包括：

- 读取 `direct_account_facts`、`direct_trading_permissions` 和交易时段日历；
- 发送 `make_order` / `cancel_order`；
- 轮询 `poll_direct_execution_events`；
- 处理结算确认，并通过 `direct_writes().provider(...)` 读取账户引用或有限 provider 计数。

模块消费 SDK 提供的归一化 facts/events，并将匹配到本策略的事实映射到 BT 对象。原生报文解析、签名和 provider 协议不应搬入 Backtrader。`live_state` 持有策略目录中的身份、sequence、pending markers、waiting orders 和 position snapshot；direct mode 负责调用其端口并与 Broker 运行态协调。

## 3. 目标职责划分

| 职责 | 当前主要代码 | 目标边界 |
| --- | --- | --- |
| BT 数据投影 | `_direct_symbol`、`_direct_sync_net`、`_direct_getposition`、`_direct_closable`、`_direct_apply_balance`、成交应用、`_direct_restore_order` | 把已经过来源、完整性和身份检查的 typed facts/events 映射到 BT `Order`、`Position`、账户值及通知。投影不负责证明来源或授权，也不能把未知值折成零。将只读投影与会修改 Broker 对象、通知或快照的步骤区分开。 |
| 对账状态机 | `_direct_reconcile`、事件归属和成交重配、return/fill gap、结算确认/读回、交易日切换 | 比较完整观察与本地状态，推进 pending marker 和未决事项，并产生有限报告。状态算法与 SDK 读取、BT 对象应用、线程调度应有明确分界。持久状态仍归 `live_state`，不新建并行账本。 |
| 协议收发适配 | `_direct_read_facts`、`_direct_request`、`_direct_dispatch`、撤单路径、`_direct_drain_events` | 将 BT 请求组装为 SDK 合同、调用 SDK facade，并把 SDK typed 结果交给状态机/投影层。provider 原生协议不属于此层。写入 marker 提交必须先于外部下单/撤单；发送后状态不明时继续保留 UNKNOWN。 |
| 生命周期编排 | `_direct_start`、`_direct_stop`、失败启动清理、facts poller、run lock 和 stop/write fences | 控制 Store 和 poller 启停、启动边界、锁持有、并发停止、停止等待及失败清理。生命周期只调度检查和状态机，不取代它们的判定。 |

还存在两类横切门禁：交易许可/账户观察有效性，以及 Feed/日历资格和等待订单处理。可选的只读 Execution facts 投影也有独立调用链。它们不应被混入“纯投影”，也不应使基础 direct 路径暗中依赖可选 Execution/Risk 组件。

## 4. 渐进剥离顺序

### 第 0 步：冻结基线与依赖图

整理方法调用图、状态字段写入点、`live_state` 端口和 SDK facade 调用点；先确定哪些函数纯读、哪些改 Broker 对象、哪些持久化、哪些可访问 provider。为每项物理提取记录现有输入/输出、顺序和副作用。

### 第 1 步：抽取窄的 BT 投影叶子

先提取不访问 Store、SDK、文件系统、锁或时钟的转换逻辑。Broker 上保留 `_direct_*` 委托方法，避免立即改变内部调用和测试 monkeypatch 点。快照格式和公开报告字段暂不改动。

### 第 2 步：明确协议端口和结果适配

将 request 构造、SDK facade 调用及 typed 结果交接分别命名；每个抽取仍由现有 mixin 控制提交顺序、授权检查和 UNKNOWN 处理。暂不将准备/提交/发送合并到新通用执行器，避免改变故障窗口。

### 第 3 步：逐个抽取状态机

先提取可独立测试的 transition 判定，再一次处理一个状态域：启动恢复、return/fill gap、结算确认、交易日切换。等待订单/日历资格单列评估。保持同一份状态、marker 和报告语义，禁止跨多个状态域一次性搬迁。

### 第 4 步：最后抽取生命周期协调

前三层行为稳定后，再梳理 start/stop/poller 的 owner、锁和停止时序。`_StopFencedPort`、poller 结算写、stop 等待中的 in-flight write 与 run lock 是耦合最高的区域，应保持在同一轮变更中完整验证，不能只测试普通启停。

## 5. 回归验证与风险

每个阶段先运行匹配的 direct 专项，再运行整个 `tests/unit/brokers/direct/`，并跑相关集成用例，例如 direct 无 Gateway 组合、direct 隔离和 direct/Gateway parity。投影变更重点验证多空腿、净仓、今昨仓、可平量、分数成交和恢复订单；协议变更验证 DTO 字段、marker 先提交、一次发送、异常/UNKNOWN 及 poll 上限；对账变更验证重启、重复/乱序回报、ID 跨交易日复用、缺口、结算读回和不完整快照；生命周期变更验证启动失败、重试、stop 幂等性、stop 与 poller 写竞争、资源及 run lock 状态。

保持 `BtApiDirectModeMixin`、`direct_params()` 和 `_direct_*` 委托在原导入路径可用，直到逐项清点调用者和测试后另行批准兼容变化。现有测试直接 monkeypatch 若干 `_direct_*` 方法；`test_direct_snapshot_split_binding.py` 还把 `_direct_write_snapshot` 当未绑定方法调用。这些都是拆分时需保留或显式迁移的约束，不应靠扩大实现范围处理。

主要风险是把“读取事实”误当成“事实完整/新鲜”、把发送异常误判为未发送、移动代码时改变通知或快照顺序、状态机共享可变字段被拆成双份，以及拆分后形成 SDK/BT 循环导入。新模块应依赖窄接口或显式传入的 host/callback，不应顶层导入 `BtApiBroker`。只使用公开源码和合成测试，不读凭据、账户数据或私密捕获；本规划不授权任何真实账户操作。

## 6. 参考

- [仓库目录与文件职责规范](../../../../source/developer-guide/repository-responsibilities_zh.md)
- [交易系统架构与项目职责](../../../../TRADING_SYSTEM_ARCHITECTURE.md)
- [迭代 60 计划](../迭代60-统一行情容器与低转换数据链路/迭代计划.md)
- [R72-STR-01 清单项](待办清单-TODO.md)
