# 撤单释放控制端 r4 作者候选（2026-09-27）

状态：`AUTHOR_OFFLINE_FOCUS_PASS / INDEPENDENT_QA_PENDING / NO_CTP_RELEASE`。此记录只描述新的隔离候选，不修改 r3 冻结文件，不批准模拟盘或实盘路径。

r4 冻结快照位于 `D:\temp\iteration41-cancel-control-r4-freeze-r1-20260927`，payload manifest SHA-256 为 `60B020202ED89169E24AFCA30B1B1B16680151A11C6F52C518D0F5BBFA7FAB0D`。[作者原始归档](ctp-parent-cancel-control-r4-author-candidate-2026-09-27.raw.zip) SHA-256 为 `9364EC4FCB4E317A1EF6AA61E60E357333B342A3856EE0EECCA1F0DD09C69BF8`；归档 manifest SHA-256 为 `9A2564671672491993E710D45AB6F2FE3198870B38334E314D55D531AF62EB13`。作者逐文件回执、测试日志及探针记录均在归档内。

冻结快照上的离线焦点命令运行结果为 **20 passed**：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest --noconftest -p no:cacheprovider tests\test_cancellation_dispatch_resolution_control.py -q
```

Ruff **未通过**：r4 两个修改文件有 23 项发现，冻结 r3 为 18 项；新增五项诊断（清理路径的 S110/BLE001 与一项 RUF100）。原始 JSON 在作者证据包中保存。尚无独立 QA 或主桥接复测结论。

r4 将 release-prepared monitor 事件在最终风险释放前落库，并在精确事件读回、风险审计释放和最终风险锁清理期间持有 monitor SQLite 的 `BEGIN IMMEDIATE` 写保留；released replay 也走该门。代码-owned UPDATE/DELETE trigger 阻止普通并发 SQLite DML。此前未显式关闭的 monitor readback 连接已改为关闭，并有连接关闭回归测例。

仍有明确边界：同一用户具备文件/DDL 权限时，能在提交后执行 `DROP TRIGGER` 后删除事件，探针已复现；替换数据库文件也不受隔离。因此此门只覆盖协作式 SQLite writer，不提供同用户恶意写隔离。risk 与 monitor 是两个 SQLite 数据库，不具备一般跨库原子事务；现有操作中 monitor event append/triggers 先行提交，随后精确读回并清理 risk latch。此特定顺序没有证据证明会因进程崩溃产生缺失事件，但进程死亡语义未独立测完。**CTP 和 production release 继续硬拒绝**，不将此候选解释为真实账户授权或 G5/G4 验收。

