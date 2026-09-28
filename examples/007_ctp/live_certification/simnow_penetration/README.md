# SimNow 穿透式认证场景集（历史 source，当前禁用）

这 33 个场景仍保留为历史认证设计和后续 managed migration 的测试素材，但当前代码包含
旧的 direct CTP/SimNow provider、报单和撤单路径。它们不属于 Iteration 41 的受管执行
入口，不能用于账户、沙盒或生产验收。

所有 `run_case.py`、`run_all.py` 和 `cases/*.py` 直启路径现在都会在 Backtrader、CTP
或 provider 导入前 fail-closed。旧参数（包括 `--list`、场景 ID、`--all`、
`--report-root`）也不能恢复 direct child process。真实认证操作是 `NOT_SUPPORTED`，直到
独立的 managed TestExecutionProfile、账户预算/TTL、清理对账和 provider admission 都
完成审查。

007 原有的本地零 I/O replay migration report 仍保留：

```bash
bt-runtime bootstrap --strategy-dir examples/007_ctp/runtime
bt-runtime run --strategy-dir examples/007_ctp/runtime
```

`runtime/config.yaml` 必须存在且由 Git 忽略。缺少时返回 `CONFIG_REQUIRED`；已有文件
不会被 bootstrap 覆盖（`CONFIG_EXISTS`）。输出 `LOCAL_REPLAY_ONLY` 仅证明 config gate
与 no-action probe；它不是 CTP 连通、SimNow/宏源账户、报撤单、成交、PnL 或实盘准入证据。
目前 inventory 共 17 个注册项，其中包括 007 suite 根的 `simulation/sandbox` 零写只读
runtime/front-check 注册。受保护配置和目录 ACL 已与 013_3 对齐。离线 `doctor` 成功
（exit 0，`provider_preflight_started=false`，识别到 5 组 front pairs，
`preflight_available=false`）。普通 `preflight` 仍 fail-closed，等待有界 Windows Job
supervisor 和独立验收。2026-09-28 root 使用显式
`check-ctp-fronts` 做了一次无凭据 TCP 检查：索引 3 的 MD/TD 各 3/3 可达并被选择，
其余索引 0/1/2/4 均为 0/3。它只是本机当时的 TCP 可达性观察，不证明账号登录、行情
订阅、报单、撤单或后续持续可达。
选择只比较配置内完整的 MD/TD 配对：每端三次 TCP 采样至少成功两次，再用两端成功
样本延迟中位数的较大值评分，选分数最低的一对；同分按配置顺序。单个地址可达不足以
入选，也不会按时钟、set 名称或配置外地址切换。
对 suite 根执行 `bt-runtime run --strategy-dir <suite-root>` 仍以
`profile_dispatch_unavailable`/exit 2 拒绝，且 `provider_preflight_started=false`；该
注册没有 runner。上面的本地零 I/O replay 命令使用另一个既有 007 runtime 目录。

## Managed 真实认证迁移计划（尚未接入）

已为 33 个真实 SimNow 认证案例建立独立目录和显式入口。当前 `_strategy.py` 保存待接入的真实动作与证据计划，以及未注册的只读 typed 观察逻辑；尚未实现 provider 执行：

```text
simnow_penetration/
├── config.yaml                 # suite 共享的本地受保护配置，Git 忽略
└── cases/
    ├── C01/
    │   ├── config.yaml         # 仅案例参数；不放账号或认证字段
    │   ├── C01_strategy.py
    │   └── run.py
    ├── T01/
    │   ├── config.yaml
    │   ├── T01_strategy.py
    │   └── run.py
    └── ...                     # 共 33 个案例目录
```

suite 根 `config.yaml` 已从 013_3 的受保护配置准备，并只将 `strategy.id` 重绑为
`example.007_ctp.simnow_penetration`。它是 schema-v4 `simulation/sandbox` 配置，包含
五组显式 MD/TD 前置候选；文件仍受本机 ACL 保护并由 Git 忽略。007 已有对应的 sandbox
零写只读 runtime/front-check 注册，但没有认证 case runner、交易 runner 或写权限。
新部署若需生成这个受保护文件，可显式使用
`bt-runtime prepare-ctp-config --runtime-id example.007_ctp.simnow_penetration.ctp_private --source-env <owner-only绝对路径>`。
生成工具只接受代码登记的 007/013_3 目标，默认仍是 013_3；已有文件不会被覆盖，
生成配置不授予登录或交易权限。
每个案例目录里的 `config.yaml` 只保存该案例所需的非秘密参数，33 个案例共用 suite
根受保护配置，不复制凭据。

未注册的 `managed_case_scope.py` 可将案例配置、静态策略计划、`run.py` 的摘要与
受封装的 suite runtime 配置摘要、33 项代码自有场景身份绑定，供未来真实回调证据核对。
这个绑定不导入策略、不启动 SDK，
也不授权行情或报撤单。历史计划曾把其中 5 项标为可选；本次目标要求 33 项全部取得
真实通过证据，不能跳过这些项目。
`common/case_engine.py` 对 33 项计划做静态检查，并为回调、监控和外部控制证据定义
不同的来源要求；即使资料齐备也只返回 `REVIEW_REQUIRED`，不会产生真实认证 `PASS`。
未注册的 `common/decision_engine.py` 为 33 项分别定义 typed 动作候选及真实观察前置条件；
`managed_case_scope.decision_scope_from_case_scope()` 将已封装的 suite 与案例摘要绑定到该
决策契约。没有受信来源验证器时一律 `BLOCKED`，即使离线合约资料齐备也不提供派发权限或
认证 `PASS`。
未注册的 `managed_case_invocation.py` 进一步核对单次案例的配置、策略和入口文件摘要，
并把受封装的 suite 配置、完整 MD/TD 候选集合与 TCP 选择证据绑定到同一调用身份。
调用方构造的活跃账户租约快照会被拒绝，直到受信租约所有者验证器接入；TCP 样本的
内部一致性会检查，但不能证明其真实采集来源，也不授权 SDK 会话、行情或报撤单。

未注册的 `managed_case_front_selection.py` 将当前受封装配置与一次有界、无凭据的
TCP 前置节点检查结果绑定成只含摘要、索引和计数的本地回执。其独立复核与主树回归通过；
它不验证 provider 登录、行情、账户或交易，也未接入案例入口。

007 的零写 sandbox/front-check 路由已在代码中接入；2026-09-28 的一次显式检查选择了
索引 3，但该结果仅说明当时本机到该 MD/TD pair 的 TCP 连接可达。它不证明登录、行情
订阅、结算、报单、撤单或 007 案例准入。普通 `preflight` 仍 fail-closed，等待有界
Windows Job supervisor 和独立验收。`managed_case_entry`
对 33 个认证案例仍返回 `BLOCKED`，因为认证 case runner 尚未注册；这是路由不可用结果，
不能计为真实 SimNow `PASS`。

最新逐目录子进程复跑的 33 个 `run.py` 均以 exit 2 返回 `BLOCKED`，真实案例 `PASS=0`，
真实报单与撤单写入均为 0。六个相关 runtime 文件的较早 fake/offline 集成焦点为
176 passed、13 skipped；较早一次 `tests/unit/live_certification` 复跑为 357 passed，
完整 `tests/unit/runtime` 为 2,131 passed、30 skipped、2 xfailed，均有 1 个现存 pytest
配置 warning。离线测试不建立真实 provider 或交易验收。

旧版结果构造器现在会把没有受信执行后证据适配器的 `PASS` 请求降为 `FAIL`；
序列化、计算退出码或保存结果时也会拒绝手工构造或篡改的 `PASS`。历史 JSONL 只作诊断记录，不能凭
调用方字段或伪造回调升级认证状态。33 个新入口仍全部返回 `BLOCKED`。
未注册的 `common/completion_invariants.py` 为 33 项提供纯数据的请求、委托、成交和
最终账户快照闭环检查；资料完整时最多返回 `REVIEW_REQUIRED`，且不能验证进程内资料
的真实来源，不会派发交易或生成认证 `PASS`。其中 33 例统一负测只证明缺少场景证据时
不会升入复核，尚未覆盖 33 类全部正反边界。

当前平铺的 `cases/*.py` 是历史来源和已封闭路径，只供阅读旧案例设计。它们经过
fail-closed 入口，不能驱动上述新案例，也不能作为真实认证结果。新案例的 `run.py` 和
策略须使用受管运行时提供的真实 provider 数据与回调证据；本地 fixtures、fake、合成
行情或 `live_seed_bar` 回退不能产生真实案例 `PASS`。在 provider admission、隔离监督、
预算与 TTL、终态清理和对账等条件完成独立审查前，真实认证仍为 `NOT_SUPPORTED`，写入
仍为 `NO_WRITE / LIVE_NO_GO`。

## 已封闭的历史目录结构

```bash
simnow_penetration/
├── README.md
├── run_case.py          # 统一运行器（支持单个/批量/全部）

├── run_all.py           # 快捷全量运行

├── common/
│   ├── config.py        # SimNow 环境配置与凭据

│   ├── result.py        # PASS/FAIL/BLOCKED 结果模型

│   ├── runtime.py       # Store/Broker/Feed 初始化 & 子进程入口

│   └── helpers.py       # 日志读取、证据收集工具

├── cases/
│   ├── C01_connect_and_login.py
│   ├── T01_open_order.py
│   ├── T02_close_order.py
│   ├── T03_cancel_order.py
│   ├── M01_connection_success_display.py
│   ├── M02_disconnect_display.py
│   ├── M03_reconnect_success.py
│   ├── M04_order_count_stats.py
│   ├── M05_cancel_count_stats.py
│   ├── O01_repeat_open_order.py         (选测)
│   ├── O02_repeat_close_order.py        (选测)
│   ├── O03_repeat_cancel_order.py       (选测)
│   ├── TH01_order_threshold_setting.py
│   ├── TH02_order_threshold_alert.py
│   ├── TH03_total_threshold_setting.py
│   ├── TH04_total_threshold_alert.py
│   ├── TH05_repeat_threshold_setting.py (选测)
│   ├── TH06_repeat_threshold_alert.py   (选测)
│   ├── V01_invalid_instrument.py
│   ├── V02_invalid_price_tick.py
│   ├── V03_exceed_max_volume.py
│   ├── E01_insufficient_funds.py
│   ├── E02_insufficient_position.py
│   ├── E03_market_state_error.py
│   ├── EM01_restrict_trading.py
│   ├── EM02_pause_strategy.py
│   ├── EM03_force_logout.py
│   ├── B01_batch_cancel_partial.py
│   ├── B02_batch_cancel_pending.py
│   ├── L01_trade_info_log.py
│   ├── L02_system_run_log.py
│   ├── L03_monitor_info_log.py
│   └── L04_error_info_log.py
└── reports/
    └── latest/           # 最近一次运行的结果
        ├── summary.json  # 33 场景汇总
        └── C01/
            ├── result.json
            ├── stdout.log
            └── logs/
                ├── system.log
                ├── monitor.log
                ├── error.log
                └── order.log

```

## 33 场景清单

### 连通性 (1)

| ID | 名称 | 必做 |

|----|------|------|

| C01 | 验证登录测试账号通过柜台认证并完成账号登录 | ✓ |

### 基础交易功能 (3)

| ID | 名称 | 必做 |

|----|------|------|

| T01 | 验证能正常下达开仓指令 | ✓ |

| T02 | 验证能正常下达平仓指令 | ✓ |

| T03 | 验证能正常下达撤单指令 | ✓ |

### 系统连接异常监测 (3)

| ID | 名称 | 必做 |

|----|------|------|

| M01 | 验证连接成功时能正常显示连接成功 | ✓ |

| M02 | 验证连接断开时能正常显示连接断开 | ✓ |

| M03 | 验证连接断开后能正常显示重连成功 | ✓ |

### 报撤单笔数监测 (2)

| ID | 名称 | 必做 |

|----|------|------|

| M04 | 验证能正常统计报单笔数 | ✓ |

| M05 | 验证能正常统计撤单笔数 | ✓ |

### 重复报单监测 (3, 选测)

| ID | 名称 | 必做 |

|----|------|------|

| O01 | 验证能统计重复开仓单报单笔数 | 选测 |

| O02 | 验证能统计重复平仓单报单笔数 | 选测 |

| O03 | 验证能统计重复撤单报单笔数 | 选测 |

### 阈值设置及预警 (6, 其中 2 选测)

| ID | 名称 | 必做 |

|----|------|------|

| TH01 | 验证提供报单笔数统计阈值设置功能 | ✓ |

| TH02 | 验证报单笔数达到或超过阈值时会预警 | ✓ |

| TH03 | 验证提供报撤单总数统计与阈值设置功能 | ✓ |

| TH04 | 验证报撤单总数达到或超过阈值时会预警 | ✓ |

| TH05 | 验证提供重复报单笔数统计与阈值设置功能 | 选测 |

| TH06 | 验证重复报单笔数达到或超过阈值时会预警 | 选测 |

### 错误防范 (3)

| ID | 名称 | 必做 |

|----|------|------|

| V01 | 验证订单合约代码错误时系统能检查并拒绝报单 | ✓ |

| V02 | 验证订单价格最小变动价位错误时系统能检查并拒绝报单 | ✓ |

| V03 | 验证订单委托数量超过单笔最大委托数量时系统能检查并拒绝报单 | ✓ |

### 错误提示 (3)

| ID | 名称 | 必做 |

|----|------|------|

| E01 | 验证系统能接收并展示柜台返回的资金不足错误码 | ✓ |

| E02 | 验证系统能接收并展示柜台返回的持仓不足错误码 | ✓ |

| E03 | 验证系统能接收并展示柜台返回的市场状态错误码 | ✓ |

### 应急处理 (3)

| ID | 名称 | 必做 |

|----|------|------|

| EM01 | 验证系统可通过限制账号交易权限方式暂停交易 | ✓ |

| EM02 | 验证系统可通过暂停策略执行方式暂停交易 | ✓ |

| EM03 | 验证系统可通过强制账号退出方式暂停交易 | ✓ |

### 批量撤单 (2)

| ID | 名称 | 必做 |

|----|------|------|

| B01 | 验证系统支持将多笔部分成交报单进行批量撤单 | ✓ |

| B02 | 验证系统支持将多笔已报单进行批量撤单 | ✓ |

### 日志记录 (4)

| ID | 名称 | 必做 |

|----|------|------|

| L01 | 验证系统日志中会记录交易信息 | ✓ |

| L02 | 验证系统日志中会记录系统运行信息 | ✓ |

| L03 | 验证系统日志中会记录监测信息 | ✓ |

| L04 | 验证系统日志中会记录错误提示信息 | ✓ |

## 结果状态

| 状态 | 退出码 | 含义 |

|------|--------|------|

| `PASS` | 0 | 旧结果模型中的场景状态；本身不是 SimNow 或实盘准入证据 |

| `FAIL` | 1 | 场景验证失败（代码或逻辑错误） |

| `BLOCKED` | 2 | 外部条件不满足（SimNow 不稳定、市场关闭等） |

此表描述历史案例结果格式。对于新迁移入口，`managed_case_entry` 的 `BLOCKED` 不能被
退出码、旧日志或人工补填改写成 `PASS`；只有未来经审查的受管真实运行及其权威证据，
才可能支持真实案例结论。

## 已知高风险场景

以下场景在 SimNow 7x24 环境下可能无法稳定复现，会输出 `BLOCKED` 并记录证据：

- **M02 / M03**：断开与重连
- **E01 / E02 / E03**：远端错误码
- **EM03**：强制账号退出
- **B01**：部分成交后批量撤单

## 当前审查增补（2026-09-28）

C01 r3 的 17 个目标已主树集成。冻结候选完整套件为 482 passed；主树 `tests/unit/live_certification` 回归为 **488 passed、1 个既有 warning**。17 个目标 Ruff 通过，集成内容与冻结候选在 CRLF 归一化后逐字一致，`git diff --check` clean。独立 schema QA 对精确 r3 patch 的结论为 `GO for source-only integration`；独立 alias/session 复核为 197 passed。这些结果只覆盖离线源码合同。C01 仍为 `INCOMPLETE`：可信 SDK issuer ledger verifier 和 baseline/final query receipt path 尚未接通，也没有可认证的 native callback 来源、受信账号 owner 或 provider 证据。

逐目录检查的 33 个 `run.py` 均为 `BLOCKED` / exit 2，原因是 `managed_ctp_certification_not_registered`；network/order_write 均为 0，真实 `PASS` 为 0。不能将这些入口或离线用例描述为真实 SimNow 通过。

隔离 ledger 原型按完整 C01 序列建模八个 RequestID（auth、login、baseline 与 final 的 orders/positions/funds 查询），16 项 fake-only 测试通过。它只证明本地请求/回调关联合同，不能证明真实 native/provider callback，也没有接入当前 runner。

G1 六项故障注入审计结论为 `G1_STRICT_WHOLE_COMMAND = NO_GO`：backend 创建、launcher resume、Job termination、句柄释放、control escrow 和回执写入中的同步调用都可能超过配置期限后才返回。G4 parent/gateway 来源审计及独立 QA 结论为 `HOLD_PROVENANCE`；候选的离线 fake 和制品一致性结果不认证上游源码来源。以上均未启用 preflight、真实 provider 或任何写路由。详细记录见[验收证据增补](../../../../docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-007-simnow-33-case-staging-acceptance-2026-09-28.md)。
