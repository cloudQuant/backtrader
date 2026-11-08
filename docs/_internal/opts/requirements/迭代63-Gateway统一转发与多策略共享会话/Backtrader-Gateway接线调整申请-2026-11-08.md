# Backtrader Gateway 接线的有限架构调整申请

日期：2026-11-08。状态：**待用户确认，未实施 BT 产品修改**。授权依据：用户要求尽可能复用 Backtrader，不允许未经确认调整架构或重构；SDK/Gateway/ZMQ 的调整已授权。本页提供所需 BT 变更的具体范围，避免把远端预留伪装成本地原生订单。既有源码基线为 BT eb7badace、SDK bc87e4ae，静态盘点不构成运行验收。

## 必须解决的现状

- Store 现有写路径要求统一 SDK facade；ServiceReadProxy 是只读接入，Broker 在该模式下只提供 market_data_only。GatewayDirectClient 无法直接替换已有 API。
- _btapi_direct_mode.py 的 _direct_request 仍生成 direct 账户标签及本地 client_order_id，没有 Gateway 所需的完整稳定 request_key；_direct_dispatch 调 make_order 并立即处理 sent/identity。
- live_state PendingCommandStore 的 schema v1 严格限定字段。它允许仅有 client_order_id 的 place，但两种身份都空会拒绝；去重按 route/client id/native fields，简单放宽空身份会碰撞。
- pending.attach 只把原生字段写入 facts，恢复读取顶层 native_identity/client_order_id/session_generation，不能用 attach 冒充原子身份补写。
- _direct_reconcile 中 PREPARED/DISPATCHED 在完整场所查询无匹配时可走 not_found_at_venue；Gateway 尚无原生身份的记录必须先查原 request_key，不能套用此判定。

## 拟请求批准的范围

1. 复用 backtrader/live_state 的既有状态所有权与持久化机制，增加 Gateway 意图和原键恢复索引，保存完整规范请求、可信绑定、远端预留/观察版本、派发标记及 release 计划。以显式 schema 版本和迁移处理旧状态；不删除或静默忽略旧数据。默认优先单一原子记录更新，若具体存储结构必须跨文件，先写明可恢复顺序并覆盖中途崩溃。
2. 扩展 PendingCommandStore 的 Gateway 标记类型，按稳定 request_key 去重，支持原生身份为空的逻辑预留，以及 dispatch 后的原子、单调、幂等身份绑定。重复同值通过，身份/摘要/版本冲突或持久化失败保留待核查，不继续按新身份执行。
3. 在现有 Broker 的 direct 模式实现文件中增加明确 Gateway 提交/恢复分支，调用 SDK reserve→dispatch→status/事件；复用现有 Order、Position、Trade、通知及强身份索引。队列回执不作为 Sent；请求级失败不直接判定原订单 Rejected/NOT_SENT；无原生身份时按原键恢复。
4. 在现有 Store 配置和生命周期接线处显式选择 Gateway 模式、注入 SDK 客户端及可信账户/策略/journal 绑定；使用独立租约 owner 线程。既有只读代理继续只读，普通 direct 保留独立准入；不重新启用被退役的旧 backend 别名。

本申请不改 Cerebro 调度、策略公共生命周期、核心线系统或回测路径，不新建第二套策略调度器；本页不是要求全面重写 Broker/Store。Gateway 服务、凭据和 native 会话继续在独立进程；策略进程不创建它们。

## 数据流示例（候选结构，非已实现 schema）

策略 42 号意图先保存稳定 request_key、完整请求与摘要。Gateway 回 RESERVED/version=1/native_identity=null 后，保存该观察。调用 dispatch 前，BT 宿主为同一意图保存 PREPARED 标记。排队回复或超时不补造原生身份；随后按原键取得可信 DISPATCHING/SENT 等观察，原子绑定实际身份和版本，再建立 BT 索引并消费回报。

崩溃发生在任意一步时恢复原 key；旧 run 仅按授权读取/释放，不自动以新 key 补单。完整同日强身份查询的 D63-38 判定只适用于已经具备所需身份和覆盖依据的分支。

## 验收范围

复用并扩充 tests/unit/live_state/test_pending.py 及 tests/unit/brokers/direct 下提交、重启对账和 not_found 通知测试。新增真实 BT + 本地独立 Gateway + 合成 provider 联调，覆盖两条无原生身份意图不碰撞、reserve/dispatch 丢回复、意图/标记/身份补写失败、各崩溃点恢复、重复和冲突观察、未知恢复和迟到回报。原 direct 路径及框架策略回归须保持通过；真实 CTP/账户另按既定验收授权进行。

批准只允许以上必要接线和持久状态扩展；后续若超出该范围改变 BT 架构，将另行提出具体方案。等待此决定期间继续完成已授权的 SDK/Gateway/CTP 工作。
