# F10 核心策略回归（2026-09-26）

裁决：`LOCAL_F10_CORE_REGRESSION_PASS`。完整策略集 **1286 passed、0 failed、
0 errors、0 skipped、13 warnings**，pytest 用时 **312.48 秒**，exit 0。

## 范围与来源

本机 Windows、Anaconda CPython 3.11.5、pytest 8.0.0、xdist 3.6.1，8 workers。
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，显式加载 `xdist.plugin`，清除 `PYTHONPATH`
与 `BACKTRADER_USE_INSTALLED`。前后导入均为本仓 `backtrader/__init__.py`。
禁用自动插件避免全局 pytest-asyncio 的已知 collection 兼容性问题；
配置 warning 与第三方 pandas/loky warnings 共 13 条，没有测试被跳过。

```text
python -m pytest -p xdist.plugin tests/functional/strategies -n 8 -q --junitxml=<qa2>/junit.xml
```

HEAD 保持 `ad2c142b9a8b42cede85886528c681abdfcb8096`，工作树含开发修改，
因此以 [1662 路径的实际字节清单](f10-core-strategies-2026-09-26.sources.csv)
标识本次代码。清单覆盖整个 `backtrader/**/*.py`、策略 Python/JSON 与测试配置；
运行前后 CSV 字节完全一致，source diff 为空。策略目录当前有 1154 个测试文件，
实际 JUnit 中为 1286 个 test case，不能套用旧文档的 1271 数值。

根代理独立解析 [JUnit](f10-core-strategies-2026-09-26.junit.xml) 确认 1286/0/0/0，
核对首尾清单 hash 相等与零字节 diff；[原始日志](f10-core-strategies-2026-09-26.log)
和 [JSON 回执](f10-core-strategies-2026-09-26.json) 一并保存。
完整本机输出位于 `D:\temp\iteration41-f10-strategies-20260926-qa2`。

## 保留的首次启动失败

`qa1` 目录保留：第一次调用 1.95 秒后 exit 5，无 JUnit、无测试 summary，
也未报告断言失败。独立 collect-only 得到 1286 项，重新显式构造 JUnit 参数后的
qa2 成功。首次退出的精确原因未证实，不能说整个过程没有失败，也不能把它算作
策略断言失败。原证据未删除或覆盖。

## 结论边界

F10 是冻结核心库的独立回归。正在修改的 `backtrader_runtime` AC27 数值投影
不在该策略集依赖范围；该项继续独立复核，不能由本次 F10 推导通过。
这也不覆盖 serial 性能、跨平台、安装制品、hosted CI、CTP native 或真实账户验收。
