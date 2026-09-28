# CTP I6 一枪式 MD 只读诊断（2026-09-25）

结论：`INCOMPLETE / NO_WRITE / LIVE_NO_GO`。I6 隔离 SDK 制品核验和本地离线测试通过；一次监督的 SimNow MD-only 诊断没有取得可接受的登录、订阅 ACK、匹配 tick 或完整 native 关闭。没有交易或结算写入。本记录不构成 SimNow 只读、production 或 live 验收。

## 离线证据

- I6 隔离 SDK artifact verifier 通过。
- 安装来源核验后的 CTP SDK 焦点测试：`94 passed`。
- 主仓 runtime 单元集：`1269 passed, 24 skipped, 1 warning in 59.84s`，exit 0；命令为 `python -m pytest tests/unit/runtime -q -p no:asyncio`。
- I6 与 artifact-provenance 定向集：`58 passed`。
- supervisor 离线测试：`17 passed`。
- 隔离环境中的合成 SWIG `CThostFtdcRspUserLoginField` 字段 round-trip（BrokerID、UserID、TradingDay）通过；这排除了该合成对象上简单 getter 映射错误，但不能解释真实回调的空 ID。

这些结果来自本地离线或假客户端范围，没有 provider I/O。没有运行或通过完整 SDK 测试套件，也没有完成任何写入验收。

## 监督的 MD-only 观察

诊断使用已 seal 私有配置中的一个候选 pair；本记录不保存候选序号、地址、账号、合约或配置摘要。artifact gate 通过后进入 market-data 阶段，但最终为 `incomplete / market_client_stop_failed`。只观察到一个登录回调，request-ID 关系为零、响应错误代码为零；该 one-shot `ReqUserLogin` 本身使用 request ID 0，因此零关系是预期，不是 request-ID mismatch。SDK 将身份失败分类为 `broker_id_mismatch`。BrokerID 与 UserID getter 的返回形状为空，TradingDay 字段形状有效。空 identity 的 native 来源仍未确定；该分类和 getter 观察不能认定账号或配置错误，也不构成账号就绪证据。

没有订阅 ACK 或匹配 tick。native Join 仍 pending，关闭未获确认。交易和结算写入均为零；登录/关闭不确定后没有尝试其他候选。

## 隔离 loopback teardown probe

使用 exact pinned I6 SDK 在 suspended-child Windows Job 中执行了 teardown-only probe。它只保留一个已保留但未监听的 loopback socket、空身份和 passive SPI；没有登录请求或 CTP front callback，也没有 provider 或账户访问。`stop_and_wait(0.75)` 返回 `client_stop_returned=true`、`join_required=true`、`join_completed=false`、`native_released=false`、`thread_alive=true`、`timed_out=true`、`complete=false`。外层 child process 随后正常退出；进程退出不是 native Join/Release 完成的证据。独立的无害 Job timeout smoke 验证了 Job kill 路径。

这是无 provider、无账户的 pending-Join 观察。probe 没有在 Join 活跃时调用 `Release()`，因此不能证明提前/并发 Release 顺序不安全；它也不是 SDK shutdown 安全性的通过、实盘 readiness 或写入验收。

## 状态边界

这是未注册的一次性只读诊断，不创建运行路由或执行权限。唯一的受保护 CTP 配置仍按共享合同供 SimNow 和未来 CTP production 使用；该诊断没有切换配置或改变其值。生产 runner、production admission、受信 approval verifier、账户/session 证据和 live write gates 均未获验收。默认 live 入口继续 fail closed，保持 `NO_WRITE / LIVE_NO_GO`。
