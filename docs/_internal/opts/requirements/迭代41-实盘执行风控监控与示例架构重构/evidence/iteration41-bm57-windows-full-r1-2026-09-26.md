# BM57 Windows 五轮完整采样（2026-09-26）

**Windows 阈值通过；Windows/Linux 完整矩阵尚未验收。** 每侧每轮每个操作预热 1,000 次、采样 10,000 次，共五轮，交替 baseline/candidate 先后顺序。根代理逐项复算十份原始记录的百分位与五轮配对中位数，未删除任何轮次。

| 指标 | candidate / baseline 五轮比值中位数 | 上限 |
| --- | ---: | ---: |
| submit p50 | 1.005146 | 1.05 |
| submit p99 | 0.981908 | 1.05 |
| cancel p50 | 1.002840 | 1.05 |
| cancel p99 | 0.976987 | 1.05 |

第一轮 submit/cancel p99 比值为 1.4552/1.4915，第四轮为 1.1133/1.0689；原始波动全部保留。通过依据是预先定义的五轮配对比值中位数，不是每轮都低于阈值。

baseline 为 `ad2c142b…` 的 468 份 Python 文件，tree hash `a40c1e27…`；candidate 是该 HEAD 上的 480 份工作树文件，tree hash `69b4a5e4…`，运行前后相同。两侧 revision 字段相同不代表代码相同，完整身份由回执中的文件树摘要区分。基准脚本和 runtime contract 哈希也在运行前后相同。

命令使用隔离 Python 执行 `scripts/run_iteration41_direct_benchmark.py --full --baseline-source-root D:\temp\iteration41-bm57-baseline-ad2c142b-20260926 --candidate-source-root D:\source_code\backtrader --output-dir D:\temp\iteration41-bm57-windows-full-20260926-r1`。当时已结束并行策略 pytest；运行前后两秒 CPU 观察为 2.2%/6.6%，32 逻辑核。这不是全程负载记录或专用性能机器证明。

全部十个子进程 exit 0；hot loop 无额外配置读取，无记录到的 socket/thread API 尝试。测试使用 synthetic replay 与 fake API，未验证 CTP native/provider 延迟，也未开放交易路由。Linux、BM59 完整长时矩阵及未来源码改动仍需单独验收。


## 原始证据

- [机器回执](iteration41-bm57-windows-full-r1-2026-09-26.json)
- [原始证据包](iteration41-bm57-windows-full-r1-2026-09-26.raw.zip)，SHA-256 `a54575f6edcd7af635dc224292206813b784d90958b4eda784c41d61f948319f`。
