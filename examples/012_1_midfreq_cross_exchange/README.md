# 012_1 中低频跨所永续合约套利

本例独立实现 OKX `BTC-USDT-SWAP` 与 Binance `BTCUSDT` 的中低频均值回归策略。
行情和订单只通过 `BtApiStore.getdata()`、`BtApiFeed`、`bt.Strategy.buy/sell` 与
`BtApiBroker` 进入 `bt_api_py` 公共接口；本目录不包含交易所私有请求映射，也不依赖
其他 example。

策略先把两所 L2 盘口按接收时间、时钟域和 sequence 对齐，再以共同 BTC 数量格点计算
多档可执行 VWAP。滚动 median/MAD 模型只用历史样本计算当前偏离。候选必须同时通过
`entry_zscore=3`、3 次持续确认和严格大于 1 bp 的完整往返净边际。成本报告包含四笔
taker fee、退出执行预留、有符号资金费、延迟、失败腿和模型误差预留；entry VWAP 已含
spread 与深度冲击，审计字段不会再次扣费。
`qualification-v3.json` 从旧公开 L2 训练窗口生成，分别绑定 `okx->binance` 和
`binance->okx` 的 rules、risk、basis 定义和统计置信度。它只允许启动当前模型观察，角色是
训练校准，不能替代新的样本外结论或 demo 准入。V3 在运行配置新增动态资金费率 TTL 后
重新绑定了完整配置哈希；alpha 参数、样本和方向模型没有因此重估。
replay、shadow 和 paper 研究在 G5A 账户费率校准前固定使用每笔 6 bps 的
`conservative_bound`；demo 则必须取得可用且未陈旧的账户 `FeeSchedule`。报告逐所记录
`fee_source` 和实际采用的每笔费率。

网络模式的资金费率来自 `BtApiStore` 的独立只读刷新通道。Store 合并重复请求并维护带
TTL 的本地缓存；策略在每次盘口事件、开仓确认和每条腿提交前重新读取两所快照。任一快照
缺失、陈旧、结算时间已过或周期与合约规则不一致时，策略禁止开仓；已有挂单先撤单，已有
确认暴露立即进入 reduce-only 补偿。中低频持仓在不利资金费率即将结算时提前退出。

冻结参数是 120 个样本窗口、`exit_zscore=0.5`、最大持仓 300 秒和 `0.01 BTC` 基础量。
收敛、继续发散、持仓超时、陈旧盘口、保证金或损失门会触发 reduce-only 平仓。逐腿 IOC
只按已确认成交量对冲；拒单或部分成交会把所有已确认暴露有界平掉。无法确定远端状态时
停止新订单并标记 `reconciliation_required`，由 SDK 的持久执行会话完成查询与对账。

运行模式：

```bash
# 六种确定性公式夹具：profitable/loss/no_edge/partial/unknown/gap
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m \
  examples.012_1_midfreq_cross_exchange.run --mode replay --scenario profitable

# 生产公共盘口；shadow 严格不下单、不产生 fill/PnL
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m \
  examples.012_1_midfreq_cross_exchange.run --mode shadow

# 只读 demo 账户预检
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m \
  examples.012_1_midfreq_cross_exchange.run --mode demo --preflight
```

复制本目录 `.env.example` 为被忽略的 `.env` 后，在本地填写两所模拟合约 API 凭据。
`config.yaml` 的 `okx_api_region` 是非敏感站点配置：在 `www.okx.com`/Global 创建的
账户使用 `global`，在 `my.okx.com` 创建的 EEA 账户使用 `eea`，在 `app.okx.com`
创建的 US 账户使用 `us`。SDK 会同时选择并校验对应的 REST、公开 WS、私有 WS 和业务
WS；不接受跨区混搭。`tr` 当前只支持 production，因缺少已验证的 TR demo 端点组而关闭。
源码、配置、manifest、报告与订单记录都不得保存凭据。账户身份、单写者锁、订单 journal
和账户级风险账本由 `bt_api_py` 按 provider、environment 与非秘密 credential fingerprint
统一维护；runner 不生成账户 ID，也不保存 API key。真正的 `demo` 下单还要求
`examples/strategy-candidate-manifest.json` 中唯一候选绑定一份 Ed25519 签名的
`STRATEGY_APPROVED_FOR_DEMO` 收据。运行时只信任版本库中的
`examples/demo-approval-trust-root.pem`，签名私钥不进入源码或运行环境。收据同时绑定候选、
配置、两仓 commit、OOS 数据与报告、G4/G5A 收据和排除 `demo_approval` 指针后的完整
manifest；临时 manifest、普通 SHA 收据、过期或证据不完整的收据都会在构建 store 和任何
订单写入前退出。签名验证依赖 `cryptography`，源码安装可使用
`pip install -e '.[live]'`；依赖缺失时 demo 写路径保持关闭。
账户必须是模拟环境、具有交易权限、使用双向持仓模式，并在开始时无仓位和挂单。
当前冻结候选为 `RESEARCH_REJECTED`：旧 15 分钟公开 L2 训练窗口产生 149,387 个因果
可执行往返评估，在每腿 6 bps、四次 taker 成交的乐观成本屏中，费用后为正的样本为 0；
最佳结果仍为 `-1.14246520` USDT，且尚未加入资金费、网络延迟与失败腿损失。该结果在
训练期已经否决当前参数，因此不消耗 holdout，也禁止 paper-live 和 demo 订单写入。当前
只开放 replay/shadow；只读 `demo --preflight` 只检查平台和账户前置条件，不构成策略准入。

这些 replay 名称只是历史分支标签。replay 不下单、不模拟成交、不计算 PnL，只检查公式和
拒绝分支可复现；`FORMULA_CHECK_PASS` 不是交易链路或盈利验收。shadow、paper 与 demo 结果
也不构成未来盈利保证。网络报告只有在 Store 停机守恒通过后才可为 `SHADOW_PASS`；paper
和 demo 还必须证明账户风险账本、确认成交经济、对账和平仓终态完整。
如以后提出新的经济假设，必须使用新的 candidate ID、重新预注册并保留独立 holdout；不能
通过降低成本或改写当前候选状态恢复准入。

经过 `Cerebro` 的网络运行会挂载命名为 `trade_logger` 的通用
`bt.observers.TradeLogger`。它实时汇总订单、成交、持仓、资金和事件计数，并在停止后冻结
通用报告；本策略只通过 `extensions.cross_venue` 补充模型、逐腿确认成交、资金费、风险和
对账证据。公式 replay 没有 `Cerebro` 生命周期，因此只导出引擎领域 `snapshot()`，不会伪造
Observer 报告。

策略按本地轻量状态签名把 `cross_venue` 扩展发布到运行中的 `TradeLogger.snapshot()`；相同签名的
高频盘口最多每秒刷新一次，因此非签名明细最多约一秒后可见。完整网络报告保留 Observer 的
`run_id`、时间戳和监控遥测，同时提供排除这些易变字段的 `business_summary` 与
`business_summary_hash`，用于确定性公式 replay 的可重复业务核验。若未来 demo 在 Observer 冻结后
才完成远端对账，输出会写入带前后扩展及哈希的 `post_run_reconciliation` 修订证据，不会改写冻结的
`trade_logger.extensions.cross_venue`。
