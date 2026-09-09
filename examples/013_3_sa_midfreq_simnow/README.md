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

当前第一套的受控外部验证已完成认证/登录、显式结算确认及只读回查、产品范围合约查询和深度行情连接。runner 的只读 preflight 已到达 `BLOCKED_CTP_TRADING_CALENDAR`。另一次独立受控 API 验证将一手非市价限价单撤单至 `CANCELED`，零成交且进程退出码为 0。这些都是 `PASS_CONTROLLED_CTP_MECHANICS` 子证据，不构成 G3 的 60 分钟观察，也不构成 G4 的策略开平闭环、归零对账、收益或经济性证据。

第二套 7×24 的受限 `shadow --api-diagnostic` 已实际通过 `PASS_API_DIAGNOSTIC`：五类只读查询完整、三类状态变更请求计数增量为零，且受管 Store 停止健康为 `PASS`。该诊断以冻结候选的产品和交易所仅作为参考数据范围，不选择具体月份合约、不订阅行情、不运行策略；其 `strategy_status=NOT_RUN`，G3/G4 均为 `NOT_RUN_API_DIAGNOSTIC`。

## 模式和写入边界

| 模式/动作 | CTP 会话 | 订单写入 | 成交/PnL | 结算确认 |
| --- | --- | --- | --- | --- |
| `replay` | 不联网，本地 fixture | 禁止 | 不生成 | 不运行 |
| `shadow --preflight-only` | 只读 | 禁止 | 不生成 | 只读核验 |
| `shadow` | 只读观察 | 禁止 | 不生成 | 不确认 |
| `shadow --api-diagnostic` | 第二套 7x24 的托管只读 API 查询 | 禁止 | 不生成 | 不确认 |
| `simnow --preflight-only` | 只读 | 禁止 | 不生成 | 只读核验 |
| `simnow --prepare-settlement` | `market_data_only` | 禁止 | 不生成 | 唯一显式确认动作，随后只读回查 |
| admitted `simnow` | 托管交易会话 | receipt 限定 | 实际回报才记录 | 启动时只读核验 |

`shadow` 和所有 preflight 路径显式设置 `auto_settlement_confirm=false`。只有同时满足
SimNow 模式、非 preflight、非 prepare、且 receipt 已通过校验时，runner 才把
`allow_order_writes` 打开。生产地址、自定义地址、MD/TD 混配、7x24 第二套交易
（只允许形成 API 工程证据）、
缺失费用/保证金/账户身份、成功但空或多行账户查询都会失败关闭。

## 快速运行

所有 Python 命令使用 Anaconda base 环境：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  examples/013_3_sa_midfreq_simnow/run.py --mode replay --scenario no_signal \
  --output-dir /tmp/iter22-sa-replay
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
当前第一套 `shadow --preflight-only` 已在会话和受控查询完成后明确返回
`BLOCKED_CTP_TRADING_CALENDAR`，不会静默降级到手工月份。日历补齐后，如仍缺上一完整
TradingDay 的全市场排名证据，自动选择将继续以 `BLOCKED_CTP_PRIOR_DAY_RANKING_EVIDENCE` 失败关闭。

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
`contract_selection.json`、`reconciliation.json`、`daily_report.json`、
`retention.json`，并按实际事件
产生 `quotes/bars/signals/orders/trades/risk_events.jsonl`。行情、bar、signal 走有界
异步队列；订单、成交、风控同步 fsync。队列满、磁盘低水位、写失败、轮转超限或
有界 drain 失败都会锁存 `FAIL_EVIDENCE_INCOMPLETE`，停止开仓且不会被最终状态覆盖。
manifest 绑定本示例源码、fixture/config、实际导入的 backtrader/bt_api_py 路径、版本和
文件 hash；网络模式还绑定 bt_api_ctp package/native 文件身份。证据只保留账户指纹。

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

专属回归：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base pytest -q \
  tests/unit/test_ctp_sa_midfreq_example.py
```

这些测试覆盖 AC-01/02、AC-05～17、AC-20～24、AC-27、AC-29 的本地可验证部分。
真实 SimNow 行情、账户费用、结算和成交没有 fixture 替代；只有新生成的网络 evidence
可以把对应项从 `NOT_RUN/BLOCKED` 改为 `PASS`。
