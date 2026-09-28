# CTP I4 SimNow 行情只读诊断：真实连接结果（2026-09-25）

结论：`INCOMPLETE / NO_WRITE / LIVE_NO_GO`。两次诊断均使用唯一受保护、Git 忽略的 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`，由代码从其中五组成对候选中做无凭据 TCP 选择；未按 set、时段或环境名选路。每次都重新探测，未证明两次选中相同地址对。I4 只读诊断独立于默认 CLI/runner，不包含 Trader、下单、撤单或结算写入。

## 第二次诊断：已获得固定回调分类

在不更改 SDK wheel、前置列表或账户参数的情况下，主仓只读适配器把 SDK 已有的固定枚举透传到脱敏输出；八类失败类别、字段白名单和外层 supervisor 均经独立复核。完整 `tests/unit/runtime` 为 `1190 passed, 24 skipped, 1 warning`；一次未安装可选 `bt_api_py` 的离线回放先暴露 `find_spec` 父模块缺失异常，随后修复并通过全套复跑。第二次真实诊断记录：

| 观测项 | 结果 |
| --- | --- |
| 本机审计时段 | 2026-09-25 03:21:45–03:22:00（Asia/Singapore），15,139 ms；未超时，子进程退出码 3 |
| SDK 登录回调 | `login_callback_count=1`，`login_callback_disposition=identity_rejected`，`login_failure_category=broker_id_mismatch`，`login_request_id_relation=zero`，`login_response_error_status=zero` |
| 阶段与主状态 | `market_data`，`status=incomplete`，`reason=market_client_stop_failed`，primary reason 仍为适配器的宽泛 `market_login_identity_mismatch`；固定类别更具体，但不包含回调字段原值 |
| 行情/关闭 | `market_login_ready=false`，无订阅 ACK 或匹配 tick；`client_stop_returned=true`，native Join pending，`probe_session_closed=false` |
| 写入边界 | `order_submission_authorized=false`，`trading_writes=0`，`settlement_writes=0` |

这证明所选候选的响应进入了登录回调且 SDK 比较到 BrokerID 不相等；它**不能单独区分**响应 BrokerID 为空、格式转换差异、前置环境与配置 BrokerID 不匹配等根因。一次只输出布尔值的本机配置检查确认，受保护配置的 `ctp.broker_id` 与[SimNow 公开的默认 BrokerID](https://www.simnow.com.cn/product.action)相同；这仍不能证明 TCP 最快的候选前置确属该账号环境。不得按 TCP 可达性在登录失败后自动换下一组前置并重放账号。先审计字段转换与候选同账户范围，再设计不记录账号值的诊断；native Join 仍须独立解决。

## 第一次诊断：尚无固定回调分类

| 观测项 | 本次结果 |
| --- | --- |
| 本机审计时段 | 2026-09-25 02:57:59–02:58:17（Asia/Singapore），18,468 ms |
| 外层保护 | Windows suspended child + Job Object 整树终止，240 秒上限；独立复核通过，五项无网络 fake 测试通过；本次未超时，子进程退出码 3 |
| SDK 来源 | [I4 离线制品证据](ctp-i4-offline-artifact-2026-09-25.md)中的精确源码提交、wheel、RECORD 与隔离 venv pin；默认 I2 注册 route 未变 |
| 行情阶段 | `market_data`，`status=incomplete`，`reason=market_client_stop_failed`，`probe_primary_reason=market_login_identity_mismatch` |
| 登录/订阅/tick | `market_login_ready=false`，`subscription_acknowledged=false`，`matching_tick_observed=false`；当前适配器会把多种登录前错误统称为 `market_login_identity_mismatch`，本次投影没有记录回调分类，不能据此判定 BrokerID、UserID 或交易日哪一项出错，甚至不能断定一定是身份字段 |
| 原生关闭 | `client_stop_returned=true`，但 `native_join_pending=true`、`probe_session_closed=false`、`native_shutdown_uncertain=true`；不能把 Python stop 返回视为完整 native 退出 |
| 写入边界 | `order_submission_authorized=false`，`trading_writes=0`，`settlement_writes=0`；没有报单、撤单或结算验收 |

两次固定字段、脱敏的本机审计收据位于 `D:\c41sdki4_audit\audit\i4-md-diagnostic.jsonl`，受限 DACL，不纳入 Git。外层启动器只保存白名单枚举和布尔量，丢弃原生 stderr 与非白名单 stdout；不记录前置、账号、密码、AuthCode 或合约值。进程正常退出不代表行情观察成功；首次未记录登录前失败细类，第二次记录了 `broker_id_mismatch`，两次原生 Join 均未完成。

关闭路径的只读源码审计发现一个待证实的控制流风险：I4 `MdClient.stop()` 在 Join 活跃时解绑 SPI 并保留 API，`_join_native_api()` 只有等 `Join()` 返回才 `Release()`。如果解绑本身不使线程结束，此流程无法主动打破等待。精确 Windows 6.7.7 header 仅说明 `Release()` 删除 API 对象、`Join()` 等待线程退出，没有规定并发调用或安全关闭次序；[SimNow 官方 Mini API 手册](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf)也没有给出该精确 DLL 的 teardown 合同。因此这仍是源码风险假设，不得盲目在活跃 Join 上并发调用会删除对象的 `Release()`，也不得从外层 Job 强杀推导 managed 会话关闭成功。先做 Release 驱动 Join 返回的离线假 API 反例，再取得厂商或精确 DLL 的安全语义；必要时设计可恢复的进程隔离。

开发下一步审计 `broker_id_mismatch` 的字段转换及各候选前置是否属于同一账户范围，在不记录原值的条件下给出可判定的证据；不得因一次登录失败自动切换到下一组并重放账号。若须修改 SDK，须重新冻结源码和制品 pin。native Join 仍须按上述独立处理。QA 只有在同一 sealed 配置、精确订阅 ACK、匹配 tick、零写入且 Join/Release 完整关闭同时成立时，才能接受行情只读门。TD 七项查询、账户范围、逐笔审批、writer fence、订单/撤单回调与重启恢复仍需各自验收；此证据不开放 SimNow managed 写入或 production live。
