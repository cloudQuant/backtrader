# R71-104 source clock 修复证据

本目录保存已完成比较的原字节，未重新执行测试或基准。修复提交为 `4034b03e7818e74f2543b52fa9dfb2345aa97b4f`，父提交为 `0ef1994c6b06a741c091e10cc2e194fffb51beb2`。基准使用的公开源树是 `a2472f5b0baedf460de043847ab9f9189dc3a42f`；候选是该基线仅替换 `backtrader/lineiterator.py`，不是整个源树升级至修复提交。两棵临时树中 696 个 Python 产品文件经 CRLF 归一化比较，仅此文件不同。修复提交的产品文件 Git blob 与本目录候选原字节相同；基线快照产品文件为 CRLF、Git blob 为 LF，归一化一致。基线 Git blob SHA-256：`391d3a9c9605e8f1f9916188d78e5a6658b7cf901328793ed185f866115e3661`。

## 证据解释

根代理串行执行四组 AB/BA，总计八次真实 Cerebro runnext，机器并非独占。两个对齐 Feed、4500 根合成 bar、一个嵌套线表达式及 12 个 SMA；每次输出 4487 行，摘要均为 `da058ee85774915fb1a6fc4b189d74048535dc810f0c641941697a34a5b4dfa3`。基线中位数 1.58633895 秒，候选 1.59660405 秒；小样本及非独占环境不支持稳定性能改善结论。原始顺序、每次用时、Python 和平台信息见原始 JSON。结果仅覆盖所测负载。

修复不再使用可能陈旧的 source clock 缓存。用户未跟踪的 `tests/unit/core/test_iter71_core_perf_batch7.py` 中两个 WIP 测试断言私有缓存存在，与此实现冲突；用户文件未修改，不能声称原样通过。公开隔离矩阵中，异步双 Feed 的 next 与 once 输出摘要在基线已不同；异步双 Feed 加 exactbars=1 在 next 和 replay 均于基线与候选抛 `IndexError`。这些异步问题仍开放，矩阵前后相同不等于语义已验收。

## 固定 Git 重建

以下记录所测源树关系，并非重新执行基准。使用全新独立临时目录，从同一 Git 仓库以 `git archive a2472f5b0baedf460de043847ab9f9189dc3a42f` 导出两份；分别将本目录 `lineiterator-head.py.txt` 和 `lineiterator-nocache.py.txt` 原字节放到两份树的 `backtrader/lineiterator.py`，并将 `bench_clock.py` 原字节复制到两份树根。候选文件也可从固定修复提交对应 Git blob 验证 SHA。原始归档 tar 的 SHA-256 为 `e6981a726f20d57f564cad60cf315beab3c04a8786c31df138b25db176a844e3`；tar 未收入本目录，可按固定 Git 对象重建源内容，归档字节和时间元数据不保证逐字节重现。

`iter71_clock_root_serial_20261122.py` 是原始驱动，写死原临时目录并会写结果 JSON。不要直接在原目录重跑以免覆盖历史证据；若未来需要新实验，应另建隔离目录和输出，核对解释器、依赖版本与文件 pin，记录路径改动。原结果记录 Python 3.11.5 和 Windows 平台，未记录 pandas 版本；未来环境不能假定完全相同。`matrix_clock.py` 及两份 JSON 是此前隔离矩阵原始记录，不是根代理串行性能测量，也不证明异步问题已修复。

## 原字节清单

下列文件从公开临时文件逐字节复制；清单不包含本说明和属性文件。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| head_vs_nocache_root_serial_20261122.json | 1980 | `e353ad4ab4b316f4fbbaec33c9c7415789c90a9ef11a346351ff3fec9f002b5b` |
| iter71_clock_root_serial_20261122.py | 1020 | `abe3a0c7aa343b40180fe09b31aea10628439c4ec751e1ae429f26bca3f666d4` |
| bench_clock.py | 994 | `7cdb4d5cbf8b1d023cf0a2584c7904fb9a40093a7bc0bfb2dff026eb67f4167c` |
| lineiterator-head.py.txt | 123417 | `5fb31f333fb7e01e0f1910bb17bb4095b431524f7bd54495bf4f2595b91f0271` |
| lineiterator-nocache.py.txt | 119623 | `024c4b7fb68ebd908a3983995d799184882158b52a5992c9796636c719c884b2` |
| uncached_delivery_formatted.patch | 6814 | `5b840d3ab2ff6dbafcbd687eb968fdb5785816e9bf2a5b37ac61c50ffa629fdd` |
| matrix_clock.py | 1394 | `db69f52af51b56e9812274ee30757292abc76bec4872c9864c1779df718e8242` |
| matrix_head.json | 1051 | `ce6988bd4eb467a9aa74194557ef6135163b901eca4912632b10d5412d192b6f` |
| matrix_nocache.json | 1051 | `ce6988bd4eb467a9aa74194557ef6135163b901eca4912632b10d5412d192b6f` |
