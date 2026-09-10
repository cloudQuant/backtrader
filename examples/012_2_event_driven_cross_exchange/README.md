# 012_2 盘口事件驱动跨所永续合约套利候选

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

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m \
  examples.012_2_event_driven_cross_exchange.run --mode replay --scenario profitable
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m \
  examples.012_2_event_driven_cross_exchange.run --mode shadow
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m \
  examples.012_2_event_driven_cross_exchange.run --mode demo --preflight
```

模拟凭据只放在本目录被忽略的 `.env`，变量名见 `.env.example`。
按 `config.yaml` 的非敏感 `okx_api_region` 选择 OKX 站点：`www.okx.com`/Global 用
`global`，`my.okx.com` 用 `eea`，`app.okx.com` 用 `us`。SDK 会原子选择并验证该区域的
REST 与三类 WebSocket；`tr` 因缺少已验证的 demo 端点组，仅允许 production。
真正的 demo 写入必须先
通过 canonical 候选 manifest 和固定信任根的 Ed25519 收据校验，并要求两所模拟合约账户
均为双向模式、可交易、初始无仓位和挂单。收据绑定候选、配置、两仓 commit、OOS 数据与
报告、G4/G5A 收据和排除 `demo_approval` 指针后的完整 manifest。运行时只加载
`examples/demo-approval-trust-root.pem`，不加载离线私钥；临时 manifest、普通 SHA、过期或
证据不完整的收据在 store 构造前失败。签名依赖通过 `pip install -e '.[live]'` 安装；缺少
`cryptography` 时 demo 写路径保持关闭。maker-taker 在缺少排队与撤单延迟证据前延期；
lead-lag 未通过预注册 OOS 前不准入。
账户身份、订单 journal 与账户级风险账本由 `bt_api_py` 按 provider、environment 和非秘密
credential fingerprint 统一维护，runner 不自行生成账户 ID。当前冻结候选为
`RESEARCH_REJECTED`：旧 15 分钟公开 L2 训练窗口的 149,387 个因果可执行往返评估中，
没有一次在四笔、每笔 6 bps 的 taker 费用后为正，最佳结果仍为 `-1.14246520` USDT。
该乐观屏还未加入资金费、网络延迟和失败腿损失，因此当前假设在训练期已被否决，不消耗
holdout，并禁止 paper-live 和 demo 订单写入。只读 `demo --preflight` 只验证平台与账户
前置条件，不改变研究结论。

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
