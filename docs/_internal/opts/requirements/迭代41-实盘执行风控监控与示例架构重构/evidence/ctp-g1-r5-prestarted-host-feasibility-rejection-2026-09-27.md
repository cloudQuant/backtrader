# G1 r5 同步进程创建可行性负测（2026-09-27）

裁决：`R4_BACKEND_HARD_DEADLINE_COUNTEREXAMPLE / G1_BLOCKED`。

r4 host 的 `create_suspended_in_job` 是同步调用。r5 在该边界用确定性 fake 阻塞 setup：到截止后 113 ms 调用线程仍卡住，未发布 session、Job/进程/线程句柄或保留控制 token；解除阻塞后只返回 `not_ready`，没有已准备 host。这个反例证明**当前 r4 接口**无法给调用者提供整命令硬截止；没有刻意卡住真实 Win32 调用，也没有真实子进程。复制 r4 加负测的隔离测试为 pytest `15 passed`、unittest `15 passed`，并非截止条件正面验收。

[Microsoft `CreateProcessW` 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)把进程/主线程句柄作为调用成功后的 `PROCESS_INFORMATION` 输出。[扩展创建属性文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)支持在创建时关联已存在的 Job，但不赋予阻塞调用的返回期限或提前发布进程句柄。[Job Objects 文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)定义 Job 的控制与句柄生命周期。结合本地反例，下一候选需让独立 custodian 在接受请求**之前**持有受控执行 worker/Job，并把同步 setup 放进可终止的执行边界；该结构仍待实现和独立验收。

root 复核 r5 manifest SHA-256 `fe9bf529aa4072a86d59a1da964e801fee6c2e0cdf8406f9949dc033f54dd696`、审计 SHA-256 `1d870a895dd461f17a35706a47153a974fcc950547bd0e6454b6342071fc6997`及 12 项声明制品的大小/摘要。[原始归档](ctp-g1-r5-prestarted-host-feasibility-rejection-2026-09-27.raw.zip)共 14 项文件，ZIP 完整性及内部摘要通过，SHA-256 `2e2d69511c2e752b3d31569c423b6b1d56eb5ed1502dcfbd3b8e246380b2094b`。默认 preflight、CTP 读写和 live 路由保持关闭。
