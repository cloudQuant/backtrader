# 运行时测试进程 PyYAML 模块隔离修复（2026-09-27）

本轮新增的 G6-P/G8-P 合成守卫测试改为在独立 Python 子进程运行签名收据→action claim→共享 live opener 链，以免 pytest 收集/执行提前加载 PyYAML 原生模块。随后全量运行时套件仍在 `test_ctp_i13_worker_dependency_seal.py` 暴露既有测试间状态问题：source-finder 测试无条件删除此前存在的 `sys.modules['yaml']`，native-spec 测试假定此前没有任何测试加载 `yaml._yaml`。旧行为的全量运行中出现 `467 failed / 1490 passed / 30 skipped / 2 xfailed`，不计作功能回归结论。

现在 source-finder 测试精确恢复进入时的 `yaml` 模块对象；native-spec 测试先保存并清空两个目标扩展的模块键，逐步断言 finder 查找不加载扩展，最终恢复原对象并验证身份。先导入 PyYAML 的三节点复现由 `2 passed / 1 failed` 变为 `3 passed`。作者和 root 均运行完整 `tests/unit/runtime`：root 命令为 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -B -m pytest -p no:asyncio tests/unit/runtime -q --tb=short`，退出 0，结果 `1957 passed / 30 skipped / 2 xfailed`，一项既有 `asyncio_default_fixture_loop_scope` 配置警告，115.58 秒。两处测试文件的 Ruff 检查通过；运行时代码未因该修复改变。

root 核对守卫测试 SHA-256 `43ef7060ef065842d8e26f97b881c8d39084edf03a5919c32b6014cde0554d30`、依赖测试 SHA-256 `d38eafd7cb5846f3aca6677207b9ab5979e3233b91769f399b56d300cdf600b1`，并封存前后两轮原始日志。[原始归档](ctp-runtime-yaml-test-isolation-2026-09-27.raw.zip)共四项文件，ZIP 完整性和内部摘要通过，归档 SHA-256 `e845d3c59812b0c22b0028d79cdbf1060b98b5c70033590d18a2123e469f88da`。这只是当前主仓离线 runtime suite 的复核，不构成 CTP 原生、G1–G8 或真实交易验收。
