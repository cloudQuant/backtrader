# 013_3 SA 中频 SimNow 示例

本目录是迭代 22 的可执行参考实现。它把策略、CTP 只读预检、显式结算确认、
订单准入、日内风险状态和证据文件接入 Backtrader 原生
`Cerebro -> BtApiFeed -> bt.Strategy -> BtApiBroker -> BtApiStore` 链路。
网络模式只创建一个由 `BtApiStore(provider="btapi")` 管理的顶层 `BtApi`；示例不访问
native Trader，也不创建第二个查询或交易客户端。CTP native 只使用 `bt_api_ctp` 随包提供的
bundle；不得接入独立 OpenCTP 客户端、服务或 framework。

当前候选固定为 `iter22-sa-v0`，研究状态为 `RESEARCH_NOT_ESTABLISHED`。本地 replay
只能证明公式、事件顺序、原生 Feed/Strategy/Broker 装配、零 SDK 写请求和证据可复现，
不能证明真实行情、成交、收益或 G3/G4。未在本机运行的 SimNow 项均应判为 `NOT_RUN`；
缺少权威交易日历或上一完整 TradingDay 的全市场排名证据时应判为 `BLOCKED`。

## 本机 SimNow 前置状态

本目录的忽略文件 `.env` 已可保存 SimNow 的公开连接默认值（`CTP_BROKER_ID=9999`、
`CTP_APP_ID=simnow_client_test`、`CTP_AUTH_CODE=0000000000000000` 和第一套 profile），但
`CTP_USER_ID` 与 `CTP_PASSWORD` 仍为空。它们只能由已在 SimNow 注册、激活后的账户提供；不能
从仓库根目录的交易所 API `.env` 推断或复制。新机器可从 `.env.example` 建立本地 `.env`，
该文件同样不应提交。

当前 checkout 的 `config.yaml` 引用了忽略的
`state/iter22-czce-2026-calendar-20260910.json`，但该 artifact 并不随仓库分发且本机不存在。
因此，在补入**当前、可追溯、SHA-256 一致**的 CZCE 交易日历（以及自动选约所需的上一完整
TradingDay 排名证据，或重新审核的手工冻结合约配置）之前，网络预检会按设计失败关闭。不得
用过期文件、自然日推算或手工修改 hash 绕过此门槛。

自动选约的日历必须覆盖**全部 eligible SA 合约的 `ExpireDate`**，而不是只覆盖启动当月或
2026 年；当前候选范围可能延伸到 2027。因此即使取得一份完整的 2026 日历，它也不一定足以
解除 auto 模式。没有交易所或期货公司提供的可审计逐日原件时，不能用“周一至周五减节假日”自行
合成 artifact；可改走经审核的手工冻结合约路径，但该 artifact 仍须覆盖该合约的到期日。

即使凭据和日历已齐全，`natural_signal` 目前仍不能写入订单：候选研究状态是
`RESEARCH_NOT_ESTABLISHED`，尚没有其所需的研究准入、G1/G2/G3 通过事实、短时有效且身份绑定的
admission receipt。下面的流程可以完成 replay、只读预检和影子观察；它不会伪造这些外部证据，
也不会把策略变成无条件下单程序。

历史受控验证仅作背景，不可复用为当前运行授权：2026-09-10 曾以冻结的本地 CZCE 日历和手工
冻结的 SA 合约完成一次只读 preflight，但未留存结构化收据。另一次独立受控 API 验证曾将一手
非市价限价单撤单至 `CANCELED`、零成交。这些都是
`PASS_CONTROLLED_CTP_MECHANICS` 子证据，不构成当前 G3 的 60 分钟观察，也不构成 G4 的策略
开平闭环、归零对账、收益或经济性证据。

第二套 7×24 的受限 `shadow --api-diagnostic` 已实际通过 `PASS_API_DIAGNOSTIC`：五类只读查询完整、三类状态变更请求计数增量为零，且受管 Store 停止健康为 `PASS`。该诊断以冻结候选的产品和交易所仅作为参考数据范围，不选择具体月份合约、不订阅行情、不运行策略；其 `strategy_status=NOT_RUN`，G3/G4 均为 `NOT_RUN_API_DIAGNOSTIC`。

新增的 `--engineering-strategy-observation` 是第二套唯一的策略级例外，供受限工程诊断使用，不是上述已完成 API 诊断的追溯性结果。它只能在第二套 `simnow_second_7x24` 以 `shadow --purpose observation` 显式启动，时长必须为正且不超过 3600 秒；不接受 `--preflight-only`、`--prepare-settlement` 或 admission receipt。该路径仍做运行所需的只读 Stage A/B 查询、合约选择和行情订阅，但 `allow_order_writes=false` 始终固定，结算确认、报单和撤单请求的终态计数都必须为零。即使它观察到策略和分钟线，也只产生工程结果：成功终态为 `PASS_ENGINEERING_STRATEGY_OBSERVATION`，G3 固定为 `NOT_RUN_ENGINEERING_STRATEGY_OBSERVATION`、G4 为 `NOT_RUN`；它永远不替代第一套实际时段的 G3/G4。

## 模式和写入边界

| 模式/动作 | CTP 会话 | 订单写入 | 成交/PnL | 结算确认 |
| --- | --- | --- | --- | --- |
| `replay` | 不联网，本地 fixture | 禁止 | 不生成 | 不运行 |
| `shadow --preflight-only` | 只读 | 禁止 | 不生成 | 只读核验 |
| `shadow` | 第一套实际交易时段的只读观察 | 禁止 | 不生成 | 不确认 |
| `shadow --api-diagnostic` | 第二套 7x24 的托管只读 API 查询 | 禁止 | 不生成 | 不确认 |
| `shadow --engineering-strategy-observation` | 第二套 7x24 的受限策略工程观察，正时长且最多 3600 秒 | 禁止（固定 `allow_order_writes=false`） | 不生成 | 不确认 |
| `simnow --preflight-only` | 只读 | 禁止 | 不生成 | 只读核验 |
| `simnow --prepare-settlement` | `market_data_only` | 禁止 | 不生成 | 唯一显式确认动作，随后只读回查 |
| admitted `simnow` | 托管交易会话 | receipt 限定 | 实际回报才记录 | 启动时只读核验 |

第二套 `simnow_second_7x24` 默认仅允许 `shadow --api-diagnostic`；普通 `shadow` 或 `simnow`
策略网络运行仍会在创建 Store、初始化 native 会话或连接前拒绝。唯一例外是上表的
`--engineering-strategy-observation`：它是受限的一小时以内 shadow 策略观察，不接受 receipt、
`--preflight-only` 或 `--prepare-settlement`，更不能被用作第一套 G3 或任何 G4 的替代。CLI 与
direct API 为确定冻结 profile 仍可能先水合本地忽略的 `.env`，但不会把这些值写入报告或用于建立会话。

`shadow` 和所有 preflight 路径显式设置 `auto_settlement_confirm=false`。工程策略观察也固定该值，
并在受控停机时要求 `settlement_confirm`、`order_insert`、`order_action` 计数均为零。只有同时满足
SimNow 模式、非 preflight、非 prepare、且 receipt 已通过校验时，runner 才把
`allow_order_writes` 打开。生产地址、自定义地址、MD/TD 混配、7x24 第二套交易
（只允许 API 或上述无写策略工程证据）、
缺失费用/保证金/账户身份、成功但空或多行账户查询都会失败关闭。

## SimNow 与期货公司生产 CTP 的隔离

`ctp-deployment-profiles.example.yaml` 和
`env.broker-production.NOT-SUPPORTED.example` 是未来生产接入的**分隔模板**，不是可执行配置。
当前 runner 只识别 `config.yaml` 中冻结的 SimNow profiles；生产前置、生产 front 或把生产字段写进
SimNow `.env` 都会在建连/下单前失败关闭。换成期货公司的账号将来可以复用策略逻辑和 CTP 抽象，
但不能复用 SimNow 的账号、state、evidence、approval key 或 receipt，也不能把“改几个环境变量”
视为生产准入。

未来生产实现至少需要单独评审并验收：期货公司签发的 TD/MD front、broker/native 身份，独立的
账户风险上限和 durable journal，生产专用 approval trust root，以及预检、恢复和两轮对账。
在这些实现和证据存在之前，请只按本 README 的 SimNow pilot 流程操作。

## 快速运行

所有 Python 命令使用 Anaconda base 环境：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py --mode replay --scenario no_signal \
  --output-dir /tmp/iter22-sa-replay
```

Windows PowerShell（从仓库根目录；若 `python` 不在当前环境中，将它替换为
`conda run -n base python`）：

```powershell
Set-Location D:\source_code\backtrader
python .\examples\013_3_sa_midfreq_simnow\run.py --mode replay --scenario no_signal `
  --output-dir .\examples\013_3_sa_midfreq_simnow\reports\local-replay
```

replay 使用 `fixtures/sa_v0_replay.json`，经过真实 `BtApiFeed` 的 tick 到一分钟 bar
聚合和 `Cerebro` 策略回调。`execution_basis=none`、`hypothetical_fills=false`、
`pnl_fields_emitted=false`；`trend`/`reverse` 场景也保持零订单。

网络运行前，在本目录创建忽略版本控制的 `.env` 并填写本地值。runner 优先读取
`CTP_*`，也兼容 `SIMNOW_*` 和仓库已有的小写 `simnow_*`；任何日志、报告和 manifest
都不得保存原值，只保存 `acct_<sha256(broker:investor)[:16]>`。`.env` 中的
`ITER22_SIMNOW_PROFILE=simnow_first_group1` 是默认选择，适用于期货实际交易时段的第一套
观察/预检。允许的值只有冻结 profile 名：`simnow_first_group1`、
`simnow_first_group2`、`simnow_second_7x24`。进程环境中的同名变量优先于 `.env`，因此可在
不改动本地文件的前提下临时选择第二套。profile 选择进入有效 config，进而绑定 manifest、
config hash、身份校验和 Store 运行时；不能用任意前置地址替代它。若仍设置
`CTP_TD_FRONT`/`CTP_MD_FRONT`，二者必须同时存在、精确匹配冻结 pair，并且与所选 profile
相同。

在 Windows 上建立或检查本地 SimNow 凭据时，先只复制公开默认值模板；随后用自己的 SimNow
投资者号和密码替换两个占位符。不要覆盖已有 `.env`，也不要把期货公司生产字段填入此文件：

```powershell
Set-Location D:\source_code\backtrader
$envFile = '.\examples\013_3_sa_midfreq_simnow\.env'
if (-not (Test-Path -LiteralPath $envFile)) {
  Copy-Item '.\examples\013_3_sa_midfreq_simnow\.env.example' $envFile
}
notepad $envFile
```

填写后应只看到以下含义明确的值：`CTP_BROKER_ID=9999`、公开的 AppID/AuthCode、自己的
`CTP_USER_ID`/`CTP_PASSWORD`，以及 `ITER22_SIMNOW_PROFILE=simnow_first_group1`。approval
key 保持空白，直到外部研究和证据审查真正签发 receipt；它不是为了让普通 shadow 命令“能下单”而
设置的开关。

### Pilot 前置检查与首个受控会话

先运行 `operator_readiness.py`。它只读取本地 config/`.env`，不会导入 CTP SDK、建连、发起网络
请求或暴露凭据值；`--strict` 仅表示“静态 SimNow 配置齐备”，从不表示策略已获交易准入：

```powershell
Set-Location D:\source_code\backtrader
python .\examples\013_3_sa_midfreq_simnow\operator_readiness.py `
  --output .\examples\013_3_sa_midfreq_simnow\reports\operator-readiness.json --strict
```

当前 checkout 预计会以退出码 `2` 报出 `simnow_credentials_missing` 和/或
`calendar_artifact_unavailable`；这是有用的本地前置清单，不是程序故障。修正后再运行一次，直到
`simnow_static.ready=true`。报告中的 `simnow_natural_signal.ready` 将始终为 `false`，因为离线工具
不能替代 live G1/G2/G3、账户绑定和签名 receipt 的验收。

静态检查通过后，按顺序执行以下受控步骤，并为每一步使用新的输出目录：

```powershell
# 1. 第一套、只读预检；不设置 --run-seconds，不确认结算，不写订单。
python .\examples\013_3_sa_midfreq_simnow\run.py --mode shadow --purpose observation `
  --preflight-only --output-dir .\examples\013_3_sa_midfreq_simnow\reports\preflight-YYYYMMDD

# 2. 仅在第一套实际交易时段运行有界 shadow 观察。
# 3600 秒只是观察目标的最短有效时长；预留 drain 时间并检查最终报告，而非把退出码当作 G3/G4 通过。
python .\examples\013_3_sa_midfreq_simnow\run.py --mode shadow --purpose observation `
  --run-seconds 3900 --output-dir .\examples\013_3_sa_midfreq_simnow\reports\shadow-YYYYMMDD
```

第二步只能在最终 `daily_report.json`、`manifest.json` 和相关证据均完整时，才可能形成 G3 的一部分；
没有一个固定时长本身会自动产生交易或 G4。收到 `MANUAL_INTERVENTION`、恢复类状态或非零退出码时，
停止重启并按本 README 的“启动恢复与人工接管”处理。

### 长时间运行的 supervisor 约束

`pilot_supervisor.py` 用于把长期试运行拆成一系列**有界会话**，而不是让一个无限制的 CTP 子进程
在无人检查的情况下永久运行。其默认行为是 dry-run：只解析计划和本地前置，不会启动 runner。先查看
当前版本支持的参数和 dry-run 输出：

```powershell
python .\examples\013_3_sa_midfreq_simnow\pilot_supervisor.py --help
```

supervisor 只能编排第一套 SimNow profile 的会话；每一段都必须独立落盘 output、检查退出码和最终
报告，并在非成功、恢复、身份变化、证据不完整或手工接管时停止后续段。它不会把第二套 7×24
工程观察升级为交易，也不会重试未知订单结果。

任何可能写入订单的子会话都必须显式给出 `--mode simnow`、`--purpose natural_signal` 和
`--admission-receipt`，并仍由 runner 重新校验 receipt、账户、TradingDay、connection generation
和运行时证据；默认计划、shadow 或缺少其中任一条件时保持只读。生产 CTP 不属于 supervisor 的可选
目标，当前仍按上一节失败关闭。

### 审批收据：仅在真实验收完成后使用

`admission_receipt_tool.py` 是离线的两阶段审批文件工具，不是把策略切换成可下单状态的开关：先用
完整、非秘密的运行时事实生成待审核 request，只有审核方在**已有**的进程级
`ITER22_APPROVAL_KEY_ID` / `ITER22_APPROVAL_HMAC_KEY` 信任根下显式附加 `--sign`，才会生成 receipt。
它不读取 `.env`、不创建 CTP/Store、不联网、不生成密钥，也不会把任何凭据写入 request 或 receipt。

每次生成或签发都会重新验证本地 hash 绑定的交易日历、当前源码/依赖/config、账户/TradingDay/
connection generation、G1/G2/G3 事实和研究状态；`natural_signal` 仅接受
`RESEARCH_ADMITTED`，收据必须已经生效、未过期，且整个有效期最多两小时。最终文件还会先由
`run.py` 验签，验证失败绝不发布。因此当前候选的 `RESEARCH_NOT_ESTABLISHED` 状态下不能、也不应
创建自然信号的收据。接口说明可离线查看：

```powershell
python .\examples\013_3_sa_midfreq_simnow\admission_receipt_tool.py --help
```

只有在独立研究准入、当日 G1/G2/G3 证据和指定审核人都已完成后，才由负责审批的人准备事实文件并
执行该流程；不要把 approval key 写入 `.env` 或提交到仓库。

第二套 API 连通性诊断（以冻结候选的产品/交易所作有界参考数据查询；不选择具体 SA 合约、不订阅行情、不运行策略）：

```bash
ITER22_SIMNOW_PROFILE=simnow_second_7x24 \
  /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py --mode shadow --purpose observation --api-diagnostic \
  --output-dir /tmp/iter22-sa-set2-api
```

该动作只启动由 `BtApiStore` 托管的 `market_data_only` 会话，并执行公开的 account、positions、
orders、trades 完整查询；instruments 查询以冻结候选的产品和交易所作为有界参考数据范围，避免
未限定的全市场查询。它要求 `auto_settlement_confirm=false`、完整且一致的
账户/TradingDay/generation/profile 身份，以及零 `settlement_confirm`、`order_insert`、
`order_action` 计数；不调用结算预检、结算确认、订阅、报单或撤单。
`api_diagnostic.json` 只保存会话/查询元数据、记录数和 hash，不保存账户记录或凭据。成功为
`PASS_API_DIAGNOSTIC`，同时固定 `strategy_status=NOT_RUN`、G3/G4 为
`NOT_RUN_API_DIAGNOSTIC`：它证明的是 API/session/query 路径，不是行情、信号、下单、成交或
策略成功。

第二套受限策略工程观察（仅检查策略/Feed/Cerebro 在 live Set-2 行情下的逻辑与受控停止；不产生
G3/G4、成交或 PnL 证据）：

```bash
ITER22_SIMNOW_PROFILE=simnow_second_7x24 \
  /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py \
  --config /absolute/path/current-session-manual-SA610.yaml \
  --mode shadow --purpose observation --engineering-strategy-observation \
  --run-seconds 3600 --output-dir /tmp/iter22-sa-set2-engineering-observation
```

该 config 必须是本次 session 新鲜、哈希绑定的手工冻结合约配置；命令不能附加
`--preflight-only`、`--prepare-settlement` 或 `--admission-receipt`。运行仍以同一 Store/Feed/
Cerebro 路径执行只读查询、选择、订阅和策略回调，但不会 arm SDK，也不能提交订单、撤单或结算确认。
受控停机只有同时满足 `OBSERVATION_ONLY`、`market_data_only=true`、Store 停止健康通过、无本地
订单/持仓/撤单/平仓请求且三类 SDK 写请求计数为零时，才给出
`PASS_ENGINEERING_STRATEGY_OBSERVATION`；否则是
`INCOMPLETE_ENGINEERING_STRATEGY_OBSERVATION`（CLI 退出码 4）。证据封存若将 manifest
降级为 `FAIL_EVIDENCE_INCOMPLETE`，CLI 同样返回退出码 4，绝不沿用封存前的成功状态。两种结果都保留
`g3_gate_status=NOT_RUN_ENGINEERING_STRATEGY_OBSERVATION`、`g4_gate_status=NOT_RUN`，不声称
远端账户归零、真实市场时段观察或交易准入。

只读预检：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py --mode shadow --preflight-only \
  --purpose observation --output-dir /tmp/iter22-sa-preflight
```

SimNow 当日首次准备结算状态是独立动作，不能与 preflight 或 receipt 混用：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py --mode simnow --prepare-settlement \
  --purpose observation --output-dir /tmp/iter22-sa-settlement
```

后续进程仍以 `auto_settlement_confirm=false` 登录，并通过公共
`verify_ctp_settlement()` 只读回查当前账户、TradingDay 和 connection generation。
第一套已有一次显式确认和同会话回查成功记录；每个策略运行仍必须自行生成并绑定其新鲜证据，不能复用该机械验证代替 G3/G4。
完整 SimNow 运行还必须提供与候选、config hash、code hash、profile、月份、用途和
G1/G2/G3 绑定的 receipt：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py --mode simnow \
  --purpose engineering_smoke --max-smoke-entry-attempts 1 \
  --admission-receipt /absolute/path/admission.json --run-seconds 900 \
  --output-dir /tmp/iter22-sa-smoke
```

`engineering_smoke` 的跨进程、全账户、同 TradingDay 入场尝试总数最多为 2，并继续
受 receipt 剩余额度限制。`natural_signal` receipt 还必须含 64 位
`signal_preregistration_sha256`。停止成功只写 `COMPLETE_STOPPED_FLAT`；只有实际至少
一次 open→close 且完成两轮不同 request ID、同账户/TradingDay/generation、结果一致的
对账，`g4_gate_status` 才能为 `PASS`。零成交运行是 `INCOMPLETE`，不能冒充 G4。

## 启动恢复与人工接管

如果 SDK 的持久化执行日志显示当前账户、TradingDay 和合约仍有未决订单、未知结果或
本策略持仓，runner 不进入普通 G4 交易。它只执行 SDK 给出的恢复动作：先撤销可证明属于
该 execution cycle 的订单，或至多提交一次与今昨仓语义一致的 1 手平仓。恢复权限是一次性
token；任何发送失败、超时、身份变化或新私有回报都会撤销权限并恢复只读状态。

自动恢复不能证明完成时，Store 和账户级 writer lock 会继续存活，进程每 250ms 轮询一次
只读恢复计划，并持续写入 `execution_recovery.json`。此阶段不会自动重复下单。只有 SDK 返回
两轮独立、同代际的 FLAT 查询并成功消费 completion token，进程才以退出码 0 和
`RECOVERY_STOPPED_FLAT` 结束。

需要由人工系统接管时，在本次输出目录写入 `operator_takeover.json`。文件必须恰好包含以下
字段：`schema_version`、`action`、`approval_key_id`、`run_id`、
`account_fingerprint`、`trading_day`、`instrument`、
`recovery_evidence_sha256`、`acknowledged_at_utc`、`signature_hmac_sha256`。
其中 schema 为 `backtrader.ctp.operator-takeover.v1`，action 为
`takeover_execution_recovery`；身份字段必须匹配当前 run，证据 hash 必须匹配当前恢复计划。
签名使用 `ITER22_APPROVAL_HMAC_KEY` 对除签名字段外的排序紧凑 JSON 做 HMAC-SHA256，
`approval_key_id` 必须等于 `ITER22_APPROVAL_KEY_ID`。验证通过只证明责任已交接，不证明
账户归零或 G4 通过；进程以退出码 3 和 `RECOVERY_OPERATOR_TAKEOVER` 结束。

SIGINT/SIGTERM 也会先落盘最终恢复证据，再以退出码 3 和
`RECOVERY_FORCED_TERMINATION` 结束。其它 `MANUAL_INTERVENTION` 同样返回 3，便于 CI 和
运维系统把它识别为需要处理的非成功终态。

macOS arm64 随包 CTP framework 的 shutdown 在 native `Join()` 仍存活时先解绑回调并保留 native、SWIG director 和 Join 生命周期到进程退出，避免 `Release()` 竞争。受控会话已能以退出码 0 结束；这只是 native 生命周期安全证据，不表示策略停止、账户归零或 G4 通过。

## 合约冻结与当前阻断

CTP `InstrumentField` 提供 `ExpireDate`，但不提供“剩余交易日”或上一完整 TradingDay
全市场 OI/Volume 排名。runner 不用自然日、工作日或当日累计行情代替这些证据。
历史上（2026-09-10）第一套 `shadow --preflight-only` 在会话和受控查询完成后明确返回
`BLOCKED_CTP_TRADING_CALENDAR`，不会静默降级到手工月份。2026-09-12（迭代26 T2）已把
受控日历 artifact 的路径和预期 hash 接线进 `config.yaml`；但 artifact 本身是忽略的本地
证据文件，本 checkout 当前没有它，因此门禁仍处于 fail-closed 状态。日历补齐后，如仍缺上一完整
TradingDay 的全市场排名证据，自动选择将继续以
`BLOCKED_CTP_PRIOR_DAY_RANKING_EVIDENCE` 失败关闭。

配置当前期望 `state/iter22-czce-2026-calendar-20260910.json` 的 SHA-256 为
`2b5168ef5b1f92290879dc5d8d3f1c16eefd823d9441d130d284263a34b46dc7`；该值不是让操作者
伪造历史 artifact 的指令。应提供适用于本次 TradingDay 的权威日历，并同时更新审核过的 config
和 hash。自动选择要求日历覆盖**每一个** eligible SA 的到期日；若当期 eligible 集合延伸到日历
覆盖范围外，必须继续以 `BLOCKED_CTP_TRADING_CALENDAR` 失败关闭。已覆盖的手工目标也必须按当前
CTP `TradingDay` 重新计算并冻结 `manual_trading_days_to_expiry`、来源和审阅时间；旧手工配置的
数值不能因合约相同而直接复用。该手工例外不改变第一套 G3/G4 的门禁。

要运行 shadow/G3，可准备一个冻结的 CZCE 交易日历。示例 schema：

```json
{
  "schema_version": "iter22.czce-trading-calendar.v1",
  "exchange": "CZCE",
  "source": "authoritative-source-and-version",
  "as_of_utc": "2026-09-09T00:00:00Z",
  "trading_days": ["20260909", "20260910", "20260911", "20260914"]
}
```

计算文件 SHA-256：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -c \
  'import hashlib,pathlib; p=pathlib.Path("/absolute/path/czce-calendar.json"); print(hashlib.sha256(p.read_bytes()).hexdigest())'
```

Windows PowerShell：

```powershell
python -c "import hashlib,pathlib; p=pathlib.Path(r'C:\absolute\path\czce-calendar.json'); print(hashlib.sha256(p.read_bytes()).hexdigest())"
```

把 artifact 的相对或绝对路径及 hash 写入 `trading_calendar`，然后显式冻结月份：

```yaml
instrument: "<approved-actual-SA-instrument>"
contract_selection:
  mode: manual
  product: SA
  exchange: CZCE
  minimum_trading_days_to_expiry: 5
  manual_reviewed_at: "2026-09-09T08:00:00+08:00"
  manual_source: "operator-review-ticket-123"
  manual_trading_days_to_expiry: 42
  manual_trading_days_source: "authoritative-source-and-version"
  manual_trading_days_evidence_sha256: "<calendar sha256>"
trading_calendar:
  artifact: "/absolute/path/czce-calendar.json"
  sha256: "<calendar sha256>"
```

`manual_trading_days_to_expiry` 不是自由声明值。runner 从 CTP session `TradingDay` 开始，
用冻结日历数到该 `InstrumentField.ExpireDate`，并要求计算值、source、hash 与 config 完全
一致。夜盘仍以 CTP TradingDay 为基准。Stage A 以产品和交易所范围查询合约，并以交易所范围
查询成交后验证响应未越界；它要求完整 account/positions/orders/trades/instruments 查询。
Stage B 对冻结月份的成交查询同时限定合约和交易所、验证响应范围，再查询费用和保证金，并拒绝
两个阶段之间任何账户、TradingDay、generation 或 metadata 变化。涨跌停只接受本 generation、
本 TradingDay 的有效 `ctp.quote.v2` 行情，不能从静态合约或费用查询伪造。

## 冻结策略规则

- 一档行情必须声明 `schema_version=ctp.quote.v2`、`volume_semantics=delta`，并有完整
  wall event time、monotonic receive time、ingest sequence、TradingDay、ActionDay、
  generation、累计/增量成交量、上下限价和质量字段。
- `I=(bid_size-ask_size)/(bid_size+ask_size)`，按真实持续时间计算 5 秒均值；
  `micro=(ask*bid_size+bid*ask_size)/(bid_size+ask_size)`；OFI 使用相邻一档价格/数量
  变化并在 5 秒求和；15 秒 mid momentum、60 秒价格波动和 1 秒收益均要求有效锚点。
- 分钟层使用 Backtrader 原生 EMA(5)、EMA(20)、ATR(14)。1/3/5 分钟收益只用连续、
  已完成、已到 `available_at` 的 bar；量比只用同 TradingDay 的前 20 个有效分钟。
- 融合权重固定在 `config.yaml`。费用来自账户级完整 commission query；保证金来自
  独立完整 margin query。预期波动必须严格大于 spread、双边滑点、开平费用和
  1 tick buffer 的总和。
- 开仓前预热 60 个合格完成 bar 和 60 秒合格盘口；同一 bar 需方向连续 2 秒且至少
  3 个新 quote，任何不合格 quote、bar 切换或方向变化都会重置。
- 仅限价 GFD、1 手、最大潜在敞口 1 手。3 秒未终态请求撤单，撤单 5 秒无终态进入
  `UNKNOWN`；普通退出不得早于保守 fill 上界后 60 秒，强制退出不得晚于 fill 下界后
  900 秒。idle 回调继续推进超时、session end、断流退出和对账。
- 日损为 `min(500 CNY, starting_equity*0.5%)`。风险文件把累计 gross 和 fee 分开，
  admission 只计算 `gross-fee+unrealized`；净亏损连续 3 笔停止开仓。新 TradingDay 必须
  绑定完整对账后才能建立新基线。
- 风险文件写失败后永久停止开仓。已有仓位或开仓挂单仍可依赖 SDK durable intent，
  以进程内、按动作一次的 emergency token 尝试减仓/撤单；残余 token 和失败原因写入
  report，不能把本地文件失败当作放弃退出的理由。

## 证据与验收

每次运行目录固定包含 `manifest.json`、`preflight.json`、
`startup_account_observation.json`、`contract_selection.json`、`reconciliation.json`、`daily_report.json`、
`retention.json`，并按实际事件
产生 `quotes/bars/signals/orders/trades/risk_events.jsonl`。行情、bar、signal 走有界
异步队列；订单、成交、风控同步 fsync。队列满、磁盘低水位、写失败、轮转超限或
有界 drain 失败都会锁存 `FAIL_EVIDENCE_INCOMPLETE`，停止开仓且不会被最终状态覆盖。
manifest 绑定本示例源码、fixture/config、实际导入的 backtrader/bt_api_py 路径、版本和
文件 hash；网络模式还绑定 bt_api_ctp package/native 文件身份。证据只保留账户指纹。

每一次网络预检都会从 Stage-B 完整 CTP 查询生成
`startup_account_observation.json`：它是账户范围的只读权威启动快照，包含非零持仓记录数、总手数、
活动委托数及每条非零持仓的合约/方向/冻结量，不保存原始账户、订单或凭据。完整 `shadow` 运行还会在
`trade-logger/startup_cached_positions.yaml` 留下一份通用 TradeLogger 缓存快照。后者用于运行时报告，
带 `broker_local_cached_report_state` 和 `unmarked` 标记；它不触发新的账户查询，且其订阅范围可能小于
账户范围，因此不能取代前者。为保留完整启动证据，该 YAML 和 TradeLogger 的实时/最终报告还会以
`startup_account_observation` 的独立、只读 `authoritative_startup_account_observation` 作用域嵌入
同一份预检投影；缓存的 `positions`、`portfolio` 与 `position_entry_count` 仍只表示 broker 本地缓存。

runner 同时以 `obsname="trade_logger"` 挂载通用 `bt.observers.TradeLogger`。它可在运行中
通过 `snapshot()` 返回内存中的订单、成交、持仓、资金和事件计数，并在策略 `stop()` 后通过
`final_report()` 冻结最终快照。SA 策略启动时即可把状态机、受控 CTP 会话、对账和 G3/G4 所需字段
写入 `extensions.sa_midfreq`；首个完成 bar 之前持仓缓存会明确标为不完整。状态转换、完成 bar、订单
或成交会立即更新，连续有效报价每 128 条至多更新一次。报告上下文只读取 broker 的
`get_cached_report_state()` 本地缓存，不会因生成快照刷新账户或持仓。发布被拒绝或抛出异常时，会以
不含异常正文的受控诊断写入 `risk_events.jsonl`，后续重试仍按最近一次尝试的报价水位节流；若停止时
最后成功快照之后仍有发布失败，或扩展缺失，runner 失败关闭，而不会导出陈旧或不完整验收结果。
影子模式若检测到账户既有仓位或挂单，只记录并以 `OBSERVATION_ONLY_NONFLAT` 停止；不会撤单、平仓或
启动恢复流程。影子会话也不进行最终账户归零核验，因此所有 Shadow 停机均记为
`OBSERVATION_STOPPED`，不声明 `STOPPED_FLAT`。这样的运行不构成 G3/G4 通过。`EvidenceWriter`
仍是高频审计证据和 fsync 失败关闭的唯一权威来源，TradeLogger 不替代它。

默认报告根目录按 manifest 中冻结的 TradingDay 管理。每个网络运行只接受一个
TradingDay，因此该运行内的 `quotes.jsonl` 是单 TradingDay 分片。保留策略保留最新
20 个不同 TradingDay。超过窗口也不会自动删除：旧运行必须先有
`retention-release.json`，其 `run_id` 和最终 `manifest.json` SHA-256 必须一致，并记录
带时区的 `released_at_utc`、`released_by` 和 `reason`。研究或验收引用可写
`evidence-protection.json`：

```json
{
  "schema_version": "iter22.retention-release.v1",
  "run_id": "<manifest run_id>",
  "manifest_sha256": "<final manifest sha256>",
  "released_at_utc": "2026-09-09T00:00:00Z",
  "released_by": "<reviewer identity>",
  "reason": "<explicit release reason>"
}
```

保护模板：

```json
{
  "schema_version": "iter22.evidence-protection.v1",
  "run_id": "<manifest run_id>",
  "kind": "acceptance",
  "reference_sha256": "<64 hex>"
}
```

保护标记优先于释放标记；标记损坏时也按保护处理。每次保护跳过、无释放跳过、计划删除
和已删除结果都会 fsync 到报告根目录的 `retention_audit.jsonl`。显式 `--output-dir`
不扫描其父目录，retention 状态写为 `NOT_APPLICABLE_EXPLICIT_OUTPUT_DIRECTORY`，避免清理
任意路径。

G3 的 `observation_evidence` 可直接机判：第一套真实时段连续有效观察至少 3600 秒、
合格完成 bar 至少 60、合格盘口窗口至少 60 秒、TradingDay/generation/profile 一致、
以及 settlement/order/cancel/account-change 写计数全为 0。休市、断代和坏数据不计时。

第二套工程策略观察会保留同类行情、选择、预检和终态写计数事实，但其 profile 为
`market_alignment=engineering_only`。因此无论运行多久、获得多少合格 bar 或 quote window，
都只能写 `g3_evaluation=NOT_APPLICABLE_ENGINEERING_ONLY`，不能把这些字段套入上段第一套 G3 判据。

专属回归：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base pytest -q \
  tests/unit/test_ctp_sa_midfreq_example.py
```

这些测试覆盖 AC-01/02、AC-05～17、AC-20～24、AC-27、AC-29 的本地可验证部分。
真实 SimNow 行情、账户费用、结算和成交没有 fixture 替代；只有新生成的网络 evidence
可以把对应项从 `NOT_RUN/BLOCKED` 改为 `PASS`。

## 拆分蓝图（迭代26 T8 登记，不在该迭代执行）

`run.py` 约 6.0k 行、`strategy.py` 约 2.4k 行，单文件已显著影响可审计性。下一个触碰
013_3 的迭代应按以下分层拆分（保持行为与报告 schema 逐字节兼容，拆分前后以
`business_summary_hash` 等价性与专属回归验证）：

1. **装配层**（`run.py` 保留 CLI/argparse/模式解析，目标 <800 行）；
2. **预检层**（profile/环境/账户/结算/合约/日历门 → `preflight.py`）；
3. **arming/授权层**（Stage A/B、ExecutionArmProof、receipt → `arming.py`）；
4. **执行观察层**（60 分钟/60 bar/60 秒观察计数与证据留存 → `observation.py`）；
5. **报告层**（现有 `reporting.py` 继续承接，冻结 schema 不变）；
6. `strategy.py` 按信号（features 已独立）与风控（risk 已独立）进一步收薄，
   领域常量（SA 时段表等）移入配置。

拆分属于结构性改动，必须走迭代22 的候选身份失效纪律（FR-24）：拆分后稳定身份变化，
既有 receipt/proof 失效需重新预检。

## 参数与启动速查

所有可调项都在本目录的 `config.yaml`，加载时进行严格校验；不要把凭据、账户号或手工
修改的交易日历提交到仓库。下表列出当前冻结默认值和它们对策略的作用。

| 配置组 | 关键参数（默认值） | 作用 |
| --- | --- | --- |
| `contract_selection` | `product=SA`、`exchange=CZCE`、`minimum_trading_days_to_expiry=5` | 自动选约必须满足剩余交易日；手工月份还需日期、来源和 SHA-256 证据。 |
| `feed` / `warmup` | 1 分钟、`qcheck=0.20`、60 根 bar、60 秒盘口 | 只在完成 bar 与连续合格盘口均满足后解除预热。 |
| `signal` | 入场/退出分数 `0.35/0.10`、确认 2 秒且至少 3 个 quote | 融合盘口不平衡、micro-price 偏离、OFI 与分钟趋势；权重由 `weights` 固定。 |
| `execution` | 限价 GFD、3 秒入场超时、5 秒撤单超时、保护 1 tick | 控制拟议订单与撤单的时限；不绕过审批或 SDK 执行门。 |
| `risk` | 1 手、最多 1 手、60–900 秒持仓、日损 `min(500 CNY, 0.5% equity)` | 连亏 3 次后冷却 60 秒；普通/应急写入预算为 100/20。 |
| `quality` / `metadata_expectation` | 行情年龄 2 秒、价差最多 2 tick、深度至少 5 手、watermark 500ms | 拒绝陈旧、过宽、浅盘口或与已验证 tick/multiplier 不符的输入。 |

从仓库根目录运行可避免加载过期的已安装包：

```bash
python examples/013_3_sa_midfreq_simnow/run.py --mode replay --scenario no_signal \
  --output-dir examples/013_3_sa_midfreq_simnow/reports/local-replay
```

`trend` 与 `reverse` 仅是冻结 fixture 场景。`shadow --preflight-only` 是只读预检；只有
经过单独审批、receipt 和真实时段资格验证的 `simnow` 入口才可能请求写入。每次运行应保存
`manifest.json`、`daily_report.json`、TradeLogger 输出和配置/组件哈希；`LOCAL_REPLAY_PASS`
仅证明本地回放，不证明实际成交、PnL、经济性或 G3/G4 通过。
