# Parent cancel-control r4 独立 QA 回执

日期：2026-09-27（Asia/Singapore）
分类：`LOCAL_FAKE_GUARD_BOUNDED_PASS / SAME_USER_DDL_BYPASS_CONFIRMED / NOT_PRODUCTION_ACCEPTANCE`

## 冻结与变更范围

- r4 冻结根：`D:\temp\iteration41-cancel-control-r4-freeze-r1-20260927`；`payload-manifest.json` SHA-256 `60b020202ed89169e24afca30b1b1b16680151a11c6f52c518d0f5bbfa7fab0d`。154/154 大小与 SHA-256 匹配；清单外 payload 文件 0（空 `.ruff_cache` 目录不作为 payload 文件）。
- r3 对照 manifest SHA-256 `65af6f048a1148182b35a18b8998f738a306d83b5d33352bd469c809c3a8d28f`，154/154 匹配。两 manifest 文件集合一致，仅两项变化：`bt_api_py/runtime_plugins/cancellation_control.py`（r3 `9af8665d98d414c475479da1eb9d2ebbc7b502853ad877f628e5118acb528d9b` → r4 `8b7d2b02654d0b4a9fbea63f4bc359a0135df6410cf4034ea069a41e32b898cd`）和 `tests/test_cancellation_dispatch_resolution_control.py`（r3 `e80bfc25ee9cdaafcee95d4b97e1bb598c420b04dc92ee331941af757c38d2a2` → r4 `0160907f5ae68eba844bf39961b65ea09f038c3d0517a3fb0e432a142407c8d7`）。独立副本 154/154 复核通过；冻结树未编辑。
- 同哈希 unified diff：`r3-r4-source.diff`。机器清点：`manifest-diff-verification.json/.log`。

## 复跑及 lint 差异

- 在独立 payload 副本执行冻结 focus：`20 passed in 11.51s`，日志 `focused-tests-independent.log`。作者日志同样报告 20 passed。另单独复跑 CTP 标签假 scope 拒绝测试：`1 passed`，日志 `ctp-labeled-fake-scope-rejection.log`。
- Ruff 0.16.2 在两个变更文件上用同一选择器 `TRY004,BLE001,S110,FURB157,RUF100,I001` 独立得到 r3 18、r4 23，且 r4 的 23 条与作者 `frozen-r1-ruff.json` 的诊断码/行列/消息逐项相同。差额 +5：`BLE001 +2`、`S110 +2`、`RUF100 +1`。作者单独的 `ruff.log` 为 “All checks passed”，但不能据此称两变更文件或全包 Ruff clean；本回执也不作整体 clean 声明。详见 `ruff-comparison.json` 及两份独立 Ruff JSON。

## 独立负测

1. **普通跨进程 DELETE**：另一个 Python 进程在最终 risk resolver 被调用时开始 DELETE；guard 仍持有 monitor `BEGIN IMMEDIATE` 期间子进程一直未结束。释放返回后它收到 `IntegrityError: cancellation release monitor facts are immutable`。提交后再起的普通 DELETE 同样被触发器拒绝，monitor event 保留；审计为 RELEASED、两风险锁清除。该观察表示并发 DML 被 guard 序列化，随后被触发器阻止。
2. **同用户 post-commit DDL bypass**：另一同用户进程成功 `DROP TRIGGER` 两项 release immutability triggers 并删除 event。审计仍是 RELEASED、两风险锁均 inactive，monitor event 缺失、触发器集合为空；monitor DB `quick_check=ok`。持久状态在 `ddl-bypass-state/`。因此 SQLite trigger/事务只构成合作式 DML 写者边界，不是面对可写数据库文件的同用户攻击者的安全边界；没有复现远程访问，也没有验证文件 ACL 或 owner replacement。
3. **Readback 句柄生命周期**：正常和合成查询异常两路径都观察到 `closing()` 调用关闭连接；关闭后再执行收到 `sqlite3.ProgrammingError`。Windows `psutil.Process.open_files()` 对目标 monitor DB 在 readback 前/后均为 0；关闭 fixture/runtime 后仍为 0，两个临时 state 目录都成功删除。异常路径结果为 `CANCELLATION_CONTROL_MONITOR_FACT_UNAVAILABLE`。
4. **实际进程死亡 cut**：子 worker 在 `risk_gate.resolve_freeze(progress_cause)` 已提交并返回、外层 monitor `BEGIN IMMEDIATE` 尚未 `COMMIT` 时暂停；父进程用 Windows `Popen.kill()`/`TerminateProcess` 强杀，再用新连接重开三库。观察到 control audit `released` 且 `released_at` 有值；`risk_freezes` 中 unknown 与 progress 两行均 `active=0`；monitor prepared event 与两条持久触发器仍在；risk/monitor `quick_check=ok`；重开后普通 DELETE 仍被触发器拒绝。该单一 cut 未出现缺失 event。原因与源码顺序吻合：event append 和 trigger 安装已分别提交，final guard transaction 只读；risk final latch commit 后杀进程会丢弃尚未提交的只读 writer reservation，不会回滚已提交 event/trigger。**这只验证了这个进程死亡切点，不证明所有 crash cut 或跨库原子性。** 状态标记 `crash-cut-marker.json`，三库状态在 `crash-cut-state/`。

探针最终通过日志为 `extra-probes-independent-run5.log`，结果为 `extra-probes.json/.log`。较早 run1–run4 是独立探针 harness 修正记录，不是候选失败：run1 自身误用 SQLite connection context manager 未显式 close 导致 Windows 临时清理 WinError 32；随后依次修正了测试报告字段名、探针中的重复 fixture.close，以及仅注入一次的异常代理。所有尝试日志仍保留；仅 run5 的最终结果用于上面结论。

## 来源与限制

测试只用独立 payload 的 fake composition 与本机合成 SQLite；测试固定加载 `bt_api_execution`、`bt_api_risk`、`bt_api_base`、`bt_api_monitor` 本地 source roots（模块来源/hash 见 `module-scope-audit.json` 与 `SHA256SUMS.txt`）。r4 CTP 标签假 scope 拒绝测试通过。没有导入 CTP/SWIG native SDK、登录账号、触达 provider/API/网络、打开默认 route 或产生外部写副作用。保留的是 local fake 合同；面对可改数据库 schema/文件的同用户进程仍有明确 bypass，因此不得称生产撤单、G4、F14、部署或整体 lint/test PASS。

### 源码定位（r4 冻结副本）

- `cancellation_control.py:1353-1468`：append 后进入 guard，readback、audit RELEASED 和最后 progress latch 清除的顺序。
- `:1779-1844`：`BEGIN IMMEDIATE` 生命周期；正常结束 `COMMIT`，异常 rollback 并 close。
- `:1845-1891`：持久 DELETE/UPDATE immutability trigger 安装及精确验证。
- `:1893-1970`：精确 readback；无传入 guarded connection 时通过 `contextlib.closing` 关闭 SQLite 句柄。
- `tests/test_cancellation_dispatch_resolution_control.py:677-930`：ordinary writer、DDL bypass、handle close、risk failure 的作者焦点；`:931-972` CTP 标签假 scope 拒绝。

## 探针后冻结复核

全部负测结束后再次核验 r3、r4 manifest 与独立副本：仍为 154/154、仅两项 payload 文件差异，冻结树未变；见 inal-freeze-recheck.json/.log。模块来源核验见 module-scope-audit.json；未加载匹配 CTP/native SDK 名称的模块。
