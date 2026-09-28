# F14：CTP 账户级快照与跨主机写入排他可行性复核

状态：`EXTERNAL_CONTROL_NOT_VERIFIED / SIMNOW_WRITE_NO_GO / PRODUCTION_LIVE_NO_GO`。本记录是源码和公开接口的只读审计，没有真实账号登录、柜台查询或报单。

## 当前代码能证明什么

| 证据 | 已证明的边界 | 尚不能证明 |
| --- | --- | --- |
| `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/containers/ctp/ctp_native_query_certificate.py` 的 `CtpNativeQueryCertificateBuilder` | 同一客户端、账户、TradingDay、连接代次上的七类请求终包、过滤条件、结果摘要及迟到回调检查 | 七类查询共享一个柜台快照版本、覆盖全账户全部未结单或排斥其他客户端写入 |
| `D:/bt_api_py/bt_api_py/ctp_simnow_execution.py` 的查询适配器 | 明确返回 `UNPROVEN` 覆盖状态，未把单次终包当作全账户完整性；`write_admitted=False` | 可授权模拟盘原生报撤单的完整账户状态 |
| `backtrader_runtime/ctp_simulation_execution.py` 的 writer-fence 与 query-verifier 协议 | 把账户级排他和完整性列为注入式外部前置；本地 lease 仅覆盖自身可控制的进程/目录 | 跨主机、其他用户或外部 CTP 客户端的独占；柜台侧共同快照 |

已核查的 [SimNow CTPIIMini API](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf) 与 [SFIT CTP Mini API](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf) 描述了逐请求查询、请求 ID 和终态回调；**在这些公开接口中未找到**跨七项查询的共同快照版本或账户级跨主机 writer lease。这只是已核查接口范围内的推断，不排除期货公司或柜台另有受信管理服务。

## 开发与 QA 的下一道门

开发负责人先确认期货公司/柜台能否提供服务端账户冻结或独占、账户范围完整性及共同快照版本的可复核接口或证明，并把颁发方、账户与 TradingDay 绑定、覆盖范围、版本/有效期、失效/撤销及异常时冻结规则写入独立合同。不能把本地文件锁、重复读到相同结果、`bIsLast` 或人工口头确认写成等效服务端控制。

独立 QA 取得源系统证据后，再做跨主机/外部客户端竞争、查询中状态变化、断线重连、过期/撤销、漏页/迟到回调及重启恢复负测；核对所有拒绝路径的原生报单、撤单、结算确认计数均为零。若外部控制不可得或证据不能覆盖账户范围，AC41-37 保持 `NOT_RUN` 或符合验收 §5 的有效 `BLOCKED`，不得通过 SimNow 写入门，也不得将其推广到生产实盘。

本记录不签发审批、不证明公开 CTP API 永远不可能实现其他方案，也不改变 `config.yaml` 指定哪对 `md_front`/`td_front` 就只连接哪对的只读路由合同。
