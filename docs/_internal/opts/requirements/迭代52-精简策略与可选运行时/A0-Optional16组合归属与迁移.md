# I52-A0：Optional16 组合归属与迁移

状态：A0 静态归属补充；仅根据限定的公开源码与既有 A0/I52 规划核对，未实施迁移、未运行验收。记录日期：2026-10-31。

## 范围与核对方法

本轮只读取以下八个精确公开文件：

- examples/live/000_live_certification/optional16/spec.py
- examples/live/000_live_certification/optional16/components.py
- examples/live/000_live_certification/optional16/run_matrix.py
- examples/live/000_live_certification/optional16/gateway_capability_check.py
- examples/live/000_live_certification/optional16/README.md
- docs/_internal/opts/requirements/迭代52-精简策略与可选运行时/A0-交易示例与认证清单.md
- docs/_internal/opts/requirements/迭代52-精简策略与可选运行时/A0-认证逐案迁移矩阵.md
- docs/_internal/opts/requirements/迭代52-精简策略与可选运行时/I52-A-清点与统一合同.md

组合身份按 spec.py 的静态定义核对：transport 的两个字面值为 direct 与 gateway_zmq；COMPONENT_FLAGS 顺序为 execution、risk、monitor；三个布尔值按 0/1 编码；combo_id 的格式为 transport-eX-rX-mX。按 matrix_specs 的嵌套循环展开 2×2×2×2 共 16 项，并与 A0-交易示例与认证清单中既有的 16 项列表逐项比对。没有导入或执行 spec、matrix runner、case、provider 或账户。

归属区分为“旧源码能证明的挂载点”和“I52 目标 owner”。前者仅说明留存代码引用哪个包或把请求交给哪个对象；后者在没有当前生产调用方、完整装配链及对应 SDK 证据时仍标为候选。gateway_capability_check.py 和 run_matrix.py 的退休行为按其源码与 README 记录；不读取历史矩阵、journal、配置、环境变量、证据或冻结 fixture 内容。

## 归属口径

- **direct 传输（T-D）—候选 owner：** components.py 的 wrap_client 接收已构造的 client，并由 ComponentClientWrapper 将连接、查询及未被可选 mount 接管的写请求交给 _base。此限定源码没有证明 _base 的构造调用方或某个 I52 direct adapter 是唯一 owner。下一步需核对公开源码中的当前 direct client 构造与活跃调用点。
- **gateway_zmq 传输（T-G）—候选 owner，具体 owner 未证实：** 同一个 wrapper 只记录所选 transport 名称，不构造 gateway 或负责其进程/通信生命周期。README 将 gateway_server.py 描述为留存源码支持，并明确其存在不构成未来部署建议；本轮未读取该文件，也未证明当前 gateway client、server、Supervisor 或 I52 调用点。下一步需核对公开源码中的 gateway 两端构造、调用链、关闭责任与当前活跃引用。
- **Execution 开启（E=1）—旧源码挂载候选：** _ExecutionMount 懒加载 bt_api_execution，创建执行与撤单 facade/store；_DispatchPort 最终调用 _base 的 place_order。因此该挂载点没有取得传输或 provider I/O owner。I52 目标 owner 仍为候选，需核对 SDK 契约、活跃装配与真实 transport 边界。
- **Execution 关闭（E=0）：** 此 wrapper 不导入、不挂载 _ExecutionMount；place_order 和 cancel_order 交给 _base。这里没有 execution 子项目 owner，也不构成风险检查、权限授予或 I52 direct-write 支持证明。
- **Risk 开启（R=1）—旧源码挂载候选：** _RiskMount 懒加载 bt_api_risk 的 DurableRiskGate。若 E=1，旧 wrapper 用 SharedRiskAdmissionAdapter 将风险 gate 接入执行 facade；若 E=0，旧 wrapper 在调用 _base.place_order 前经风险 gate。I52 的风险策略、scope、配置来源和与统一合同的兼容性均未被本轮证明，目标 owner 仍为候选。
- **Risk 关闭（R=0）：** 此 wrapper 不导入、不挂载 _RiskMount，不创建此层的 permit/admission 责任。若 E=1，旧代码记录 allow_unprotected 路径；若 E=0，请求直接交给 _base。关闭不能被解释为已通过 I52 风险审查。
- **Monitor 开启（M=1）—旧源码挂载候选：** _MonitorMount 懒加载 bt_api_monitor 的 DurableOutbox，记录本地事件并尝试确认/只读回读。它不负责订单派发，也不是账户或订单事实权威。I52 目标 owner 与运行、持久化和关闭边界仍需另行确认。
- **Monitor 关闭（M=0）：** 此 wrapper 不导入、不挂载 _MonitorMount，也不在该层记录 monitor 事件；不代表系统不存在其他监控 owner。

上述包名和挂载点是留存 source 的静态事实，不是当前已安装、可用、兼容或被生产入口启用的证明。Optional16 是可选子项目候选集合；任何组件位设为 1 均不得直接推导出 I52 组件能力已接受。

## 16 个精确组合的逐项归属

表中 T-D/T-G 分别指上文的 direct/gateway_zmq 传输候选 owner。每个 E/R/M 单元明确列出开启或关闭含义。所有组合的正式状态均为历史 checkpoint 0/16；本轮没有任何逐项 formal PASS，16 项均未验收。

| combo_id | 传输 owner | Execution owner | Risk owner | Monitor owner | formal 状态 |
| --- | --- | --- | --- | --- | --- |
| direct-e0-r0-m0 | T-D：候选，待追踪 _base 构造方 | 关闭：不挂载；写/撤单交给 _base | 关闭：不挂载；此层无风险 gate | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| direct-e0-r0-m1 | T-D：候选，待追踪 _base 构造方 | 关闭：不挂载；写/撤单交给 _base | 关闭：不挂载；此层无风险 gate | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| direct-e0-r1-m0 | T-D：候选，待追踪 _base 构造方 | 关闭：不挂载；写/撤单交给 _base | 开启：候选 _RiskMount / bt_api_risk | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| direct-e0-r1-m1 | T-D：候选，待追踪 _base 构造方 | 关闭：不挂载；写/撤单交给 _base | 开启：候选 _RiskMount / bt_api_risk | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| direct-e1-r0-m0 | T-D：候选，待追踪 _base 构造方 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 关闭：不挂载；execution 走旧 allow_unprotected 路径 | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| direct-e1-r0-m1 | T-D：候选，待追踪 _base 构造方 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 关闭：不挂载；execution 走旧 allow_unprotected 路径 | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| direct-e1-r1-m0 | T-D：候选，待追踪 _base 构造方 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 开启：候选 _RiskMount / bt_api_risk；旧代码接入 admission adapter | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| direct-e1-r1-m1 | T-D：候选，待追踪 _base 构造方 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 开启：候选 _RiskMount / bt_api_risk；旧代码接入 admission adapter | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| gateway_zmq-e0-r0-m0 | T-G：候选，gateway 两端 owner 未证实 | 关闭：不挂载；写/撤单交给 _base | 关闭：不挂载；此层无风险 gate | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| gateway_zmq-e0-r0-m1 | T-G：候选，gateway 两端 owner 未证实 | 关闭：不挂载；写/撤单交给 _base | 关闭：不挂载；此层无风险 gate | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| gateway_zmq-e0-r1-m0 | T-G：候选，gateway 两端 owner 未证实 | 关闭：不挂载；写/撤单交给 _base | 开启：候选 _RiskMount / bt_api_risk | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| gateway_zmq-e0-r1-m1 | T-G：候选，gateway 两端 owner 未证实 | 关闭：不挂载；写/撤单交给 _base | 开启：候选 _RiskMount / bt_api_risk | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| gateway_zmq-e1-r0-m0 | T-G：候选，gateway 两端 owner 未证实 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 关闭：不挂载；execution 走旧 allow_unprotected 路径 | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| gateway_zmq-e1-r0-m1 | T-G：候选，gateway 两端 owner 未证实 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 关闭：不挂载；execution 走旧 allow_unprotected 路径 | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |
| gateway_zmq-e1-r1-m0 | T-G：候选，gateway 两端 owner 未证实 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 开启：候选 _RiskMount / bt_api_risk；旧代码接入 admission adapter | 关闭：不挂载；此层无 monitor 事件 | 历史 0/16；本项未验收 |
| gateway_zmq-e1-r1-m1 | T-G：候选，gateway 两端 owner 未证实 | 开启：候选 _ExecutionMount / bt_api_execution；派发仍到 _base | 开启：候选 _RiskMount / bt_api_risk；旧代码接入 admission adapter | 开启：候选 _MonitorMount / bt_api_monitor | 历史 0/16；本项未验收 |

## 模式、环境与权限边界

combo_id 只编码 transport 与 execution/risk/monitor 三个布尔位。它不编码 replay、shadow、paper 或 live mode，不编码账户环境、provider endpoint、账户/凭据引用、策略授权或读写权限。不得从组合名、transport 名称、旧配置缺省值、组件开关、README 描述或组件已启用推断这些值。真实 config.yaml 和 .env 不在本轮读取范围内。

I52-A 规定 mode、账户环境、endpoint、凭据引用、路由 scope、数据来源与写权限应分别经版本化配置合同验证；未知、交叉环境或隐式授权必须 fail closed。A1 合同及逐项能力矩阵尚未通过前，这 16 个旧组合都不能作为可运行的 paper/live plan。I52 仅以 paper/live 为本轮实现与验收范围；replay、shadow 和旧本地撮合继续延期，不在本轮运行或本地验收。

## 退役路径保留与后续迁移步骤

README 将 Optional16 acceptance path 标为 retired。run_matrix.py 与 gateway_capability_check.py 仅输出 BLOCKED/optional16_acceptance_retired 并返回 exit 2，不读取配置或凭据、不启动 child/gateway、不写结果。应原样保留这些入口、spec/components、gateway 支持源码及历史 matrix/journal/evidence；不得复活旧 runner、改写旧矩阵或把旧组合称为已迁移、已支持或已接受。

后续只可把 16 项作为历史拓扑身份和候选需求输入。建议按以下顺序继续，逐项核对相应公开源码：

1. 在 A0 后续归属审查中追踪每个当前 paper/live 入口的 direct client 构造、gateway 客户端/服务边界、进程/资源关闭 owner，以及 execution/risk/monitor SDK 的实际 import、适配与活跃引用。不能证实的 owner 继续标为候选或 BLOCKED。
2. 在 A1 冻结显式 mode、账户环境、endpoint、凭据引用、路由 scope 和权限合同，并定义每个 optional 子项目的能力矩阵、唯一写派发 owner、启动/停止与失败关闭规则。组合位不得成为授权位。
3. 只有在 owner 与合同接受后，才逐项决定哪些历史 transport/component 需求可映射到新的 paper/live topology；明确标出不支持项和依赖。使用普通 Strategy 与经核实的 Feed/Broker/Store 入口，先形成受限的源码/装配证据，再分别进行必要的账户 formal 验收。此处没有任何已迁移项或已接受项。

## 结论

Optional16 在本轮的交付仅为 16 个历史身份的逐项候选 owner 映射与下一步。历史 formal 状态保持 0/16，每个组合均未验收。没有证据表明策略源码、formal 矩阵、gateway、execution、risk 或 monitor 已迁移到 I52，也没有证据表明任何组件当前可用或获得账户写权限。
