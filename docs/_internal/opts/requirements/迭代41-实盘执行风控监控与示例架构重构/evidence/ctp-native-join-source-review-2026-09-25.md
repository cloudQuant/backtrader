# CTP 原生 Join 挂起：源码证据与离线假设（2026-09-25）

状态：`SOURCE_ORDER_CONFIRMED / ROOT_CAUSE_HYPOTHESIS_ONLY / NO_VENDOR_CONTRACT / NO_WRITE`。本记录只检查冻结 I10 SDK 源码、6.7.7 Windows 头文件、现有 fake 测试和已保存的 I6/I7/I11 脱敏证据；没有读取或修改私有配置、one-shot marker，没有访问 provider/network，也没有运行真实诊断。

## 结论边界

已证实的实现顺序是：MD 客户端注册 SPI 和前置后调用 `Init()`，后台线程进入 `Join()`；当 `stop()` 发现 Join 仍活动时，它保留 API/SPI/Join 线程、清空客户端当前引用、调用 `RegisterSpi(None)`，然后返回。只有原来的 `Join()` 正常返回后，回收路径才调用 `Release()`。I11 的 `client_stop_returned=true` 与 `native_join_pending=true` 正是这一实现允许出现的组合：前者表示 Python `stop()` 已返回，后者表示 native `Join()` 仍未返回。

最符合源码与 I6/I11 观察的假设是：`RegisterSpi(None)` 只更改回调注册，并没有给 `Init()` 创建的原生线程一个已证实的退出信号；如果该 API 需要另一个停止动作才能退出，那么“等待 Join 返回后才 Release”的当前顺序可能让 Join 长期挂起。这是机制假设，不是已证明的死锁：现有头文件和观察没有证明只有 `Release()` 才能让线程退出，也没有证明 `Release()` 可在 Join 前或 Join 期间调用。不能据此把 Release 移到 Join 前。

I6 的隔离 no-login loopback teardown 也观察到 Join pending，且没有登录请求、前置回调或 provider 访问。这说明登录身份为空、订阅 ACK 或缺 tick 不是解释 Join 挂起的必要条件。I11 在订阅 ACK 后仍挂起，与生命周期假设相容，但不能单独确认其机制。

## 源码与接口依据

冻结源码来自 `bt_api_ctp` commit `a6253a58b1ebca11f58c8836fbed757d0daf7582`（版本 `2.0.3+iteration41.i10`；冻结 wheel SHA-256 `e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4`）。本机工作目录中的 `D:\bt_api_py` 与 CTP 子模块有未提交改动；以下源码判断以只读检出的 I10 冻结 clone 为准。

- `src/bt_api_ctp/ctp/client.py:3036-3145`：`MdClient.start(block=False)` 依次注册 SPI、注册前置、调用 `Init()`，再启动 Join observer；`_join_native_api()` 在独立 Python 线程同步调用 `api.Join()`（约 `2920-2967`）。
- `src/bt_api_ctp/ctp/client.py:3158-3247`：活动 Join 下，`stop()` 保留 native API/SPI，清除客户端活动引用，尝试 `RegisterSpi(None)` 并返回；该分支没有调用 `ReqUserLogout()` 或 `Release()`。Join 未活动时才同步尝试 `RegisterSpi(None)` 和 `Release()`。
- `src/bt_api_ctp/ctp/client.py:232-280`：retired-session helper 明确只在 Join 返回后释放 API；释放失败时继续保留 session，避免误报关闭完成。
- 冻结 Windows 6.7.7 `ThostFtdcMdApi.h:93-103` 将 `Release` 描述为删除 API 对象、`Init` 描述为启动接口工作、`Join` 描述为等待接口线程结束；`RegisterSpi` 位于约第 129 行，`ReqUserLogout` 位于约第 160 行。头文件没有单独的 `Stop()` 或定时 `Join()` 方法。上述注释没有说明 `RegisterSpi(nullptr)` 是线程退出信号，也没有说明 logout 会结束 API 工作线程。
- 同版本 TD 头文件也把 `Join()` 定义为等待接口线程结束、把 `Release()` 定义为删除对象；其余并发与退出后置条件同样没有写入头文件。

代码注释提到某 macOS framework 上 `Release()` 与活动 Join 并发不安全。这是 SDK 源码中的实现理由，不能替代对 I11 所用 Windows 二进制的版本化厂商合同，也不能推出 Windows 的并发行为。

## 运行观察与 fake 覆盖范围

- [I6 teardown 证据](ctp-i6-md-diagnostic-2026-09-25.md)记录：no-login、未监听的 loopback teardown 中，`client_stop_returned=true`、`join_required=true`、`join_completed=false`、`native_released=false`、`thread_alive=true`。外层进程结束不证明 native Join/Release 完成。
- [I11 MD 证据](ctp-i11-md-diagnostic-2026-09-25.md)记录：订阅 ACK 已观察、tick 和同交易日均未正证，`client_stop_returned=true`、`close_state=native_join_pending`。Job 终止和 Job empty 证明进程树被收拢，不证明 SDK 有序关闭。
- 冻结 I10 `tests/test_ctp_shutdown.py:931-1038` 使用 fake API 的 `allow_join_return` 事件人为控制 `Join()`。测试证明 stop 返回后 receipt 会报告 pending、Join 返回后 Release 才执行一次；它没有模拟或确定真实 6.7.7 API 是什么动作会让原生 Join 返回。I10 五文件 fake suite 的 171 项通过记录见 [I10 wheel 证据](ctp-i10-md-readonly-candidate-2026-09-25.md)，也不能视为 native 生命周期验收。
- [厂商确认草案](../CTP原生关闭厂商确认问题.md)仍为 `NOT_SENT / NO_VENDOR_CONTRACT`。官方公开手册的版本也没有精确映射到 I11 使用的本机二进制，因此不能用它填补 6.7.7 行为缺口。

## 需要供应商按精确版本回答

请分别对 MD、TD 和实际使用的操作系统/ABI/6.7.7 DLL 与 header 指纹确认：

1. `RegisterSpi(nullptr)` 返回时是否只替换 callback pointer，还是也停止、排空或等待 API 工作线程？它能否证明没有 callback 正在执行或之后再开始？
2. `ReqUserLogout` 是否仅注销交易会话，还是会请求 API 工作线程退出？必须等待哪个 logout/disconnect 回调；请求返回、成功响应和线程退出各自有什么证明？
3. 对 `Init()` 后的 API，`Join()` 何时允许正常返回？前置断开、未登录、已登录但未 logout、无行情活动分别有什么合同？
4. `Release()` 是否允许在 Join 尚未启动、正在等待、已返回三种状态下调用？与活动 Join 并发是否安全、有界，并且是否保证唤醒 Join？是否有受支持的有界 stop API？
5. `Release()` 返回是否正式保证所有原生线程与 callback 已停止且不再访问 API/SPI？这个保证是否因 MD/TD、Windows/macOS、发行包或 ABI 不同？

在这些回答与精确二进制对应之前，不能把 logout、SPI detach、Release-before-Join 或 concurrent Release 认作安全的关闭顺序。

## 最小安全 SDK 变更与合成测试

现有 SDK 已把 `stop()` 返回与 native shutdown completion 分开，并由 `stop_and_wait()` 对 Join/Release 作 fail-closed receipt；因此当前没有可由离线证据支持的 native 顺序修复。最小安全变更是继续保留“Join 返回后才 Release”的策略，并把 `stop()` 的契约明确为“取消本地会话、尝试 detach SPI、保留未结束 native session”，让调用者只把 `stop_and_wait()` 的完整 receipt 当作已关闭。此变更不会解决永久 pending Join，但不会制造未经证实的 use-after-free 风险。

若供应商确认某个特定 stop handshake（例如 logout 请求及终态回调）会触发线程退出，再增加一个明确的 `request_native_stop()` 阶段：先阻止新请求，保持 SPI 可接收合同要求的终态回调，核对其 request/session 关联，再等待 Join；只在 Join 返回后 Release。缺回调、错误、超时或 Join pending 均保留 API/SPI 并返回 incomplete。若合同要求 Release 唤醒活动 Join，应先得到对并发安全、对象寿命、唤醒保证和有界性的明确答复，再单独评审该路径。

新增离线 fake 测试应把“已证实的 wrapper 顺序”和“待确认的 native stop 语义”分开：

1. 用 `Init`/`Join`/`RegisterSpi(None)`/`Release` 事件 fake 复现当前合同：Join 等待独立的 `native_exit` 事件，detach 不自动设置该事件。断言 `stop()` 可返回、receipt 是 pending、API/SPI 被保留且 Release 未调用；模拟外部 native exit 后，断言 Join 返回、Release 恰好一次、receipt complete。该测试只验证 wrapper 状态机，不声称模拟真实 CTP。
2. 只有在供应商合同确认后，增加合约模型 fake：模拟指定 stop 请求和精确终态回调触发 `native_exit`，断言 stop 请求发生在 SPI detach 之前，Join 返回后才 Release。另测请求拒绝、错误/缺失 ACK、超时、重复 close 与 Join 仍 pending 都返回 incomplete，且不提前释放。
3. 在没有合同前，不写“Release 解除 Join”或“并发 Release 安全”的 fake 断言；那会把假设固化成伪证据。

本次只完成源码与已有文本证据检查，没有改 SDK，也没有运行测试。

## 同对象 pending-Join 重启栅栏离线候选（2026-09-25 后续）

在独立 CTP SDK worktree `D:\bt_api_py\bt_api\bt_api_ctp-native-join-lifecycle-worktree`，基于 I9 源提交 `19349b8` 的候选 `abb6cf00ba49db8853b1e0f39a9dfa9d67b126ed` 为 MdClient 和 TraderClient 加了一个局部防护：旧 API 的 `Join()` 未返回且其 `Release()` 尚未尝试完成时，记录 retired API identity，拒绝同一个 client 对象再次 `start()`，不进入新的 native API factory。`Join()` 返回后按原顺序移除 retired session、尝试 Release、再清除该 identity；Join 抛错则保留 pending/retired 状态，fail closed。

源码与关闭 fake suite `31 passed`，Ruff、格式和 diff 检查通过。独立 reviewer 核对了 MD/Trader 两条时序，定向 `test_ctp_shutdown.py` 为 `19 passed`，未发现 P1/P2；新增 fake 证明 pending 时同对象重启被拒、Join/Release 完成后可重试。候选未构建新 native wheel、未进入主仓 pin 或默认 route，也未使用真实 provider、私有配置或 marker。

这项修复只防止**同一个对象**重复积累 pending 原生会话。它不能让 vendor `Join()` 返回，不能覆盖创建新 client 对象或跨进程/主机的重复连接，也不证明原生有序关闭。上文厂商确认和真实受监督 Join/Release 验收仍为阻断门；`NO_WRITE / LIVE_NO_GO` 不变。
