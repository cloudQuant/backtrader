# CTP 期权/期货中频 C/P/F：离线一分钟 FQ2 回放

这是迭代 24 的独立、可直接运行的单策略示例。它仅使用本目录的
`config.yaml`、`run.py`、`fq2_fixture.py`、`features.py`、
`ctp_options_midfreq_strategy.py`、标准库和 `backtrader`/Pandas/YAML；运行时不导入、
不扫描、也不依赖任何其它 `examples/` 目录或 `examples` 公共包。

默认命令从本目录直接运行：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python run.py
```

`fq2_fixture.py` 先明确生成 synthetic clock mapping、三腿 bar seal 和每腿 60
个一秒 quote 状态，策略只消费 barrier 冻结的 `MinuteDecisionInput`。
`features.py` 按 `[T-5s,T)`、`[T-60s,T)` 做时间积分，检查每段不超过 2 秒、三腿
source/receive skew 不超过 500ms，并在第 61 分钟使用此前 60 个有效分钟计算
median/MAD。默认 `no_edge` 序列结果为 `NO_EDGE`；可用 `--scenario edge` 查看
完整 FQ2 特征通过、一次性 token 被当前 `next()` 消费、但仍被 replay 写入禁令
拦下的决策记录：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python run.py --scenario edge
```

`--inject-cutoff-tick` 只用于离线验证：它在回放结束后把一条由 producer 明确携带
bid/ask/量、scope、sequence、wall/monotonic receive 证据的 cutoff tick 交给
`notify_tick`。该回调只能记录特征，不能创建普通决策、改变 60-bar 历史或提交订单；
`--inject-at-cutoff-tick` 验证等于 T 的接收时间会被拒绝。

配置是严格 schema。未知键、非有限数、重复 C/P/F 合约、非 1:1:1 手数、不是一分钟/
60-bar 的参数，以及超过 10,000 元或不满足工作预算与恢复预留关系的配置都会在创建
Cerebro 前拒绝。`shadow`、`simnow` 和 `production` 同样会在配置解析阶段失败关闭；
本目录没有 CTP 客户端、凭据或网络路径。

MF-T1 的本地时序投影可通过真实 Cerebro 的无参 idle 回调运行：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python run.py --timing
```

`execution_timing.py` 只消费显式 synthetic scope、UTC/monotonic mapping 和脱敏的
执行事实快照。单腿、未对冲篮子、撤单和恢复期限分别从持久意图起点计算；普通退出使用
最近完整成交的上界加最短持仓，并由后续合法 minute barrier 决定，最大持仓从最早可能
暴露的下界计算。实际 feed 返回 `None` 时 Cerebro 会调用 `notify_idle()`，该路径只推进
风险投影，不创建普通开仓。缺少 SDK grant、reservation、offset 或真实账户对账时，输出
始终是 `execution_permission=NOT_PROVEN`，零外部请求和零交易写入；此 synthetic replay
不替代 CTP/SDK 执行验收。

`--config` 只能读取本目录内的文件；包含 `..`、符号链接或任何外部绝对路径都会在
构造 Cerebro 前以 `CONFIG_PATH` 拒绝，避免形成对其他示例配置的隐式读取依赖。

JSON 输出明确标出 `external_network_requests=0`、`external_trade_writes=0`、
`actual_order_permission=NOT_PROVEN` 及 `actual_pnl=null`。根目录提供的独立 180 quote
oracle 只用于测试输入与边界对照，策略没有用产品函数倒算 expected。当前 producer
是显式 synthetic replay 输入，不能替代真实 CTP Feed/Store/Broker、期权合约资格、
三腿执行恢复、账户预算、安装包和第一套环境验收；这些边界仍按迭代 24 文档保持
`BLOCKED` 或 `NOT_RUN`。

## SimNow engineering_smoke adapter

`simnow_adapter.py` 是真实 SDK 链路的 fail-closed 装配层：一个
`BtApiStore(provider="btapi")` 产生三个 `BtApiFeed`，同一 Store 产生一个
`BtApiBroker`，再装入同一个 `Cerebro`。它不读取 `.env`，不创建客户端，不启动 Store，
不订阅行情，也不报单。命令行显式调用仍会拒绝，因为本目录不接受隐式 API 注入：

```bash
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python run.py \
  --mode simnow --purpose engineering_smoke
```

受治理的上层 launcher 可以在进程内显式传入已认证 SDK 对象调用
`run_engineering_smoke(..., api=api)`；本 adapter 只记录 transport 提供的 ACK、fill 和
terminal identity，绝不制造成交。三腿必须按确认成交推进；部分成交进入 compensation/
recovery 状态。持久日志为 append-only JSONL。实时 FQ2 只接受带
`event_time`、`recv_monotonic`、`generation`、`subscription_epoch` 且严格早于 bar cutoff
的同 cohort 事件。费用和保证金必须来自完整、身份绑定的外部输入；启动和停机均要求两轮
account-wide reconciliation。任一条件缺失即 `BLOCKED`。

当前验收中 `ITER22_APPROVAL_KEY_ID` 与 `ITER22_APPROVAL_HMAC_KEY` 均缺失，因此本路径
不会解除 `market_data_only`、不会接受空授权、不会生成或写入密钥；执行权限固定为
`NOT_PROVEN`，缺信任根时返回 `TRUST_ROOT_UNAVAILABLE`。
