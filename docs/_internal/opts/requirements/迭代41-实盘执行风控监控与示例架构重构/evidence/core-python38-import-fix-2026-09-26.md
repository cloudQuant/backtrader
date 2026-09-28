# Python 3.8 默认导入修复

独立复核在 CPython 3.8.20 上发现 `import backtrader` 失败：默认 Store 导入链中的
`CtpManagedDispatchBinding` 使用了 Python 3.10 才支持的 `dataclass(slots=True)`。
此前 config/operator harness 未执行这个 DTO 的类定义，因此没有覆盖这次回归。

## 修复

- `backtrader/stores/managed_execution.py` 仅在 Python >=3.10 传入 `slots=True`。
  旧解释器仍使用 frozen dataclass；现代 SDK 解释器上的 slots 保留。
- 新 fresh-process 边界测试直接执行该 stdlib-only 模块的类定义，验证 frozen 与无
  `bt_api_*` 导入；现代解释器同时检查 slots。它能覆盖运行时 decorator 兼容性，
  不依赖仅做 AST 语法检查。
- `scripts/ci/run_iteration41_cpython38_core_runtime.py` 增加此 import-boundary 测试
  文件。该 CI lane 仍不安装或支持 managed SDK。

## 本机验证

| 范围 | 结果 |
| --- | --- |
| CPython 3.8.20 实际默认 `import backtrader` + 新 runtime projection imports | exit 0，源码为本仓，已加载 `bt_api_*` 列表为空 |
| Python 3.8 fresh-process boundary | 2 passed，1 条既有 pytest 配置 warning |
| 扩充后的 Python 3.8 config/operator/import harness | 111 passed、8 skipped、1 条既有配置 warning，exit 0 |
| Python 3.11 CI harness/import/managed projection 焦点 | 35 passed、1 条既有配置 warning |
| 三个修改文件的 Ruff | 通过 |

独立 reviewer 随后在 CPython 3.8.20 重新执行实际默认导入，确认无 SDK 模块加载；
fresh-process boundary 文件在 Python 3.8.20 和 3.11.5 上均为 **2 passed**，
3.11 分支实际检查了 slots 仍存在。它没有重复整套 111 项，也未把这项局部复核写成
新的一次全量测试。

Python 3.8 解释器为 `C:/anaconda3/envs/btcpp-py38/python.exe`，版本 3.8.20。
本机 JSON 为 `D:/temp/iteration41-core-py38-import-fix-20260926.json`，SHA256
`4ae79d51c76b19e2fcc4a89f3f290918b7e0c297314d38feff544901718d2e19`。
8 项 skip 未计入通过；这仍是 Windows 本地结果，不替代 hosted Ubuntu/Windows CI，
也不使 Python 3.8 支持要求 Python >=3.11 的 managed SDK。
