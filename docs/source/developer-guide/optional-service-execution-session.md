# 可选执行服务运行入口

`ServiceExecutionSession` 将已配置的执行客户端接入普通 bar 模式的 Cerebro。
它在运行线程上注册客户端，随 Broker 轮询维护租约、刷新订单，在退出时先停止
Broker/Store，再关闭客户端 runtime。策略只负责信号和 `notify_order`，无需自行
调用刷新循环。Execution 的订单台账、准入和 provider 派发仍在服务进程中。

## 配置与装配

沿用 SDK 的 `parse_client_config` 和现有 YAML 配置格式。没有配置执行客户端时，
继续使用原有 `cerebro.run()`，不创建本会话。配置错误或服务启动失败应向上报错，
不能通过捕获错误后调用普通 `cerebro.run()` 来回退到直连。

下面是客户端配置示例；部署方必须解析引用、提供 CURVE 密钥和服务身份，并在服务端
授予相应能力。示例没有密钥，也不自动启动服务。

```yaml
config_schema_version: 6
process_role: strategy_client
registration:
  strategy_ref: strategy-s001
clients:
  execution:
    config_schema_version: 1
    settings:
      bindings:
        - mount: broker.orders
          service_id: account-a01
          instance_id: account-execution
          account_ref: account-a01
          scope_ref: s001-orders
          transport_ref: account-zmq
          required: true
        - mount: broker.order_query
          service_id: account-a01
          instance_id: account-execution
          account_ref: account-a01
          scope_ref: s001-order-query
          transport_ref: account-zmq
          required: true
      options:
        request_timeout_ms: 1000
        heartbeat_interval_seconds: 5
communication:
  config_schema_version: 1
  profiles:
    account-zmq:
      backend: zmq
      config_schema_version: 1
      endpoints:
        rpc_connect: tcp://127.0.0.1:7601
      security_profile_ref: account-a01-client
```

`s001-orders` 和 `s001-order-query` 应解析为同一个账户、策略、运行范围的
`WireScope`。本入口需要提交、撤单、查询三个授权操作；缺失或歧义路由在启动 Store
之前被拒绝。服务端需要同时发布 `service.order_entry` 和 `service.order_query`。
配置中的可选遥测绑定可以降级，不改变执行与查询绑定的必需性。

在部署装配代码中使用以下入口。`cerebro` 已有 `BtApiBroker`、数据和策略；
其 Store 尚未启动，也没有绑定其他 managed execution adapter。`identity`、
两个 resolver 和 transport factory 都来自可信部署装配，不能从 YAML 导入任意 Python。

```python
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_runtime import ServiceClientRuntime
from backtrader.stores.service_execution_session import ServiceExecutionSession

runtime = ServiceClientRuntime(
    parse_client_config(raw_client_config),
    identity=identity,
    scope_resolver=scope_resolver,
    peer_resolver=peer_resolver,
    transport_factory=transport_factory,
)
session = ServiceExecutionSession(
    runtime,
    mount="broker.orders",
    scope_ref="s001-orders",
    query_mount="broker.order_query",
    query_scope_ref="s001-order-query",
    refresh_interval_seconds=1.0,
    max_refresh_interval_seconds=30.0,
    limit=32,
)
results = session.run(cerebro, runonce=False, preload=False)
```

本入口独占一个尚未启动的 runtime 的生命周期，单次运行后不复用。其他 facade 若借用此 runtime，
只能在会话运行期间使用；不能交给另一个线程或另一个会话管理。运行多个策略进程时，
每个进程建立自己的客户端会话，服务端继续复用账户连接。本轮入口只装配一个明确的
执行/查询范围，不承担跨账户套利组协调。

订单仍须带既有受管身份元数据，包括稳定的 `managed_intent_id`、`managed_signal_id`、
`managed_instrument`、`managed_position_effect` 和 `managed_metadata_version`。
不能在读取超时后生成新 intent 重下同一业务订单；未知结果须从原台账查询、对账。

## 运行与退出语义

- 续租独立于订单读取退避。每次 Broker 轮询先维护租约，再按调度检查活动订单。
  单轮最多查询 `limit` 次，未变化的结果也占预算；轮转避免尾部订单饥饿。
- 必需租约失效会传播错误并进入清理；不自动 recover 或重放交易。订单读取失败保留
  原业务状态、数量和价格，标注读取不可用，并按既有刷新调度退避。
- 停止轮询后保留 Broker 原有的停止政策；这不新增自动平仓或撤单授权。正常运行
  已经停止 Broker 时，入口不再重复停止；初始化或策略启动异常漏掉停止时，入口兜底。
- runtime 在 Broker/Store 停止处理之后关闭。`runtime.state == "closed"` 只说明
  本地传输已经关闭；应同时检查 `cleanup_failures` 和 `unregister_uncertainties`。
  注销不确定不能宣称服务端注册已经清除，也不能仅按等待时长推定清除。
  `session.cleanup_report` 保留有限的清理事实；关闭失败时保留这些对象和报告，
  不丢弃仍持有资源的对象。原运行异常优先保留；没有原异常时，清理不完整会抛错。
- 本入口不创建维护线程。Feed 和用户回调必须及时让出运行线程；长时间阻塞会影响
  刷新和租约维护。当前没有为一个刷新批次增加总墙钟预算，单次 RPC 受 SDK 超时限制。
- 本轮仅支持普通 bar 模式。`channel` 和优化模式在接管资源前拒绝；需要独立设计它们的
  外部事件循环、并行实例与生命周期，不能把同一会话复制到多个进程。

这不解除 `ServiceReadProxy` 的只读限制。该代理仍需 `market_data_only=True`，
不能与本交易入口混用。本轮没有完成服务账户/行情读取与执行写入的统一交易 Store。

## 验证边界

对应测试为 `tests/unit/stores/test_service_execution_session.py` 和
`tests/unit/stores/test_service_execution_session_local_process.py`。本机进程场景使用
真实 SDK、CURVE、服务宿主、SQLite 和 Cerebro；provider 回报由测试控制端通过公共
台账 API 注入。这是本机生命周期与订单通知证据，不是交易所回调或真实账户验收。
