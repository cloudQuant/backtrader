# G6-P/F14 外部账户 actor 架构审计

**裁决：** G6-P **F14_STRICT_BLOCKED**，G8-P **NOT_RUN**，**NO_WRITE / LIVE_NO_GO**。这是只读架构审计；未运行测试或导入 SDK/native 模块，未访问账户、凭据、私有配置、provider 或网络。

## 当前旁路路径

1. **Backtrader Store/Broker：** Broker 将 submit/cancel 交给 BtApiStore。Store 未挂 managed adapter 时分别走 legacy submit/cancel；backend=gateway 会创建旧 bt_api_py.gateway.client.GatewayClient。详见 backtrader/stores/btapistore.py:7714-7727, 7991-8013, 16395-16453 和 backtrader/brokers/btapibroker.py:2875, 3103。
2. **旧同进程 gateway：** GatewayClient 默认 gateway_start_local_runtime=True，启动同进程 GatewayRuntime；其 CTP adapter 建立 CTP MD/TD streams 并调用 feed.make_order/feed.cancel_order。这是本地 ZeroMQ 形状的客户端，不是独立凭据 actor。详见本次 raw ZIP 的 old_gateway_client/runtime/ctp_adapter 副本。
3. **SDK direct：** CTP client 仍有 ReqOrderInsert、ReqOrderAction 直调。取得 SDK 和凭据的本地进程可以绕过新 gateway 候选。
4. **新 bt_api_gateway/transport 候选：** 新 GatewayCommandRouter 是通用、可注入的路由器；admission、SQLite writer authority 和 executor 都由构造方接入。它们不是外部 CTP authority。ZMQ Curve/ZAP 加静态 peer ACL 可以认证传输对端和限定静态 scope/kind，但没有账户 epoch、撤销/接管、快照来源或 native 执行边界。Wire sequence 由客户端带入。EventJournal 接受调用方已脱敏事件及快照；游标一致不证明 provider 数据同版本。
5. **MCP：** 当前 MCP 提供策略任务启动/取消工具，不提供下单/撤单工具。其 validator 拒绝已识别的 BtApiStore/provider-store 与受保护 CTP 路径，是候选执行边界的纵深防御，不能证明主机网络出站、凭据或其他进程受到外部隔离。

当前代码的目标不应是向本地命令多加一个 token，而应移除策略进程的 CTP 直连能力。

## 最小目标调用链

Backtrader/MCP 客户端（仅 typed intent，无凭据/native handle）
→ 认证的外部 Account Actor API
→ 服务端持久单次 action claim + 跨主机 epoch + 同 epoch 完整账户快照检查
→ 单账户串行 actor 在同一服务边界完成最后风控/epoch 检查及 native Req
→ 同一 owner 持久化 callback inbox、订单/成交对账和 UNKNOWN/no-resend
→ 向客户端发布只读投影。

Actor 必须是唯一可取用 CTP 凭据并连接写网络的服务身份；OS、凭据库、网络策略必须拒绝旧进程、其他主机、用户、终端和 direct SDK writer。仅本地 SQLite lease、签名 DTO 或本机 assert_active() 后再由客户端 Req，均无法封闭跨主机旁路和撤销竞态。

## 外部事实与可先做的离线工作

F14 仍缺外部服务身份及部署 pin、单调跨主机 epoch/撤销协议、可证明的凭据与 egress 独占，以及与账户/交易日/epoch 绑定的完整共同版本快照。快照至少覆盖资金、全账户未结委托（含外部/人工委托）、成交、持仓、分页完整性和可对账水位。独立 CTP query 的 bIsLast 不能拼成共同 snapshot；provider 无共同版本或可信等价物时，严格 F14 继续阻断。

可先做的本仓离线切片：定义默认 unavailable 的 typed AccountActorPort；CTP/CTP-gateway Store 无 actor 时在构造和每个 legacy/direct fallback 前拒绝；覆盖注入 api/api_cls、SDK mode、旧 gateway 与直接 Req 的零调用负测；补 ZMQ wrong-peer/scope、replay、stale epoch、revocation race、UNKNOWN restart 无重发与不完整/版本不一致快照的 fake 测试。MCP AST/worker 拒绝测试保留为纵深防御。此类 fake 测试不能代替跨主机并发拒绝、网络/凭据边界、provider snapshot 和真实服务 epoch 的独立证据。

## 来源与归档

原始只读审计、源文件 byte hashes、31 份冻结源码/测试副本和包内逐文件 SHA-256 收据见本报告配套 raw ZIP。清单注明了仓库 HEAD 与 dirty/untracked 状态；gateway 和 ZMQ 候选当前不是已发布或受信的外部服务。不得据此报告 G6-P/G8-P 通过。

