# CTP 6.7.7 账户快照完整性审计（2026-09-23）

## 结论

仅凭 CTP 6.7.7 客户端 API 与当前 `TraderClient`，可以证明单个请求收到了成功终包；不能独立证明订单、成交、持仓覆盖整个账户，也不能证明三类结果来自同一时点。账户未结单状态应保持 `ACCOUNT_WIDE_OPEN_ORDERS_NOT_PROVEN`；订单、成交、持仓的共同账户快照也未获证明。SimNow adapter 将账户未结单结果固定为 `complete=False` 是正确的 fail-closed 表达；不得因 `bIsLast=True` 或七类查询均 terminal 而改成 `complete=True`。

本次是对本地源码的只读审计，未连接网络或 CTP/SimNow 账户。SDK 证据来自 `D:\bt_api_py` 当前工作树，不是发布制品或真实会话证据。

## 源码证据

| 事实 | 本地证据 | 能证明与不能证明 |
| --- | --- | --- |
| Order/trade/position 查询回调提供 `nRequestID` 和 `bIsLast`；请求通过对应的 `ReqQry*` 方法发起。 | `D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\api\6.7.7\windows\ThostFtdcTraderApi.h:125,128,131,672,675,678`；`D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\api\6.7.7\linux\ThostFtdcTraderApi.h:125,128,131,672,675,678` | 可用于匹配请求并认定 API 报告了终包。接口没有回调总数、页号/游标或共同快照 ID，因而不能发现被服务端省略的记录或验证跨查询原子性。 |
| 查询字段有 BrokerID/InvestorID 及可选合约、交易所、时间或记录 ID 条件，无 UserID、FrontID、SessionID 的分页/遍历字段。 | `D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\api\6.7.7\windows\ThostFtdcUserApiStruct.h:2483,2506,2529`；`D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\api\6.7.7\linux\ThostFtdcUserApiStruct.h:2483,2506,2529`（`CThostFtdcQryOrderField`、`CThostFtdcQryTradeField`、`CThostFtdcQryInvestorPositionField`） | 空的可选筛选表示请求当前登录身份可查询的范围；请求结构自身不能证明 broker/front 对该范围的实际可见性或覆盖边界。 |
| Order 行含 BrokerID、InvestorID、UserID、TradingDay、FrontID、SessionID；trade 行含 BrokerID、InvestorID、UserID、TradingDay。 | `D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\api\6.7.7\windows\ThostFtdcUserApiStruct.h:1456,1950`；`D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\api\6.7.7\linux\ThostFtdcUserApiStruct.h:1456,1950` | 如果返回行包含其他用户/会话身份，客户端可以识别并按未管理订单处理；没有返回行不能证明其他客户端没有订单。 |
| 客户端在发出查询时捕获 request ID、account fingerprint、generation、TradingDay、BrokerID、InvestorID；累计匹配回调至 terminal，拒绝过期 generation 回调并记录迟到回调。 | `D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\client.py:921,948,1759,1765,1771,3689,3758,3853,3948,3971,4006` | 这些是本地查询 lane 的来源、时序及内容完整性记录；它们不是服务端行数或账户范围证明。`QueryResult.complete` 表示观察到成功 terminal callback。 |
| 证书串行绑定七个同一 client/session 的 query result，核对终态、filter、payload digest，并在完成前复查 late callback；证书文档明示不保证七次读取是 atomic snapshot。 | `D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\containers\ctp\ctp_native_query_certificate.py:1,388,474,505,621` | 证书证明受 issuer 绑定的七个请求终态与记录摘要稳定，不证明响应无服务端截断、全账户范围或跨请求共同快照；返回行 scope 字段只在存在时检查。 |
| SimNow SDK adapter 不把 query terminal 提升成账户级完整性。 | `D:\bt_api_py\bt_api_py\ctp_simnow_execution.py:159-184,577-613,615-718` | `account_open_orders_complete` 固定为 false；查询结果固定 `complete=False`；只读 observation 是 `NON_AUTHORIZING`。 |
| Backtrader 执行协议要求外部 native query evidence verifier 证明完整页和完整账户未结单覆盖；本地 lease 不提供全账户 single-writer 权限。 | `backtrader_runtime/ctp_simulation_execution.py:12-24,487-510,1012-1029,1199-1212` | 本地 `complete=True` 不足以准许写入；目前仓内没有可完成这些服务端断言的 native verifier。 |

因此，`bIsLast` 应解释为**一次 CTP 响应流的终止信号**。它不携带独立总数，不能检出“省略记录但仍送 terminal”的服务端响应。七个不同 query 的 terminal flags 也不提供共同 snapshot epoch；查询期间，其他登录用户或服务器事件可能改变账户状态。客户端重复查询或比较本地返回行无法给出有限、可靠的缺失记录证明。

## 写入前所需外部证据

在真实 CTP 写入准入前，必须由 broker/server 或账户级服务提供可信且可验证的覆盖证明，至少绑定：

- 精确的 broker/investor/account、交易日、所选 front、所有相关 user/front/session 或 InvestUnit 范围，以及各 query 的请求筛选；
- orders、trades、positions 的同一服务端 snapshot/version/watermark，或 broker 声明并强制的冻结点；
- 每个数据集的完整覆盖声明及可核对的记录数/页数与规范化 digest（若服务端协议有分页，必须证明所有页连续且完整）；
- 证明有效期及到实际 dispatch 的账户级 single-writer fence/freeze，覆盖其他进程、主机和人工/其他 API 客户端。Backtrader 本地文件 lease 仅保护协作进程，不能替代它。

当前审计未发现 SDK/native CTP 接口提供上述 snapshot token、账户全范围签证或外部 writer fence；不得把本地 `QueryResult.complete`、native certificate SHA256、account fingerprint、七查询成功或单客户端连接锁解释成该 attestation 已存在。若后续 broker 接口提供此能力，应由独立 pinned verifier 验签/认证、绑定上述 scope/snapshot/count/digest 与 freshness，并在 Backtrader `CtpSimulationQueryEvidenceVerifier.verify()` 集成；在此之前 `ACCOUNT_WIDE_OPEN_ORDERS_NOT_PROVEN` / `LIVE_NO_GO` 不变。

## 最低负向测试要求

1. `bIsLast=True` 但无 broker/server 覆盖 attestation 时，账户未结单、成交或持仓证据必须拒绝写入；七个 terminal query 或 certificate digest 单独提供时同样拒绝。
2. 服务器 attestation 的 row count、page coverage、digest、snapshot/version、账户/交易日/front/user/InvestUnit 范围任一缺失或不一致时拒绝；模拟“漏一行但仍 bIsLast”的响应必须由 server count/digest mismatch 捕获。
3. 把不同 snapshot/version 的 order、trade、position 查询拼在一起，或查询中 account/generation/trading day 变化，必须拒绝；终包后的迟到回调和重复/不匹配 request ID/type 也必须拒绝。
4. 返回带有其他 UserID/FrontID/SessionID 的开放委托时必须按未管理敞口阻断；测试不得假定查询只返回本进程下单的委托。
5. 缺少外部 attestation、过期 attestation、server writer fence 失效/丢失、其他进程/主机 writer 未被 fence 覆盖时，native submit dispatch 计数必须保持为 0。

以上是后续 verifier 的负测要求，不表示这些测试已实现或运行。
