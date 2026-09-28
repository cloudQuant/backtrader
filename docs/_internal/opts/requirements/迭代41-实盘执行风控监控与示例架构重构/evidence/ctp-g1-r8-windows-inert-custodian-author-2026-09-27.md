# G1 R8 Windows惰性Custodian作者证据（2026-09-27）

裁决：`AUTHOR_WINDOWS_INERT_DIAGNOSTIC / G1_CLOSED`。这是作者冻结候选与负例记录，不是G1验收，也不是CTP集成后端。独立复核由 `g1_host_qa` 另行重放。

## 冻结档案

[原始 ZIP](ctp-g1-r8-windows-inert-custodian-author-2026-09-27.raw.zip) SHA-256：`f49e8394f788e7431f1b77a40dde51b111765e1dfd71bff715700be399906701`。ZIP含14个文件：manifest绑定的10项payload，以及manifest/receipt与各自SHA sidecar。`testzip()`通过，10/10 payload摘要逐项匹配manifest；[内容索引](ctp-g1-r8-windows-inert-custodian-author-2026-09-27.raw.contents.json)列出每项大小和SHA-256。

冻结manifest SHA-256：`f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb`；receipt SHA-256：`66b556a7dc7a17613cc7d87b34fa0168876058c9b881d68186cba8c6c81df2d1`；原生源码 `r8_custodian.cpp` SHA-256：`c843712eb3e999b88790f0adb18848cd6d2341db5f2efeb19a8eee3a32a80dce`。逐场景原始数据与21项P01–P21缺口图在冻结的 `r8_trials.json` 中，完整源码、试验脚本、构建物、inert EXE及复核清单均保存在ZIP中。

## 结果与拒绝依据

最终冻结的 `r8_trials.json` 在Windows 10 build 26100 / Python 3.11上记录10个惰性场景；13项断言验证了预期观测，包括负例。正常路径观察到worker退出码0、Job `ActiveProcesses=0`，之后释放控制；not-ready场景拒绝。descendant场景在清理前观察到Job活动数2，随后为0。Custodian/Join/cleanup/worker-write卡住场景返回 `UNKNOWN`，保留控制，再由Job终止并核实worker退出及Job为空。

关键负例P05：最终冻结的 `admission-sync` 行记录 `request_budget_ms=1200`、`caller_api_returned=false`、`caller_blocked_at_deadline=true`、`caller_watchdog_terminated=true`、`caller_decision_ms=1218`。这个1218 ms是watchdog终止及后续等待后Supervisor形成决定的时间；同步2 MiB admission `WriteFile`没有在D前返回。事后杀Job及其后的worker退出/Job empty不能算作caller在D内返回或成功。

版本差异说明：冻结包中的 `R8_FINDINGS.md` 留有上一轮试验的 `1234 ms` 数字；该文本与同包最终 `r8_trials.json` 的1218 ms不是同一轮记录。1234 ms是先前一次运行的样本，未作为最终冻结trial行；本文及最终量化以manifest绑定的 `r8_trials.json` 为准，不改写冻结原件。

`admission-overlapped` 在caller API返回时记录 `UNKNOWN`、`elapsed_ms=1015`、`io_pending=1`。同一caller进程中的reaper线程持有pipe、OVERLAPPED、event和2 MiB buffer；`CancelIoEx`记录issued=1/error=0，最终completion为error 995（`ERROR_OPERATION_ABORTED`）。这证明该单个负例中的pending I/O所有权延续到完成，不证明独立进程reaper，也未覆盖取消竞态和其它I/O阶段。

## Whole-command deadline边界

Python runner的 `subprocess.Popen` 同步启动native launcher；在Popen返回前，Python尚未拿到launcher process handle，也未得到launcher后续复制的outer Job handle。runner的外层 `communicate` watchdog是Popen返回后的8秒，不是请求D=1200 ms。native launcher仅在CreateJobObject/OpenProcess/DuplicateHandle返回后才发出 `OUTER_JOB_CONTROL_READY`；所以该句柄不能覆盖这些操作之前的启动阻塞。outer Job试验只证明控制句柄取得后可在16 ms观测到整个Job为空，不能证明调用者在D内返回。请求计时在所有prewarm/READY完成后才开始。

CreateProcess/ResumeThread、Named Pipe、Job query/terminate、CancelIoEx、CloseHandle和Python Popen的同步阻塞均没有注入挂起；已记录的Win32整数毫秒耗时只是已返回调用的样本，不是上界。R8也未安装SCM服务。没有访问CTP/provider、凭据、私有配置或默认preflight，也没有修改生产路线。

**结论：G1保持关闭。** R8为真实Windows inert进程/Job的诊断证据；同步准入逾期与尚未覆盖的最高层启动/同步API边界使whole-command hard deadline仍未得到证明。
