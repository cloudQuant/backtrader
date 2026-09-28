# Parent cancel-control r4 SQLite 边界独立审查（2026-09-27）

状态：`LOCAL_FAKE_QA_ONLY / SAME_USER_DDL_BYPASS_CONFIRMED / NOT_PRODUCTION_ACCEPTANCE`。

本页记录对冻结 r4 的独立副本 QA；冻结目录与生产源码均未修改。冻结 payload manifest SHA-256 为 `60b020202ed89169e24afca30b1b1b16680151a11c6f52c518d0f5bbfa7fab0d`。独立检查验证 154/154 文件与哈希，r3→r4 仅两项源码变化；隔离聚焦集 `20 passed`，CTP 标签 fake scope refusal `1 passed`。

- 第二进程的普通 DELETE 在 guard 持有 `BEGIN IMMEDIATE` 时等待，guard 提交后被 immutable trigger 拒绝；提交后的普通 DELETE 也被拒绝。
- 同一用户进程可 `DROP TRIGGER` 后删除 monitor event。故 SQLite trigger 只阻挡协作式 DML 写者，不能防有数据库文件/DDL 权限的同用户写者；该绕过保持拒绝裁决。
- 正常与查询异常 readback 均显式关闭 SQLite 句柄；Windows `open_files()` 计数为 0，临时目录清理成功。
- 实际执行一个 crash cut：risk final latch/audit 已提交、monitor guard 尚未提交时终止 worker；重开后 event 和两个 triggers 保留、审计为 RELEASED、两 risk latch inactive，两个数据库 `quick_check=ok`，普通 DELETE 仍被拒绝。此结论仅覆盖该切点，不证明所有崩溃切点或跨库原子性。
- 同选择器 Ruff r3 为 18 项、r4 为 23 项，新增 5 项（`BLE001 +2`、`S110 +2`、`RUF100 +1`）；因此不称整体 lint clean。

独立测试只使用 local fake composition 与合成本地 SQLite；未导入 native CTP/SWIG SDK，未触达 provider/API/网络、账号或默认 route。结果不构成 G4/F14、CTP、真实撤单、生产释放或部署验收。

更完整材料：[独立 QA 回执](ctp-parent-cancel-control-r4-sqlite-boundary-independent-qa-2026-09-27.md)、[机器摘要](ctp-parent-cancel-control-r4-sqlite-boundary-independent-qa-2026-09-27.json)、[只读原始 ZIP](ctp-parent-cancel-control-r4-sqlite-boundary-independent-qa-2026-09-27.raw.zip)。ZIP SHA-256：`932c279d79913ec572d9bbdb0ee720748fade7179a6c3315efd0d0233786eee7`；ZIP testzip 通过。

对照：[r4 作者候选](ctp-parent-cancel-control-r4-author-candidate-2026-09-27.md)；[r4 主桥接独立复核](ctp-parent-cancel-control-r4-independent-review-2026-09-27.md)，其来源组合 3 个原桥接节点和五文件焦点分别 `3 passed`、`73 passed`，属于另一项 fake/offline 证据，不与本次 20 项相加为生产验收。

说明：完整回执为保留原始 SHA 按字节复制；其末尾复核文件名附近有一个 stray form-feed 控制字符。该拼写瑕疵不影响随包 hash 校验，机器摘要和日志仍可按归档校验核对。
