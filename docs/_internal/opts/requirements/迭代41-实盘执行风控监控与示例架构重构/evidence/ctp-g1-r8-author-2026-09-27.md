# G1 R8 惰性 custodian 候选（作者摘要）

日期：2026-09-27  
候选状态：`REJECTED_G1_CLOSED`。这是本机 Windows 上的 inert/fake 原型，不是服务部署、生产集成或 G1 接受证据。

冻结 manifest SHA-256：`f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb`；作者 receipt SHA-256：`66b556a7dc7a17613cc7d87b34fa0168876058c9b881d68186cba8c6c81df2d1`。manifest 绑定 10 项 payload，包含 C++ 源码、可执行文件、对象文件、runner、trial 与 review checklist。作者 receipt 明确无 provider/credentials。

候选 runner 覆盖正常完成、未就绪拒绝、worker/custodian stall、同步/overlapped admission、后代进程和外层 Job 终止等模式。清单记录 13 个断言谓词且无断言失败；其中 P05 断言的通过含义是**检测到**同步调用超过请求 deadline 的反例，并非 deadline 通过。冻结 `r8_trials.json` 记录同步 caller 在 D=1,200 ms 时仍未返回，监督器之后才杀 caller Job。

**裁决：G1 CLOSED，普通 preflight 与默认 route 继续关闭。** 进程准备、handle transfer、Python `Popen` 等启动操作没有纳入请求 D；OVERLAPPED reaper 是 caller 内的线程。候选未证明完整命令 deadline、caller 死亡后的 pending I/O 所有权或真实 OS 服务 containment。

作者原始材料与独立 QA 证据见[R8 独立审查](ctp-g1-r8-independent-review-2026-09-27.md)和[只读 QA ZIP](ctp-g1-r8-independent-qa-2026-09-27.raw.zip)。作者 `R8_FINDINGS.md` 中的时间样本与结构化冻结 trial 有出入；独立审查分别保留两份记录。
