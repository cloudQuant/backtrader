# G1 R9 预启动服务拓扑设计回执索引

状态：design-only；G1 仍关闭。此材料归档的是只读拓扑提案，不表示代码实现、Windows 服务部署、真实身份/ACL/CPython runtime 验收或 preflight 开放。

- 设计报告：[g1-r9-prestarted-service-topology-design-only-2026-09-27.md](g1-r9-prestarted-service-topology-design-only-2026-09-27.md)
- 逐字节来源清单：[manifest](g1-r9-prestarted-service-topology-design-only-2026-09-27.manifest.json)
- 原始冻结副本：D:\temp\iteration41-g1-r9-prestarted-service-design-20260927\R9_DESIGN.md；SHA-256 77500a63eabd0df5673b923458893fbd44c0d3ca1ec22c403dff95b98d869bd0
- 原始来源清单：D:\temp\iteration41-g1-r9-prestarted-service-design-20260927\r9_manifest.json；SHA-256 ad6fb53200789e051fc93d76d073c54c6f2d7d9bfaea4b3e288da0bd055765c0
- R8依据：D:\temp\iteration41-g1-r8-independent-custodian-20260927，manifest SHA-256 f1ce63cf08ec620c7a4ca09fac55bc26a7553f88796cfb3e2a768f7bb008cdeb。R8最终 P05 记录是 1218ms / D=1200ms；归档 findings 中的 1234ms 是较早运行。

范围：报告提出 caller-side 预连接 I/O broker、READY-gated persistent service reaper、Job1 coordinator/worker 后 Job2 receipt writer、同一绝对 deadline，以及 P02/P03/P07/P14 负测。它明确保留 reaper 的同步 terminate/query/close 卡死、OS调度、SCM prewarm和生产部署信任边界；这些情况下结果仍 UNKNOWN，不能据此声称 G1 通过。

仓库源码没有随本次归档变更；本回执未新增测试或更改验收矩阵/检查点。