# 迭代 41 配置优先模板

状态：`PARTIALLY_IMPLEMENTED / LIVE_NO_GO`。schema-v4 与 CLI 的 config-first 基础已进入源码；默认 registry 当前有
16 条：11 条 nonmanaged `simulation/replay`（8 个普通策略、`examples/007_ctp` 与
`examples/010_live_examples` 两条 legacy no-action，以及 historical `sample.py` no-action migration profile）、两条隔离
fake-provider managed L2 runtime、一条无 runner/能力授权且 `sandbox_write_policy=deny` 的 config-bound CTP SimNow `simulation/sandbox` 私有只读路由、一条公开 OKX `simulation/shadow` 只读观察，以及一条 package-owned `backtest/local_backtest` fixture。该 fixture 只用包内四根
历史数据 bar 运行 Cerebro，网络、外部写、订单、成交和 provider submission 都为零。这里的通用 backtest/live
模板本身仍不登记 runtime，也不能据此启动或批准交易。完整边界见[实施状态与验收快照](../实施状态与验收快照.md)。
每个 Iter41 runtime 的 `config.yaml` 都是必需文件；没有文件一律 `CONFIG_REQUIRED`、零 I/O，不能默认direct。

**CTP 当前操作方向（2026-09-25）：** SimNow 与未来 production CTP 共用同一物理文件 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 和同一 canonical `ctp:` endpoint/account/instrument 字段结构。当前只推进 SimNow；未来经用户发起并独立审查后，才会在该文件切换为 `live` mode/preset 并替换同一组 CTP 参数。当前文件保存的是 SimNow `simulation/sandbox` 值；现在不预填生产账号或前置地址。切换配置本身不会启用共享 CTP runner 的 live dispatch，也不授权连接/交易；该 runner 的 live profile 与 mode-specific admission 尚未接入默认 registry/CLI。下方独立 `runtime-production/`、`ctp_production` parser/helper 与 production selector 描述均为 legacy/deferred 实现记录，不是当前 operator flow 或新的 QA 完成门。

## 三模式最小模板

| 文件 | mode / preset | 边界 |
| --- | --- | --- |
| `config.example.yaml` | backtest / local_backtest | package-owned fixture 已对该组合作本地 Cerebro 验收；通用模板仍需独立 registry 绑定，零网络、零外部交易写入。 |
| `config.simulation.example.yaml` | simulation / replay | 未来受审 registry profile 的离线确定性回放模板；fake orders/fills单列，零网络/外部写。 |
| `config.live.example.yaml` | live / managed_live_direct | 通用未来 live registry binding 的 schema 示例，不是 013_3 CTP 的操作文件或第二份 CTP 配置。013_3 未来仍只编辑受保护 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 的 mode/preset 与同一 canonical `ctp:` 块中的 account/front/contract 字段；共享 CTP runner 的 live profile 与 mode-specific admission 尚未实现并验收前不能启用。 |

普通 profile 的用户字段为 config_schema_version、strategy.id、runtime.mode、runtime.preset，以及可选 parameters、secrets_ref；CTP SimNow 私有 `simulation/sandbox` 另有规范顶层 `ctp` 块，须显式成对设置一组 `md_front`/`td_front` 或最多 8 组成对、唯一、有序的 `front_pairs`，并填写合约范围和认证字段。
受信registry展开provider/environment、route/access、能力/pin与plugins，effective config只读。用户不编辑
五插件十个布尔；高级参数只允许白名单策略参数和额外收紧限额，不能覆写mode/preset/route/access/capability/enabled。

完整preset映射：backtest→local_backtest；simulation→replay、paper、shadow、sandbox；
live→managed_live_direct、managed_live_gateway。mode/preset不匹配或未知名称必须拒绝。
paper/shadow最多按批准profile公开读，外部submit/cancel/close为0；sandbox默认是demo/SimNow认证私有只读，
external_write=0，014/015可保留此模式。只有registry批准write capability且有效sandbox receipt/admission才可写，
此时强制managed execution/risk/monitor和TestExecutionProfile；production write始终=0。只读不强套写审批。
原候选paper/demo/SimNow/production禁令不因三模式改名而解除。live没有legacy_direct preset。

## 首次创建与日常运行

建议目录由SDK registry明确登记：

```text
example/
  config.yaml                  原策略参数，继续tracked；不直接作为runtime配置
  run.py                       内部参数reader保持兼容，运行mode由runtime配置唯一决定
  runtime/                     一个常见的登记 runtime directory
    .gitignore                 必含 /config.yaml、/secrets.yaml（可另含 /reports/ 等运行时产物）
    config.example.yaml        最小v4模板
    config.yaml                必需本地runtime文件，ignored且不在index
    secrets.yaml                本地秘密文件，ignored且不在index

P1-B 的已登记 runtime directory 是 `examples/ctp_options_simnow_managed_replay_runtime/` 本身，不是 `runtime/` 子目录；始终以 registry 返回的 `<registered-runtime-dir>` 为准。
```

当前已安装的最短命令是：

```powershell
bt-runtime bootstrap --strategy-dir <registered-runtime-dir>
bt-runtime run --strategy-dir <registered-runtime-dir>
```

bootstrap仅首次原子生成该目录最安全且已登记的 preset，已有文件返回CONFIG_EXISTS，不能覆盖旧参数config或本地runtime。
批量bootstrap只接受代码拥有的受信 runtime-set 名称，不接受用户 manifest 或目录清单；先预检目录/冲突，再按目录原子创建。逐项结果和安全重试不得
覆盖差异内容、删除其他runtime、生成审批或执行交易。首次生成preset决定mode，日常run的CLI不能覆 mode/preset。
run内置配置/schema/preset policy校验；可选 `bt-runtime validate --strategy-dir ...` 与 `doctor --strategy-dir ...`
用于离线检查和诊断，不增加日常必做步骤。CTP provider/account preflight 是单独的显式只读命令，
不隐式修配置/secret或启动策略。默认 CTP 注册仍仅有 I2 制品 pin 的只读路线；其 TD/MD 完整
preflight 未通过。随后独立 I8 MD-only 诊断也以 `native_shutdown_uncertain` 结束，不能作为
登录、行情或关闭验收；见[I8 证据](../evidence/ctp-i8-md-diagnostic-2026-09-25.md)。这些结果均不授予写入或 live 路线。

未来已登记 profile 的模式修改只编辑已存在config并重新seal/preflight/独立审批。live运行还需 `--confirm-live` 确认**已经配置且
已审批**的同一合同；该标志不能改变模式、授权交易、绕过候选门或自动resume。配置删除/缺字段/旧schema-v3、
CLI --mode、未知preset、config篡改、secret环境冲突，均在plugin/provider初始化前失败。

## 参数、秘密与旧配置迁移

旧11份受Git跟踪的参数config继续保留，registry绑定其路径/hash为参数来源；运行时用户不必再传第二个--config。
旧mode/凭据字段不能反向影响runtime；schema-v3只准由显式离线迁移工具生成待审v4，不在run中自动猜测或改写。
runtime/.gitignore必须含精确的 /config.yaml 与 /secrets.yaml 条目，可另含 /reports/ 等无关运行时产物；禁止全仓ignore或批量取消旧参数文件跟踪。仓库/CI Git-index hygiene gate 拒绝将这两个本地文件写入 index；runtime loader 不查询 Git index。普通 profile 继续拒绝内联秘密；唯一受保护的规范 `ctp:` 私有配置允许本地认证字段，解析时同时接受 `simulation/sandbox` 与未来 `live/managed_live_direct` 的相同字段结构，且必须校验文件权限、脱敏与 config seal。解析 live 配置不登记 runner、不读取凭据，也不授予写入权限。

默认离线模板不需要秘密。CTP SimNow 私有模板的 `config.yaml` 是运行时 MD/TD endpoint 的唯一来源，不要求代码内静态 official-front allowlist。填写单对时直接使用该 pair；填写 `front_pairs` 时只对列表内的 1–8 组成对、唯一 mapping 做有界、重复、无凭据 TCP connect 采样，按 `max(MD median RTT, TD median RTT)` 选最低值，同分采用列表顺序。部分失败 pair 排除、全部失败则拒绝；运行会话固定所选 pair，不再切换。该连接探测只证明 TCP transport reachability，不表示 CTP login、账户身份、行情或交易通过。运行时不按时间、日历、TradingDay 或 set 名称选路，也不发现或使用未配置地址。旧 `selection`、`set1_profile`、`set2_profile`、`calendar_artifact`、`calendar_sha256` 字段必须拒绝。显式执行准备器时，可从 owner-only `.env` 读取 current、完整 SET1 编号组和成对 SET2 的 MD/TD 输入，转换为无 set 标签的 `front_pairs`；精确重复去重，半组、冲突或超 8 组拒绝。显式 owner-only YAML source 也支持 `ctp.front_pairs`。`.env` 只参与显式准备，运行时只读取 sealed `config.yaml`，不按 set/time 选档。早期 YAML/multi-source helper 聚焦合同为 `51 passed, 3 skipped`，对应的受保护输出当时为 737 bytes；当前文件内容可能随用户更新，不能以该历史长度校验配置。`secrets_ref: config_yaml` 仅适用于此受限私有 profile，不选择账户域或提升 production。

CTP 操作者可从 [config.ctp.example.yaml](config.ctp.example.yaml) 查看无真实账号信息的 canonical `ctp:` 字段和 `front_pairs` 示例。SimNow 与未来 production 使用同一受保护 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`。当前文件是 SimNow `simulation/sandbox` 值，含五组成对候选；新增官方 7x24 pair 的 MD/TD 在最近一次 TCP 检查中均不可达。未来生产阶段复用同一 CTP runner；其 live-mode admission 与独立 artifact/account/session/risk controls 验收通过后，只改这个文件的 mode/preset 与账号/前置/合约参数；共享文件本身不会启动或授权 production。`runtime-production/` 与 `ctp_production` parser/helper 是 legacy/deferred 迁移证据，不是第二份 operator config。当前 default registry 只有 sandbox 私有只读 profile，没有 write-capable shared CTP runner 或 live dispatch；live preset/route 仍 fail closed，维持 `NO_WRITE / LIVE_NO_GO`。最近的真实 I8 诊断见[I8 证据](../evidence/ctp-i8-md-diagnostic-2026-09-25.md)，其结果仍非完整 preflight。

单次 local TCP reachability evidence 和 selection 合同详见[前置探测说明](../evidence/ctp-front-pair-selection-2026-09-24.md)。日历、TradingDay 与服务时段可用于操作者判断，不参与前置选择。

**历史实现（legacy/deferred，不是当前 operator flow）：** 仓库曾有独立 `runtime-production` 私有 schema/helper 和未登记的 production read-only candidate selection precondition。旧 parser/selector focused 结果 `60 passed, 1 warning`（此前 `137 passed, 4 skipped` 为更早源码快照）只证明各自的本地 fake/config 合同；不代表当前共享配置 schema、production route、SDK pin、真实会话或批准已就绪。未来 production 复用同一 CTP runner；仍须把 mode-specific admission contracts 接入默认路线，并分别审核 artifact/account authority、credential boundary 与写入风险门；但它与 SimNow 使用同一 runtime `config.yaml`，不维护第二份生产配置，也不复用 SimNow 的 endpoint/account 参数、receipt 或审批。当前配置只保留 SimNow 值，不预填生产账号或前置地址；未来按同一字段结构替换。
gateway/supervisor client无provider凭据，唯一writer的受管部署保存。模板、index、日志、receipt、fingerprint全部脱敏。
gateway网络endpoint/security属于受信部署registry，Windows/Linux可用的TCP loopback仍必须Curve/ZAP/ACL，
不能把endpoint或安全开关下放到用户runtime YAML。

## 工作包记录

`work-package-record.example.yaml` 记录任务owner、先决条件、mode/preset矩阵、配置迁移和证据。
它不是验收receipt，未运行测试始终NOT_RUN/null。fake、sandbox和production写计数分开；缺证据不能填PASS。


The `<PLACEHOLDER_...>` values in the YAML example are synthetic only. Copy the schema into the ignored local config and provide actual account and authentication values there; never commit those values.
