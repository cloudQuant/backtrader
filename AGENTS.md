# AGENTS.md

## 先读：职责、现状与证据

分析、审查、提出迁移建议或修改本仓库前，先读取
[仓库目录与文件职责规范](docs/source/developer-guide/repository-responsibilities_zh.md)。
涉及跨仓库交易接入时，还需读取
[交易系统架构与项目职责](docs/TRADING_SYSTEM_ARCHITECTURE.md)、
[bt_api_py 的 SDK 家族职责表](D:/bt_api_py/README.md)和
[迭代 53 计划](docs/_internal/opts/requirements/迭代53-实盘直连与Store职责重构/迭代计划.md)。
跨仓工作使用各自现有 checkout，并读取目标仓适用的 AGENTS.md 与 README。

按需要查阅[逐文件职责盘点索引](docs/source/developer-guide/文件职责盘点-2026-11-01/index.md)；
其中交易接入与服务、数据与分析组件分别覆盖 BtApiStore/BtApiBroker 与 BtApiFeed。
盘点是带日期的静态快照，分析前应核对当前源码、调用者、未提交改动与包构建配置。
回答须区分既定职责、当前实现、目标设计、未验收内容和本次建议；不能将路径存在、源码审查或 fake 测试当成账户能力已通过。文档不一致时标出来源和状态，遵循用户当前指令，不擅自裁定事实。

本文件精简前的完整工作区原文（包含历史进度、未提交的用户修改及运行限制）已按原字节保存在
[AGENTS 历史快照](docs/_internal/opts/requirements/迭代53-实盘直连与Store职责重构/AGENTS-历史快照-2026-11-01.md)。
它是历史记录，不整体覆盖当前指令；涉及其历史流程、受保留 host、已消费调用或证据时必须先阅读相关段落并遵守仍适用的限制。

## 跨项目职责

以下为约定/目标边界；目标本身不证明相应能力已实现或验收：

- **Backtrader**：策略与 Cerebro 生命周期、Store/Feed/Broker 框架接口、BT Order/Position/Trade、bar 聚合与数据线、回调和通知，以及中立数据到框架对象的投影。
- **bt_api_py**：统一 BtApi facade、provider 发现与选择、跨包组合、route 与会话调用及中立 SDK 工作流。Backtrader 经此接口集成，不按交易所建立专属 BT adapter。
- **启动 journal 恢复**：`bt_api_py.startup_recovery` 负责 SDK 恢复 hook 的次序和结果合同；Store 保留触发时机及失败转译。缺失 hook 为 unsupported，并不证明订单状态干净；当前跨仓接线仅为源码 WIP。
- **审批 lease 字段检查**：`bt_api_py.approval_lease` 校验传入字段，Store 做 BT command 映射与拒绝转译；它不签发授权或证明来源。当前跨仓接线仅为源码 WIP。
- **bt_api_base**：共享中立 DTO、协议、接口和基础组件；合同本身不证明账户、provider 或授权事实。
- **bt_api_ctp / bt_api_okx / bt_api_binance 等 provider**：各自交易所的 native/session、鉴权、字段、请求、查询、回报、原生规则及向中立合同的转换。
- **bt_api_execution**：显式启用的可靠执行、journal、派发、对账与恢复；聚合、拆单和算法调度是目标能力，不能假称已实现。
- **bt_api_risk**：显式启用的业务风险政策、准入、额度与风险计算；选择后故障 fail-closed。
- **bt_api_gateway**：可选的账户范围命令与读取路由、共享会话/读模型合同；按 SDK README 区分服务装配和 transport，不假定本包自行提供 provider client、凭据加载或 socket server。
- **bt_api_monitor**：可选监控、事件、指标和告警；观察不自动证明账户或订单真值，也不授予写权限。
- **bt_api_runtime / bt_api_transport_zmq**：分别承担可选 SDK 服务装配和传输职责；两者不应成为默认 direct 的隐式前置，也不拥有交易所事实。
- 本地直接交易仍须执行基础身份、协议、会话、请求与回报关联、安全及 UNKNOWN 处理；未选择可选组件时不能强制依赖它们。选中组件失败不得静默回退。

## Backtrader 主要模块

- `store.py` / `stores/`：Store 公共接口、实例级生命周期、route 和 Feed/Broker 协调；不拥有 provider 原生协议真值。当前 Store 非强制单例，行为以源码和验收为准。
- `brokers/`、`broker.py`、`order.py`、`position.py`、`trade.py`、`commissions/`：BT 订单、成交、持仓、费用投影与通知；provider 原始账户/订单事实经 SDK 提供。
- `feeds/`、`feed.py`、`filters/`、`resamplerfilter.py`：Feed 生命周期、BT 数据线、数据时钟、过滤与 bar 聚合；不伪造来源时钟或交易授权。
- `execution/`、`factor_execution/`、`service/`：当前迭代的 BT 执行适配、策略/因子事实和框架生命周期桥接候选；durable journal、provider authority 与通用服务能力归相应 SDK owner，逐函数确认，当前工作树仍有未验收迁移。
- `cerebro.py` / `_cerebro/`、`strategy.py`、`line*.py`：引擎唯一调度、策略回调、线运算与多数据时钟；不新增第二套策略调度器。
- `research/`、`indicators/`、`observers/`、`analyzers/`、`sizers/`：各自的研究、指标、观察、分析和仓位计算；不私自创建账户事实或绕过执行/风控边界。
- `tests/` 是验证，`examples/` 展示使用，`scripts/` / `tools/` 为任务入口，`docs/` 解释和记录；产品代码不依赖这些目录作为运行时实现。

## 持久开发流程

- Backtrader、`D:/bt_api_py` 和各 SDK 子仓在各自现有 `dev` checkout 开发，用户未要求时不新建 worktree；不直接推送 master 或 development。
- 小轮推进：实现、完成本轮约定的检查、仅暂存接受的文件或 hunks、提交相应 dev、记录范围/结果/仓库/分支/commit；SDK 子包先提交，再更新父仓 gitlink。保留所有无关 dirty 修改与用户文件。
- 检查历史工作区中与目标相关的已验证工作；不要因成果留在其他 checkout 重复开发。验收失败继续修复，明确源码、fake、安装包及真实账户证据级别。
- 同一适用策略跨 backtest、replay、shadow、paper、live 复用是架构目标，不表示当前模式全部可用；切换依配置与相应 Feed/Broker/Store，模式名不授予写权限。
- 迭代 53 当前计划为先完成已授权的结构重构，再在 S3 冻结后集中测试与修复；此顺序服从用户后续明确指令。目标的暂停/恢复状态以会话当前状态为准。

## 私密输入与历史限制

真实忽略的 `.env`、`config.yaml`、凭据和私密捕获不属于源码审查材料。子代理和普通审查只用公开源码、模板、测试及脱敏公开快照；授权账户读取须使用受保护的有界 reader，仅输出有限类别或布尔值，不输出值、原始行或凭据哈希。
不修改冻结证据、清空已消费 generation、重跑已接受实际调用或未经授权的账户操作。保留相关 retained host 与源/结果身份；不得自行退出、kill 或手动释放。具体限制和结果见历史快照及相关迭代证据；遇到不确定状态不得假设已关闭或批准重试。

## 子代理

用户允许委派时，优先使用 `model="gpt-6.1-terra"`、
`reasoning_effort="xhigh"`、`fork_turns="none"`，并在任务中提供明确上下文、适用职责资料与写入范围；用户另有指示时从其指示。迭代 53 遵守用户设定的子代理数量上限。主代理模型不因该偏好改变。

## 开发与验证

- Python 以源码和 `setup.py` / `pyproject.toml` 为准；当前核心构造使用 mixin/显式 factory，不重新引入 metaclass。
- 相关命令：`make test-fast`、`make test-slow`、`make test-strategies`、`make test-all`、`make test-performance`；针对变更选择必要验证。指标注册、多 Feed 时钟或 minperiod 的变更需特别覆盖策略回归。
- `make format-check`、`make lint`、`make type-check` 可用于相应质量检查；不以测试数量代替实际合同覆盖，也不重复已接受的历史 QA。
- 新建或更新中文 Markdown 默认 UTF-8 BOM，尊重冻结证据和既有格式例外；严格 UTF-8 解码、确认无替换符，并用 Windows PowerShell 5.1 默认读取确认中文可读。
