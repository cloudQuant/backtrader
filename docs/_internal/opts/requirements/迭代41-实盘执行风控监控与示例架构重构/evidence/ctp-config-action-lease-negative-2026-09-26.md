# CTP 配置动作租约负测（2026-09-26）

**结论：`NO_WRITE / LIVE_NO_GO`。** 未登记的
`backtrader_runtime/ctp_config_action_linearization.py` 只供离线诊断。
它不能作为报单/撤单最后一次重封到原生调用之间的写入准入。

本机 Windows/NTFS fake-action 测试持有配置文件和路径组件的读租约。
普通内容写入、替换、删除和重命名受阻；非固定驱动器及配置硬链接被拒绝，
同卷无关目录仍可写入。但并行 `FILE_WRITE_ATTRIBUTES` 句柄在 fake
native-action 窗口成功为**被租约持有的配置文件**设置自定义
name-surrogate reparse tag。随后按原路径打开失败（WinError 1920）；
测试在 `finally` 中清除 tag，原租约句柄仍能读到原内容。这个观察证明
共享租约未阻止路径元数据变化；它**没有**证明该机器已把路径重定向到
另一份配置，也没有触达真实配置或 CTP。

复核命令：

```text
python -m pytest -p no:asyncio tests/unit/runtime/test_ctp_config_action_linearization.py -q --tb=short
11 passed, 1 skipped, 1 existing pytest config warning
```

Ruff、`py_compile` 和相关 `git diff --check` 通过。测试只有 fake native
action，没有凭据读取、SDK import 或 provider I/O。Windows 以外的实文件系统
行为、管理员/内核绕过和跨主机写者不在此结果内。

## Python dispatch 间隙负测（2026-09-26）

`tests/unit/runtime/test_ctp_simulation_execution.py::test_profile_config_change_after_final_check_blocks_native_dispatch` 用合成临时配置和 fake native port 精确插入竞态：在 submit 与 cancel 各自最后一次 `_revalidate_profile_scope_after_reserve()` 成功返回后，测试立即改写 `config.yaml`，然后检查 native fake 是否仍被调用。当前实现两条路径都会到达 fake native adapter，所以“不得派发”的断言按预期报告 `2 xfailed`；命令为：

```text
python -m pytest -p no:asyncio tests/unit/runtime/test_ctp_simulation_execution.py -k profile_config_change_after_final_check_blocks_native_dispatch -q --tb=short
68 deselected, 2 xfailed, 1 existing PytestConfigWarning
```

这是记录仍开放缺口的预期失败，不是修复或验收通过；测试没有凭据读取、SDK import、provider I/O 或真实配置访问。当前 Python session 的重复重封能拒绝发生在重封前的改动，但不能阻止重封返回后并发修改。Windows lease 的负测另证其 `FILE_WRITE_ATTRIBUTES` 反例；此处 fake race 不推断 POSIX 或其他文件系统行为。P2 仍开放，默认写入口继续关闭。

拟议的最小下一步是 S/P 共用的本地配置与动作一致性边界：受信逐动作执行者本身管控配置/路径/ACL 的变更，
排除预先打开的变更句柄，核验配置代次、有效 scope 和动作 payload，
在同一隔离边界内只调用一次 native API，再返回不透明回执。
现有 helper 仅定义类型合同，没有 broker 实现或默认路由；
将可转交的 grant 交给仍能修改配置或直接调用 native API 的进程，不满足该合同。这个本地边界不证明账户级外部写者排他；后者只属于 G6-P，G6-S 须保留 `UNPROVEN` 残余风险。

参考：[Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、
[FSCTL_SET_REPARSE_POINT](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4aeefef8-92c3-4abc-af7a-a610caf8a165)、
[Reparse Point Tags](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-tags)。
