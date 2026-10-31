# 迭代53轮次记录：typed journal port 首次并发初始化锁

- 日期：2026-10-31
- 仓库：`D:\source_code\backtrader`
- 分支：`dev`
- Backtrader 基线：`1d72afc656603ae2eee13e138e7af04096b3133a`
- 提交状态：未提交；本记录和本轮代码改动保留在当前工作区。
- 本轮代码范围：仅 `backtrader/stores/_journal_ports.py`
- 修改后该源码的 SHA-256：`f349455a23f6bcb3c49232f643d4abfddcdb98e94af5ece63ba7ef192669838c`

## 问题与修复

`build_backtrader_journal_ports()` 原先通过无锁的 `_PORTS is None` 检查创建进程级缓存。首次调用并发时，多个线程可能同时创建不同的 `JournalPorts` 对象；随后每个 installer 将不同 port 实例交给 SDK 注册，和 SDK 对“已有 port 不可静默替换”的合同冲突。

本轮在模块中加入 `_PORTS_LOCK`。缓存命中仍走无锁快速路径；未命中时取得锁、再次读取 `_PORTS`，仅由获锁线程构造并发布对象。并发等待者返回已发布的同一个 `JournalPorts` 实例。此修复只保护进程内的首次构造，不改变 port 内容、版本校验或 SDK 的拒绝规则。

## 验收结果

- 独立 review：GO（并发锁变更）。
- 临时内存合成并发探针：通过。16 个线程经 barrier 同步后并发调用 `install_backtrader_journal_ports()`；所有调用返回同一对象，延迟构造器只调用一次，SDK 注册表的三个槽都与返回对象中的实例保持身份一致。
- `git diff --check -- backtrader/stores/_journal_ports.py`：通过。Git 输出工作副本 LF 将归一化为 CRLF 的提示；没有 whitespace 错误。
- 未新增持久测试文件，未运行完整测试套件，未提交。

## 临时探针复现方式

在 Backtrader 仓库根目录，通过 PowerShell 把下列 Python 源码放入单引号 here-string 变量 `$journalPortInstallRaceProbe`，再执行 `python -c $journalPortInstallRaceProbe`。探针临时包装导入模块中的 `JournalPorts` 构造入口，在构造时睡眠 50 ms 以扩大首次并发窗口；16 线程经 barrier 同步后并发调用 installer。`finally` 恢复被包装的模块变量并清空 SDK 进程级注册表。探针不创建文件、数据库或账户连接。

```python
import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from bt_api_execution.journal import _journal_ports, reset_journal_ports

ports_module = importlib.import_module("backtrader.stores._journal_ports")
original_constructor = ports_module.JournalPorts
original_cache = ports_module._PORTS
constructor_calls = 0
counter_lock = threading.Lock()
start = threading.Barrier(16)

def delayed_constructor(**kwargs):
    global constructor_calls
    with counter_lock:
        constructor_calls += 1
    time.sleep(0.05)
    return original_constructor(**kwargs)

def install_after_barrier(_):
    start.wait(timeout=5)
    return ports_module.install_backtrader_journal_ports()

try:
    reset_journal_ports()
    ports_module._PORTS = None
    ports_module.JournalPorts = delayed_constructor
    with ThreadPoolExecutor(max_workers=16) as executor:
        result = list(executor.map(install_after_barrier, range(16)))
    assert all(item is result[0] for item in result), "concurrent installers received different port sets"
    assert constructor_calls == 1, f"constructor ran {constructor_calls} times"
    registered = _journal_ports()
    for name in ("position_attribution", "fee_pair_facts", "registered_sim_attestation"):
        assert getattr(registered, name) is getattr(result[0], name), f"registered slot diverged: {name}"
    print("PASS: 16 concurrent installers registered one shared port set; constructors=1")
finally:
    ports_module.JournalPorts = original_constructor
    ports_module._PORTS = original_cache
    reset_journal_ports()
```

实际输出：

```text
PASS: 16 concurrent installers registered one shared port set; constructors=1
```

## 证据限制

该结果是当前 Windows/Python 进程中的合成线程并发证据。探针使用延迟构造包装器，验证 builder/installer 的缓存身份和 SDK 注册槽身份；没有构造真实 `ExecutionDecisionJournal`、打开 SQLite 数据库或执行 CTP receipt 认证。探针未记录 SDK 导入 origin 或 SDK HEAD，因此结果不作为跨仓版本兼容验收；它也不覆盖多进程、进程重启或跨机器共享，不构成 provider、账户、paper/live 或正式案例验收。