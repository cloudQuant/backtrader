# BM57 direct Store 基准工具：独立 smoke 验收

**结论：`SMOKE_ONLY / NOT_ACCEPTED_FULL_MATRIX`。** 本次只验收测量工具的路径、计数、来源和阈值计算，没有取得正式性能结论。

## 实现与测量范围

`scripts/run_iteration41_direct_benchmark.py` 在隔离子进程中使用合法 schema-v4 `simulation/replay` 配置、合成非授权 `TestExecutionProfile` 和本地 fake API，实际调用 `BtApiStore.submit_order/cancel_order`。配置加载、封存和 profile 校验单独计时，不进入热循环。基线为实施前 dev 提交 `ad2c142b9a8b42cede85886528c681abdfcb8096` 的 package 导出；它不是用于策略正确性回归的 master 基线。

正式样本协议为每操作 1,000 次预热、五轮成对运行、每轮每操作 10,000 个样本，交替两侧先后顺序。submit/cancel 的 p50、p99 分别计算五轮 candidate/baseline 比率的中位数，均须不超过 1.05。阈值失败报告 `PERFORMANCE_NOT_ADMITTED`、exit 3；工具或来源失败报告 exit 2。七样本 smoke 不评估这个性能门槛。

## 根代理独立结果

- 四项合同测试通过，用时 4.41 秒，有一条现存的 pytest asyncio 配置警告；结果保存在本轮工具输出，没有另存 JUnit。
- 新目录中的 smoke exit 0，两侧各执行 2 次预热、7 次测量，分别观察到 9 次 fake submit 和 9 次 fake cancel。
- 配置 loader 计数在热循环前后均为 2；module origins 来自各自指定源码根；源码、runtime 和脚本 hash 首尾一致。
- socket/thread API 尝试、新 Python 线程和插件导入计数为 0。Windows 热循环 OS 线程数保持 4→4。
- 新工具源 SHA-256：`4b7a64e9381fc86a3d75291b972ae53684f9de70192c25e6def335c23236193f`；测试 SHA-256：`1e7425ee5fd2992009c68df30d8b07dd2646fcbb2be399a10b5f9f2cfdda5fab`。

该主机同时进行其他开发，未声明性能隔离。tiny smoke 的耗时不用于判断回归比例。Python hook 只观察本次测试活动，不是 OS 安全隔离。没有使用 SDK、CTP 原生模块、私有配置、真实账户或 provider；默认 route 未改变。五轮 Windows/Linux 正式矩阵仍未运行。

## 复现与原始材料

使用独立 Python 3.11.5 source-QA venv：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
& 'D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe' -m pytest tests/unit/scripts/test_run_iteration41_direct_benchmark.py -q -p no:cacheprovider --tb=short
& 'D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe' scripts/run_iteration41_direct_benchmark.py --smoke --baseline-source-root 'D:\temp\iteration41-bm57-baseline-ad2c142b-20260926' --candidate-source-root 'D:\source_code\backtrader' --output-dir 'D:\temp\iteration41-bm57-independent-20260926-01'
```

输出目录必须是新目录，复现时另取名称。全部样本及逐文件 hash 见[结构化收据](bm57-direct-harness-review-2026-09-26.json)、[原始结果](bm57-direct-harness-review-2026-09-26.result.json)和[原始文件包](bm57-direct-harness-review-2026-09-26.raw.zip)。原始包 SHA-256 为 `3b0151048b460754dbb0f96093b3a1cc66173ded9597bec8b44a9f7805fd12ea`。
