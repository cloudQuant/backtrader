# Iter23/24/25 三腿 SimNow 工程机械验收 launcher

`ctp_options_simnow_live_runner.py` 是一个受治理的、可注入的入口，不是
客户端、策略或成交模拟器。导入它不会读取 `.env`、创建 API、连接账户或
提交订单。

主控必须注入一个已构造的 Store、`BtApiBroker`、三条 feed、owner、完整的
F/C/P instrument metadata，以及 caller 已通过 Store public APIs 收集的、带明确
scope 的 Stage A、exact-future Stage B、`get_ctp_bundle_execution_reference_snapshot`
结果和两轮 raw reconciliation。launcher 不会在 `preflight()` 中重查 Store；可选的
`collect_public_evidence(timeout>0)` 才会按 product/exchange、exact future、bundle
legs 调用这些公开 Store 方法，不访问 `store._api`。预检输入还必须明确标记
`preflight_context.market_data_only=true`、`execution_armed=false`。

默认调用 `launch_three_leg_smoke(..., execute=False)` 只做只读 preflight。preflight
会在 Store 仍 market-data-only/unarmed 时通过 Broker public
`record_ctp_reconciliation`/`get_ctp_reconciliation_state` 归一化两轮 raw 证据；
raw `unmatched_trade_count=null` 只有 Broker 明确返回 two-round PASS 后才成为
派生的 `reconciled` proof，绝不会由 launcher 直接当作 0。成功后 proof 会冻结。

主控随后完成 Store public authorization configure/arm，再完成 `broker.start()`，
并把只含 `store_armed`、`broker_started` 和同一 account/day/generation 的 lifecycle
proof 传给 `execute_preflighted()`（`begin()` 是别名）。该入口不再读取 raw
reconciliation，也不重复 preflight。兼容的 `start(execute=False)` 仍执行 preflight；
`start(execute=True)` 只消费已冻结 proof 和显式 lifecycle proof。

执行前每腿 reference 必须提供同一来源时序的 fresh、正数 Ask/Bid 及对应数量；entry
只接受 `buy@AskPrice1`，exit 必须传入更新时戳的 reference 并只接受 `sell@BidPrice1`。
任意同 tick 但不等于当前 executable quote 的价格都会被拒绝。任意 reject、partial、
timeout、reconnect、unknown 或 late fill 都进入 recovery required；没有 native trade
evidence 不会推进退出。

退出必须由 caller 显式计划，且三条腿的 native fill/cumulative evidence 全部观察到；
最终 raw flat reconciliation 也必须再次经 Broker public normalization，两轮相同 identity
和稳定状态通过后才返回
`MECHANICAL_PASS`。输出只包含脱敏 hash、状态和 Iter25 的固定标签
`HFT_NOT_ADMITTED`，不计算或声称 PnL、收益或 HFT 资格。

HMAC trust root 必须由受控 caller 预先配置；launcher 不生成、读取、记录或输出 secret。
开发测试只使用 fake/injected 对象，永不连接账户。
