# G1 R8 独立审查：Windows inert custodian

日期：2026-09-27  
裁决：**REJECTED / G1 CLOSED**。普通 preflight 和默认 live route 保持关闭。本审查只覆盖 fake/inert 原型，不构成生产 acceptance。

## 冻结身份与独立复跑

候选 manifest SHA-256：`f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb`；作者 receipt SHA-256：`66b556a7dc7a17613cc7d87b34fa0168876058c9b881d68186cba8c6c81df2d1`。10/10 manifest payload、receipt/manifest sidecar 均核验通过。custodian source SHA-256 `c843712eb3e999b88790f0adb18848cd6d2341db5f2efeb19a8eee3a32a80dce`；probe source `f1959f9f6a4246bbdd186a965cca192ea80ce16255976d1245833b4783995e49`；冻结 EXE `a6a1270cd4a5a868f6a8ee51c14fbcc1b463906e45488a7f92676ac070aac9a0`；OBJ `77c12781cc9d742153d53ab7d2986944239ad13366e0c33cff39abb4f7954c3e`。

在独立副本以同一 C++ 源码构建后重放全部候选支持场景：冻结 trial 为 13 个断言谓词 / 0 个失败；独立复跑也是 **13/13 谓词、0 失败**，包括 10 个 runner 模式和单独的 outer Job kill probe。该计数验证候选预期的正、负行为，不表示 13 个独立 OS hang injection，更不代表 G1 接受。完整原始源码、运行日志、机器收据和 sidecar 哈希在[独立 QA ZIP](ctp-g1-r8-independent-qa-2026-09-27.raw.zip)中。

- **P05 同步 admission 反例：**冻结 `r8_trials.json` 的 D=1,200 ms，`caller_decision_ms=1218`、`caller_api_returned=false`、`caller_blocked_at_deadline=true`，之后 watchdog 才终止 caller Job。独立复跑分别记录 1,234 ms，同样未在 D 内返回。作者叙述文件的 1,234 ms 与 31 ms 是旧样本；manifest 绑定的最终 trial 对应为 1,218 ms 与 16 ms。两次运行保持分列，不混作同一个样本。
- **OVERLAPPED I/O：**冻结与独立复跑均观察到 API 返回 UNKNOWN 时 `io_pending=1`；`CancelIoEx` 返回成功、pending 清零，最终 completion 为 `ERROR_OPERATION_ABORTED`（995，0 bytes）。冻结样本的 API 决策时间 1,031 ms（I/O 等待 1,015 ms）。I/O owner process PID 等于 caller PID，owner thread 与 API thread 不同。`IoReaper` 是 caller 进程内的线程，完成并消费错误 995 后 caller 才退出；没有跨 caller 进程存活的 I/O reaper。
- **caller 死亡后的 handle/I/O 生命周期：未验证。**外层 Job kill 场景没有 pending OVERLAPPED；overlapped 场景在 caller 退出前已 drain。没有场景证明 caller 被杀后另一个进程继续持有 pipe、`OVERLAPPED`、event 和 buffer，亦未测 caller death 与 live peer 的竞态。
- **外层 Job duplicate kill：**冻结 trial 从 5 个 ActiveProcesses 开始，外部 runner 通过 duplicate Job handle 终止后，Job 计数归零用时 16 ms；caller、custodian、worker 的 retained process handle 均返回 `WAIT_OBJECT_0`。独立复跑为 5→0、15 ms。此结论仅适用于 duplicate handle 已可用之后的 inert Job tree。

## 截止时间与进程启动边界

`r8_custodian.cpp:367-461` 先创建 Job/pipe、启动 worker/custodian/caller 并等 READY；request D 到 line 454 的 `requestStart` 才开始，然后发 GO。外层 launcher 在 lines 571-576 将 Job handle duplicate 给 Python runner并发出 `OUTER_JOB_CONTROL_READY`，之后才在 line 580 将 launcher 自身分配到 Job；再创建/恢复子进程并发出 `OUTER_JOB_READY`。trial marker 顺序和 `prewarm_ms` 都显示 prewarm、pipe/setup 与 handle transfer 发生在 request D 之外。

完整命令启动 deadline 仍未建立。Python runner 在 `run_r8_trials.py:157` 调用同步 `subprocess.Popen`，在调用返回之前没有 launcher process handle；duplicate Job handle 更晚才由 native launcher 创建并转移。该转移之前的 `CreateJobObjectW`、`OpenProcess`、`DuplicateHandle` 和 Popen 未注入阻塞。runner 的 8 秒外层 watchdog 仅在 Popen 返回后工作，不是 1,200 ms request D。同步 CreateProcess、ResumeThread、Job query/terminate、CancelIoEx 和 CloseHandle 的任意阻塞边界也没有穷尽注入。

## 未覆盖项目与边界

候选没有实现的检查仍为未验证：P02/P03 CreateProcessW 调用前/创建后阻塞；P04 ResumeThread hang；P06 connect/read/body pending；P07-P09 延迟 completion 与取消错误竞态（含 `ERROR_NOT_FOUND`）；P10 pending I/O owner death；P11 malformed frame；P13-P15 Job 查询失败/假零与延迟 cleanup；P18 caller disconnect；P19 独立 reaper death 且 request Job 存活；P20 并发/复用 slot；P21 deadline 后迟到成功。不能由 13 个既有谓词替代这些缺失注入。

未使用 CTP、凭据、SDK/native/provider、外部服务、网络、私有配置，也未触碰默认 preflight/route。候选只证明有限的本机进程与 Job 行为。**G1 CLOSED。**

作者候选页见[R8 作者摘要](ctp-g1-r8-author-2026-09-27.md)。完整独立报告、机器 receipt、原始 frozen inputs 与 replay logs 由 ZIP 和内容 sidecar 绑定：ZIP SHA-256 `aa578adece4263bdcb6fe5c41f4959eeae8fed7f8e106683fe233081e1e11992`；sidecar SHA-256 `23dfb2b55f5444d8d7a57980e3e5e892f3b38211fd8e4b1d7a9194b11ed7319a`。ZIP 有 29 项，`testzip()`、逐项 sidecar 哈希和 10 项 manifest payload 核验均通过。
