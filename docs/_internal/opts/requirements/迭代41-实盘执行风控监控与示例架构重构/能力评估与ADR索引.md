# 能力评估与 ADR 索引

版本：`baseline-2 / 2026-09-22`。状态：`DECISION_RECORDED / PARTIAL_LOCAL_VERIFIED / LIVE_NO_GO`。
本次结论来自本地代码阅读与 Git 身份核对，不冒充对应维护者签收或未来实现的验收。
各实现 PR 按本索引复核，改变决策需同时更新 FR/WP/AC 和[审阅裁决记录](审阅裁决记录.md)。

表中的 pin/package 结论是 `baseline-2` 历史核查；当前工作树已有 config-first、risk dispatch claim、
reconcile control、gateway、cancel 与 AI evidence 的局部源码/测试。AI 三仓当前有
`SOURCE_BASELINE_ONLY` source inventory 和 `LOCAL_WHEEL_REVIEW_INTEROP_PASS / review_only` 的 supplied-wheel
向量，但三个 checkout 均 dirty；它们仍缺可归责发布、trusted import origin、部署身份/授权与外部证据。
准确边界以[实施状态与验收快照](实施状态与验收快照.md)和[AI 证据索引](evidence/README.md#ai-三仓-source-checkoutwheel-与配置证据)为准。

## 1. 可复现源码基线

仓库身份由 remote、逻辑 submodule path、commit/pin 确定；本机目录仅供本次重现。
完整机器记录见 [plan-review-baseline.json](evidence/plan-review-baseline.json)。

| 对象 | 本机 checkout / 逻辑路径 | 本次 SHA | 核查结果 |
| --- | --- | --- | --- |
| cloudQuant/backtrader | `D:/source_code/backtrader` | `ad2c142b9a8b42cede85886528c681abdfcb8096` | dev；存在用户尚未提交的 README/审阅文件，本次保留 |
| cloudQuant/bt_api_py | `D:/bt_api_py` | `d3674e19a11b9f35f19ae756899bcf18854c8c46` | 本次 SDK 权威 checkout；`D:/source_code/bt_api_py` 是另一旧 checkout，不能混用 |
| bt_api_base | `bt_api/bt_api_base` | `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f` | 既有 shared/base 包，新增无 I/O schema surface 在此归属 |
| bt_api_execution | `bt_api/bt_api_execution` | `2700cb5454ef4c3d1780eda28b6f33307a860998` | `baseline-2` 时已挂载、未实现/未打包、installable=false；当前 local source 未 pin |
| bt_api_risk | `bt_api/bt_api_risk` | `d0c18a9d503a6792b582d0927244ceb55395032b` | 已有分析、limits/policy 和 ML；不能直接作为已验收 hard gate |
| bt_api_monitor | `bt_api/bt_api_monitor` | `d515a8209324d56742c095d70976593bb3ba3eff` | 已有 metrics/health/exporter；耐久控制面待实施 |
| bt_api_gateway | `bt_api/bt_api_gateway` | `44fd2fe26b51f1d8b573c84415a6cff660f33dea` | `baseline-2` 时 ATTACHED / NOT_PACKAGED、仅 README；当前 local source 仍缺安装门、wheel/consumer |
| bt_api_transport_zmq | 拟 `bt_api/bt_api_transport_zmq` | 无 | `baseline-2` 时 NOT_CREATED / NOT_PACKAGED；当前 local source 仍不能伪造 pin |
| backtrader-agent | `D:/source_code/backtrader-agent` | `90aabcf0bbd2fd06fcc114713c21fc0aac9ad88b` | 独立产品仓；`working_tree_dirty=true`，仅有本地 source baseline 与 review-evidence 测试；其发布/部署产物仍需独立契约和制品核验 |
| backtrader-skills | `D:/source_code/backtrader-skills` | `de68788439444cba2ec764e722db1818e455376a` | 独立产品仓；`working_tree_dirty=true`，本地 PEP 621 metadata 修复及 manifest/wheel 验证不构成发布；不得成为交易热路径、账户授权或配置覆盖来源 |
| backtrader-mcp | `D:/source_code/backtrader-mcp` | `ad6312a11c2fe7ff9a4c3fcfcfab5037a951b58c` | 独立产品仓；`working_tree_dirty=true`，仅有本地 source/review 互操作；只可经受限、可审计的契约互操作 |

旧计划 risk `b6c98e9...`、monitor `48fa8d2...`、gateway NOT_ATTACHED 属于历史快照，
已被上述基线取代。Git pin 只证明来源，不证明安装、语义或真实交易能力。三个 AI checkout 是用户明确的
权威本机位置；其本轮 commit、dirty manifest 与 source hash 见[AI source inventory](evidence/ai-producer-source-inventory.json)。
它们的 release wheel、契约版本、import origin 与部署授权仍须在 AC41-81 独立复核。

## 2. ADR-41-09：TradeLogger 与独立 monitor

问题：能否直接用 TradeLogger 满足初始需求 3，避免维护独立监控？

| 维度 | 已核查 TradeLogger | 现有 bt_api_monitor | Iter41 所需增量 |
| --- | --- | --- | --- |
| 订单/成交/仓位报告 | `backtrader/observers/trade_logger.py::notify_order/notify_trade/next` 已有；`_report_monitoring_snapshot` 读取内存计数 | metrics/collector 可复用 | 用统一 execution correlation 关联，保留框架局部展示 |
| 次数/重复单阈值 | `_track_request_monitoring/_monitor_threshold` 递增计数并输出 warning/event | 可记录指标 | risk 在真实写前拒绝，监控不以“已经报警”替代风险 veto |
| 生命周期 | Observer 跟随策略进程；`stop()` 才产出结束信息 | `collector._collection_loop`、`exchange_health._monitoring_loop` 为进程内 asyncio task | 部署为独立观察进程/服务并验收进程强杀，不将 async task 等同独立进程 |
| 历史与恢复 | `_monitoring` 是 Counter，报告注释明确 in-memory；文件/MySQL 日志不含控制事务协议 | collector history list、health deque 有界但非 durable cursor | durable checkpoint、重复消费幂等、数据缺口标识 |
| 失活控制 | 无进程外执行能力 | 当前未形成耐久授权 command/ack 协议 | 授权 freeze/drain 请求；只允许登记 executor 执行，无接管主体时告警人工处理 |
| 权威账户事实 | 缓存报告/调用者提供的 startup observation；不主动查询 provider | 分析/健康读模型 | provider observation + execution/risk read model，各字段带来源/as-of/completeness |

**决定：** 保留 TradeLogger 为观察者及人类报告出口，通过 bridge 消费脱敏事实；独立 monitor
负责健康、耐久消费、告警和受限控制请求，risk/execution 负责真正的 veto/执行。现有 monitor 也不能
未经 WP41-D 就宣称可独立兜底。关闭 logger、通知失败和 monitor exporter 失败均不改变订单事实。

替代方案“给 TradeLogger 加两个字段”无法解决进程死亡和耐久 command；“删除 TradeLogger”会损害
既有 API 与框架观测，收益不足。选择职责分离，但复用报告/事件格式以免重复采集。

验证：AC41-16～20、47、51、53、62；保留 `tests/unit/observers/test_trade_logger_monitoring.py`
及 `tests/integration/test_trade_logger_report.py` 的相关合同，新增强杀、断线、checkpoint/command
重放用例。不是只测 `stop()`，更不能将检测到失活记成撤单完成。

## 3. ADR-41-10：现有 execution 与聚合层次

问题：已有代码是否足够，新 execution 包应复用什么，订单聚合在哪一层实现？

| 实际代码 / 符号 | 已存在能力 | 迁移裁决 |
| --- | --- | --- |
| SDK `bt_api_py/bt_api.py::configure_execution` | 在公开 BtApi façade 中构造私有 `_ExecutionSession` | 保留业务 façade 和既有入参兼容；新 managed 路径只通过显式安装的 execution integration port |
| SDK `bt_api_py/_execution_session.py::_ExecutionSession` | JSONL、lease/registry/fence、intent、CTP approval/budget、unknown/recovery；不是独立 execution 分发包 | 逐职责迁移公开 contracts/状态机，先建立 golden trace/fault vectors；不整文件复制、不同时开启两账本 |
| 同文件 `migrate_execution_journal` 及 SDK `__init__.py` 导出 | 有迁移及围栏切换基础 | 保持公共 migration API，做格式版本/单 writer 切换/中断恢复，B8 清理私有调用或登记限期兼容 shim |
| Backtrader `backtrader/brokers/btapibroker.py::submit/cancel/next` | framework order 映射、异步回执投影、仓位/现金缓存 | 只做 framework intent/拒绝/allocation 投影，不新建账户订单真相 |
| 同文件 `stop`、close_today/close_yesterday 与 option metadata 校验 | 进程内退出清理，offset/期权费率/乘数校验已有 | 保留严格边界并提升到 typed contract，不以通用 drain 绕过 stale quote、read-only 或期权元数据缺失拒绝 |
| `backtrader/sizer.py::getsizing`、Broker `getcash/getvalue` | 当前 sizer 读取账户 cash，未按策略预算隔离 | 保持旧含义，新增 StrategyAllocation-aware sizer，不悄悄改变 getcash 返回值 |
| SDK forwarding 的 SQLiteStateStore（由架构审阅定位） | 传输 ack/private-event 恢复状态 | 可保留传输收据/游标；不能变成 managed 第二 OMS 或在 unknown 时自行重新 dispatch |

| 聚合放置方案 | 收益 | 问题 | 选择 |
| --- | --- | --- | --- |
| 策略/examples | 接入快 | 跨策略未知、重复账本、恢复/额度无全局一致性 | 不采用 |
| Backtrader Broker | 容易关联 order.ref | 框架耦合，SDK 其他调用者无法复用，承担第二账户真相 | 只保留薄投影 |
| provider adapter | 熟悉交易所字段 | 跨 provider 语义和账户策略预算混杂，误把 batch 当原子 | 仅提供 capability 与协议映射 |
| bt_api_execution | 可按账户归因、统一 plan/child/partial/allocation/recovery | 需独立包发布、兼容迁移、持久化成本验收 | 采用，由 SDK 组装 |

**决定：** execution 是 managed 编排权威；BtApi 仍是面向业务的 SDK façade，provider 提供远端事实，
risk 拥有额度，gateway 拥有共享会话/路由。先单笔及恢复，再兼容同向聚合，最后按 capability 实现高级
模式；不做无证明的反向净额化或“原子”多腿。真实成交回执才改变 fill/allocation，transport ACK 不算成交。

**可行性判断：** 现有 lease、迁移、CTP budget 提供可复用基础，具备渐进抽取条件；尚不能据静态阅读
证明全部可原样迁入。A/B 的限定 spike 必须产出：私有调用点表、单笔 golden trace、旧 journal 迁移样本、
每个 crash point 的恢复对照、调用者不导入私有实现证明及存储延迟分解。失败时重估 B，不复制 fallback。
双读仅用于离线比对，双写禁止；保留 direct 兼容不会使显式 managed 请求回退私有实现。

验证：AC41-03/06～10/21～27/56～60/62；真实 runner L2 最少两个参考入口。源码行数或 fsync
出现次数不等于每单成本，不以“有 10 处 fsync”推断每单做 10 次同步写。

## 4. ADR-41-14：配置优先的三模式运行合同

**背景。** 实码核查确认现有 examples 的 `config.yaml` 角色、默认 mode 和 CLI 覆盖规则并不一致；schema-v3 的
手工插件开关还会要求操作者理解 route、账户访问和五个能力包的组合。用户要求将 `config.yaml` 设为必需文件，
由它控制 `backtest`、`simulation`、`live`，并让日常操作更短、更不易误触实盘。

**决定。** 所有 inventory runtime 使用本地、精确忽略的 schema-v4 `config.yaml`，并由受版本控制
`config.example.yaml` 提供模板。`runtime.mode` 和 `runtime.preset` 是唯一的运行选择；版本化 preset registry 生成只读 `EffectiveRuntimeConfig`，而非让用户填写
plugin flags、route 或账户访问。普通 profile 的秘密由 `secrets_ref` 指向被忽略 `secrets.yaml` 或 OS secret store；CTP SimNow 私有 `simulation/sandbox` 扩展按用户要求在受限、未跟踪的 config 中显式填写成对 `md_front`/`td_front`、合约范围与认证字段，并使用 `secrets_ref: config_yaml`。后端只从 sealed config candidates 做有界无凭据 TCP 选择，绝不按时间/日历选档或连接失败后回退；用户不选择 set1/set2/profile/calendar，provider environment 由受信代码固定为通用 `simnow`，不从地址推断 set1/set2。显式运行 `prepare-ctp-config --source-env` 可将完整编号 CTP_SET1 和配对 CTP_SET2 `.env` front 输入转换为无 set 标签的 ordered `front_pairs`；这不代表运行时读取 `.env` 或按 set/time 选择。旧代码还保留独立 `ctp_production` schema、production read-only 候选选择前置合同与 `runtime-production/` path；它们现标记为 legacy/deferred migration evidence，而非 operator contract。当前唯一目标是让 SimNow 与未来 production CTP 使用同一个 registered runtime `config.yaml` 和规范 `ctp:` field shape；用户未来启动 production 阶段时，只在该文件切换经审阅的 live mode/preset 并替换 account/front/instrument parameters。共享 schema/parser/private-config migration 已实现；默认 route 中同一 CTP runner 的 live-mode dispatch、SDK pin、真实生产 session 与写授权均未完成，旧 parser/selector fake tests 不代表 readiness。SimNow 私有例外仍不提供写权限或 production route。已实现的
`bt-runtime bootstrap` 只创建不存在的配置，`validate`/`run` 内置严格检查，`doctor` 是只读诊断；命令行和环境变量
不得覆盖 mode/preset。live 仅允许受管预设，且确认只绑定已审批的配置指纹，不能授权或升级模式。

**后果。** 既有 direct 映射代码仍可由受限 preset 调用，但“无配置 direct 启动”被移除。历史 schema-v3 必须显式迁移；
既有纯策略参数文件可保留为 registry hash 绑定的内部输入，但不得再决定运行模式或权限。所有执行前拒绝都必须证明 0 网络、
0 provider write；可允许写入的 sandbox write/live 必须保留模式、预设、审批、风险和监控的可追溯证据。

**验证。** AC41-76～84、FR41-14～16/22/24/25、NFR41-05/08/09 和
[配置与运行模式规格](配置与运行模式规格.md)。

## 5. ADR 索引与签收门

索引中的状态指设计记录，不是代码实现。PENDING_IMPLEMENTATION_DETAIL 的条目在相应 WP 的
contracts freeze 前补机械 vectors/参数并由表列责任角色签收；不得留空进入依赖它的写入实现。

| ADR | 主题 | 当前决定/来源 | 实现前签收责任 |
| --- | --- | --- | --- |
| ADR-41-01 | 单一 journal 与账户身份 | 设计文档 execution scope/authority；单 writer，禁止双写 | SDK + execution 维护者 |
| ADR-41-02 | risk reservation | 两路共用 durable authority，managed 绑定 child，不把 direct 当 OMS | risk + execution 维护者 |
| ADR-41-03 | monitor command | 持久化去重、目标确认、超时升级；无 executor 不报 drain 完成 | monitor + operator |
| ADR-41-04 | 数据保留 | 未确认事件/未终结未知订单不按普通日志清除；预算见验收附录 | execution + monitor + QA |
| ADR-41-05 | 回滚 | 冻结→清理/对账→人工切换；不能自动 direct | SDK + operator |
| ADR-41-06 | 包依赖与 pin | 独立 wheel、optional integration、逻辑 repo identity；空包 strict 拒绝 | 各库维护者 |
| ADR-41-07 rev3 | 历史 runtime 配置 | schema-v3 的注册目录/无隐式 enabled 决定；已被 ADR-41-14 的必需 v4 配置取代 | SDK + Backtrader 维护者 |
| ADR-41-08 | gateway / transport | [插件与ZMQ架构](插件与ZMQ架构.md) 是四拓扑与协议的权威文档 | gateway + transport 维护者 |
| ADR-41-09 | TradeLogger 与 monitor | 本文 §2，DECISION_RECORDED | monitor + Backtrader + QA |
| ADR-41-10 | execution 复用与聚合层次 | 本文 §3，兼容 spike 待执行 | execution + SDK + QA |
| ADR-41-11 | 存储与 durability | [设计文档](设计文档.md) 存储决策；具体 crash vectors/目标平台 benchmark 待执行 | execution + risk + QA |
| ADR-41-12 | AI 信任边界 | [设计文档](设计文档.md) AI 交接；shared schema 归 bt_api_base，三种凭证分离 | base/三产品维护者 + operator |
| ADR-41-13 | 平台、性能与容量 | [验收用例与基准](验收用例与基准.md)，Windows/Linux 3.11，候选预算未测 | QA + SDK + operator |
| ADR-41-14 | 配置优先三模式合同 | 本文 §4；必需 schema-v4、mode/preset seal、secret split、bootstrap/run/doctor、live 指纹确认 | SDK + Backtrader + QA + operator |
| [ADR-41-15 (PROPOSED)](ADR-41-15-ctp-store-session-handoff-proposal.md) | CTP Store–Execution Session handoff | 提案；统一账本、耐久命令、OrderRef cutover 与 provider 回执边界；不是写入授权 | SDK + execution + Backtrader + QA |
| [ADR-41-16 (PROPOSED)](ADR-41-16-simnow-f14-writer-fence-proposal.md) | 唯一 F14 决策 ADR：SimNow 有界操作性 S 与 strict/production P 边界 | S 尚未批准或实现，P 外部账户级控制未验收；两者当前均 `NO_WRITE / LIVE_NO_GO`。[非规范可行性复核](evidence/ctp-f14-two-level-acceptance-review-2026-09-25.md)不形成第二份决策。 | SDK + operator + risk + QA |
| [ADR-41-17 (PROPOSED / NOT_ACCEPTED)](ADR-41-17-session-snapshot-config-scope-proposal.md) | 启动封存 run-scope 与 session 非热重载 | 同一受保护 `config.yaml`、同一最终 runner；提案不改现行 P2/AC/xfail，不开放 route；须先评审是否接受活动 session 不因文件编辑即时撤销。 | runtime + config/security + risk + QA |

后续 ADR 从 17 编号，不能覆盖现有编号。ADR 提案状态不代表签收或运行能力。人物任命、签收记录与基线冻结规则见
[审阅裁决记录](审阅裁决记录.md)。
