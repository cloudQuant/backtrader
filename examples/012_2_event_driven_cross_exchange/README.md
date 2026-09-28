# 012_2 盘口事件驱动跨所永续合约套利候选

## 迭代 41 配置入口：LOCAL_REPLAY_ONLY

新入口 `run_runtime.py` 必须读取本目录下 `runtime/config.yaml`（schema v4），仅支持
`simulation/replay`。在仓库根目录、已安装本地 Backtrader/SDK 的环境中依次执行：

```powershell
bt-runtime bootstrap --strategy-dir examples/012_2_event_driven_cross_exchange/runtime
bt-runtime run --strategy-dir examples/012_2_event_driven_cross_exchange/runtime
```

`bootstrap` 只会首次创建 `runtime/config.yaml`，已有文件会以 `CONFIG_EXISTS` 拒绝而不会覆盖。首次建立配置始终使用上述 `bt-runtime bootstrap` 命令，避免从模板手工复制到错误目录；受版本控制的 `runtime/config.example.yaml` 只供审阅，不是运行时回退来源。唯一可选参数是 `parameters.scenario`：
`profitable/loss/no_edge/partial/unknown/gap`，默认 `no_edge`。这些名称仅表示合成公式
分支；报告保留 `R0_FORMULA_FIXTURE`、零订单/成交及无盈利结论，不属于原生执行链验收。

缺配置（`CONFIG_REQUIRED`）、错误 mode/preset、未登记目录及 CLI 模式覆盖会在加载旧策略前拒绝。
复制 runtime 或整个示例目录不会自动取得登记，需部署阶段独立评审中央 inventory。
新入口不读取凭据，不支持 shadow、paper、sandbox 或 live；外部网络和 provider 写入均为零。
原有 tracked `config.yaml` 仍是 hash-bound 研究参数，不再选择执行模式。旧 `run.py` 的
`--mode shadow/demo`、直接导入的 `main()` 和公开 `run_network()` 现已封闭；无参数调用只转发到
已登记的 replay runtime。只读 shadow 暂不可直接运行，恢复前需要独立评审并登记 v4
`simulation/shadow` runtime。

兼容边界：直接执行旧 `run.py` 时，历史参数会在导入策略、Backtrader 和 SDK 前拒绝；通过
Python 导入 `run.py` 仍会在模块加载期间导入 Backtrader 和 SDK，只有调用 `main()`、
`run_network()` 或 `build_store()` 时才由旧入口拒绝。请用 `run_runtime.py` 作为配置优先入口。
下文 `.env`、shadow 和 demo 的操作细节仅记录历史实现，不代表当前可运行入口。

本例独立实现 OKX `BTC-USDT-SWAP` 与 Binance `BTCUSDT` 的 taker-taker IOC 事件策略。
它不继承、不导入其他 example。行情和订单沿
`BtApiStore` / `BtApiFeed` / `BtApiBroker` 进入 `bt_api_py` 公共统一接口。

每个连续 L2 事件都检查 sequence、恢复快照、时钟域、500 ms 陈旧门、250 ms 跨所
skew、共同数量格点和可执行深度。机会必须持续至少 500 ms，且完整往返净边际严格大于
1 bp。配置中的固定 `path_p99_seconds` 仅为兼容和报告字段，不能作为延迟证据。每条可执行
路径必须取得 manifest 绑定、内容寻址的样本外资格模型；模型同时绑定方向、首腿交易所、
实际 taker fee bucket、可执行 depth bucket，以及从 signal 到 hedge terminal 的实测 p99。
缺少任一匹配模型时引擎保持 fail-closed，不生成 `EventIntent`。

500 ms markout 按“方向 + 首腿交易所”分别保存，正值表示机会相对入场时发生不利衰减。
门禁采用上尾 CVaR，而非池化中位数；任一路径样本不足、缺失率超限或上尾损失超限都会
停止开仓。首腿按逐所 ack p99、拒单率和深度动态选择，但只有完整端到端模型的 p99 才能
授权机会寿命。每腿截止 1 秒，整对截止 2.5 秒；所有截止时间使用本机 monotonic 时钟。

基础量冻结为 `0.01 BTC`。首腿只把真实成交量交给第二腿。拒单或部分成交进入有界
reduce-only 补偿；未知执行不会盲目重试，而是冻结并要求 SDK 查询对账。报告包含 gross、
net、逐项成本、drawdown、胜率、expectancy、决策延迟、10/50/100/500 ms markout、
未对冲时长和拒绝原因。
replay、shadow 和 paper 研究在 G5A 前固定使用每笔 6 bps 的 `conservative_bound`；demo
必须取得可用且未陈旧的账户 `FeeSchedule`。每份报告逐所写出 `fee_source` 和采用的费率。
网络模式的资金费率由 `BtApiStore` 在独立只读通道刷新并以 TTL 缓存。策略在每个盘口
事件和每条开仓腿提交前读取两所缓存；缺失、陈旧、过期或周期不一致会阻止首腿，撤销待定
开仓，或立即补偿已经确认的裸腿。资金费率请求不进入订单优先队列，因此不会占用撤单和
平仓的命令容量。

旧 `--mode shadow/demo` 网络命令已关闭。当前只能通过已登记的 v4 replay runtime 运行。
只读 shadow 暂不可直接运行，未来需独立评审并登记 v4 `simulation/shadow` runtime。

## Windows 验收

当前候选为 `RESEARCH_REJECTED`，端到端 HFT 资格是 `FAIL/NOT_ADMITTED`。已登记的 v4
runtime 只开放 `replay`；旧只读 `shadow` 暂停，直到完成独立的 v4 shadow 注册和验收。
`paper-live` 与 demo 下单也没有当前运行入口。

首次在 Windows 上运行：

```powershell
Set-Location D:\bt_api_py
python -m pip install -e .
Set-Location D:\source_code\backtrader
python -m pip install -e .
python scripts/refresh_cross_exchange_local_manifests.py --check
```

确定性 replay 不联网也不交易：

```powershell
bt-runtime run --strategy-dir examples/012_2_event_driven_cross_exchange/runtime
```

shadow 的持续观测步骤当前不可执行。未来恢复时必须由独立评审的 v4
`simulation/shadow` 注册提供配置入口，并验证零订单、零成交、零 PnL 和安全停机。

该策略的决策链是：连续 L2 事件 → sequence/恢复快照/500 ms 陈旧度与 250 ms 跨所 skew 检查
→ 共同数量格点及可执行深度 → 至少 500 ms 的机会寿命 → 四次 taker fee、退出、延迟、失败腿、
模型和资金费预留后的严格净边际 → 必须匹配“方向 + 首腿交易所 + fee/depth bucket + 端到端 p99”
的候选绑定路径模型 → 上尾 CVaR markout 风险门。任何缺失的路径模型都会 fail-closed，不会产生
`EventIntent`；若未来通过独立研究准入，逐腿成交仍只按确认量对冲，超时、部分成交或未知状态均走
reduce-only 补偿和 SDK 对账。

模拟凭据只放在本目录被忽略的 `.env`，变量名见 `.env.example`。
按 `config.yaml` 的非敏感 `okx_api_region` 选择 OKX 站点：`www.okx.com`/Global 用
`global`，`my.okx.com` 用 `eea`，`app.okx.com` 用 `us`。SDK 会原子选择并验证该区域的
REST 与三类 WebSocket；`tr` 因缺少已验证的 demo 端点组，仅允许 production。
`PASS` 候选的 demo 写入必须先通过 canonical 候选 manifest 和固定信任根的 Ed25519 收据校验。
当前 `RESEARCH_REJECTED` 候选只允许显式使用
`--mode demo --allow-rejected-demo-simulation` 进入模拟账户路径；它创建单次本地 lease，数量受
当前 risk 配置约束，运行时长受 `run_timeout_seconds` 约束，最多 8 个订单操作且 lease 最长 900 秒。
此 flag 不改变研究状态、经济筛查、HFT 资格或盈利结论；paper-live 仍被禁止。两所模拟合约账户
仍必须均为双向模式、可交易、初始无仓位和挂单。签名收据绑定候选、配置、两仓 commit、OOS 数据与
报告、G4/G5A 收据和排除 `demo_approval` 指针后的完整 manifest。运行时只加载
`examples/demo-approval-trust-root.pem`，不加载离线私钥；临时 manifest、普通 SHA、过期或
证据不完整的收据在 store 构造前失败。签名依赖通过 `pip install -e '.[live]'` 安装；缺少
`cryptography` 时 `PASS` 候选的签名 demo 路径保持关闭。operator override 不跳过 demo 技术预检、
风险账本、资金费、对账或停机检查。maker-taker 在缺少排队与撤单延迟证据前延期；
lead-lag 未通过预注册 OOS 前不准入。
此外，当前事件驱动候选没有可准入的 candidate-bound event path models；由于研究状态仍为
`RESEARCH_REJECTED`，显式 flag 不会越过该模型门，demo 会在 Store 构造前失败。只有候选重新
达到相应研究准入并绑定通过验证的模型后，才会继续进入该执行路径。
账户身份、订单 journal 与账户级风险账本由 `bt_api_py` 按 provider、environment 和非秘密
credential fingerprint 统一维护，runner 不自行生成账户 ID。当前冻结候选为
`RESEARCH_REJECTED`：旧 15 分钟公开 L2 训练窗口的 149,387 个因果可执行往返评估中，
没有一次在四笔、每笔 6 bps 的 taker 费用后为正，最佳结果仍为 `-1.14246520` USDT。
该乐观屏还未加入资金费、网络延迟和失败腿损失，因此当前假设在训练期已被否决，不消耗
holdout。paper-live 仍被禁止；只读 `demo --preflight` 只验证平台与账户前置条件，不改变研究
结论。operator override 也不改变 `RESEARCH_REJECTED` 或任何盈利结论。

当前候选只命名为“事件驱动”。本地回调基准不能覆盖公网 REST、交易所限频、真实排队位置、
跨所成交不确定性和端到端延迟，因此 HFT 资格门保持 `FAIL/NOT_ADMITTED`。replay 名称只是
历史分支标签；它不下单、不模拟成交、不计算 PnL，`FORMULA_CHECK_PASS` 只表示公式与拒绝
分支符合预期。网络报告只有在 Store 停机守恒通过后才可为 `SHADOW_PASS`；paper/demo 还
必须取得账户风险账本、确认成交经济、对账和平仓终态。paper 或短期 demo 也不证明可持续盈利。

经过 `Cerebro` 的网络运行会挂载命名为 `trade_logger` 的通用
`bt.observers.TradeLogger`。它实时汇总订单、成交、持仓、资金和事件计数，并在停止后冻结
通用报告；本策略只通过 `extensions.cross_venue` 补充路径模型、markout、逐腿确认成交、
风险和对账证据。公式 replay 没有 `Cerebro` 生命周期，因此只导出引擎领域 `snapshot()`，
不会伪造 Observer 报告。

策略按本地轻量状态签名把 `cross_venue` 扩展发布到运行中的 `TradeLogger.snapshot()`；相同签名的
高频盘口最多每秒刷新一次，因此非签名明细最多约一秒后可见。完整网络报告保留 Observer 的
`run_id`、时间戳和监控遥测，同时提供排除这些易变字段的 `business_summary` 与
`business_summary_hash`，用于确定性公式 replay 的可重复业务核验。若未来 demo 在 Observer 冻结后
才完成远端对账，输出会写入带前后扩展及哈希的 `post_run_reconciliation` 修订证据，不会改写冻结的
`trade_logger.extensions.cross_venue`。
