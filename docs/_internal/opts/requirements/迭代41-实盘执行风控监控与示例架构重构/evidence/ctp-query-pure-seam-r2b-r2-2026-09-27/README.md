# r2b CTP 查询证据纯测试接缝：r2 自包含包

结论：`LOCAL_TEST_CONTRACT_PASS / PACKET_COMPLETE / FAKE_LOCAL / OFFLINE`。本切片仅迁移 Iteration22 的 158 个查询/证据失败节点中的 **1 个**；其余 157 个 nodeid 保存在 [作者 r2 ZIP](author-r2.zip) 中。它没有修改 Store、默认 runtime 或任何真实账户路径，也不证明原生查询生产者、会话来源、外部 Actor、报撤单或 SimNow/production 准入。

[作者报告](author-report.md)保留原 nodeid 的两条核心完成性断言，另加合成 envelope 正例和 17 个带语义标签的负例。r1 [独立合同复核](independent-r1-receipt.md)在精确 r2b 源重放补丁后得到 19 项通过，三条 CTP 路由探针拒绝，Trap API 属性读/调用为 0，SDK/native 导入为 0，并核对剩余 157 项的集合。r1 的 15 条哈希索引有 5 条指向包外路径，因此 r1 包本身未获自包含接受。

r2 只改包装，不改测试补丁或 19 项测试逻辑。[独立 r2 收据](independent-r2-receipt.md)与[机器结果](independent-r2-result.json)确认 18 个 ZIP 成员精确组成 15 个 indexed payload、哈希索引、manifest 与 verifier；15/15 字面相对路径在包内存在且哈希、长度匹配，ZIP CRC 正常，从新解压副本执行 verifier 成功。r2 没有重新跑逻辑测试，其内容与 r1 通过的 payload 逐字节相同。

| 文件 | SHA-256 |
| --- | --- |
| `author-r2.zip` | `2840372130889784F6C691F0B7DE8CCC90812823FAC15E2871547E1C7463AC74` |
| `author-manifest.json` | `AD6106E0542FABAD44A16D86F7AEE8A39B4EBE6342A152BCCAD491960C9A0C5E` |
| `author-report.md` | `92D7E5C7B5F6728459A42BE7793DA451215B14D06041E7B66C9185E01A04858E` |
| `independent-r1-receipt.md` | `4176C24F531E447E326AFEF11C28F12BC4D1D1CC62575DABB263DB4DB038B6F8` |
| `independent-r2-receipt.md` | `A63E8483ECDEB319C9D1E2DD2A3D3A661FE6F68EA6105C23C1FFB6A9BC24C77C` |
| `independent-r2-result.json` | `46EF52E92C9EA4DD230622034C1F60EE68ADB53727AAAD584090E8DC115514BB` |
