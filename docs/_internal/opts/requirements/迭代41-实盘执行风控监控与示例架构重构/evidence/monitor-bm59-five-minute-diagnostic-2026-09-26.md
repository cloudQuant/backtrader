# BM59-M 五分钟诊断（Windows，2026-09-26）

## 结果与范围

**SMOKE_ONLY / NOT_ACCEPTED_FULL_MATRIX，exit 2。** 九项检查中八项通过，
`producer_kept_rate` 失败；不得将 CPU 单项通过写成 BM59 验收通过。
测试期间其余九个子代理暂停 pytest、构建及子进程测试；没有证据证明宿主的其他
外部进程也全部空闲。没有 provider、原生 SDK 或私有配置访问。

运行时间为 2026-09-26 11:34:38.773 至 11:39:47.318 UTC，总墙钟约 308.544 秒。
主脚本保持 SHA-256 `f9d89f460522eaf36b6ed7a70908d0ea05598d8de36cd0717f5218b7faef228d`；
临时副本仅将 smoke 的测量时长 3 秒改为 300 秒、warmup 20 条改为 1000 条。
20 events/s、32 条批次、100ms 消费轮询、50ms 资源采样、WAL/FULL、计量公式与阈值均未改。
临时脚本 SHA-256 为 `fb8b8da091ee0eed60bde081142eb6088e14bc1acc147aaa747c039b20ffdf36`。

使用已验安装环境 `D:/temp/iteration41-capability-risk-version-fix-20260926/consumer-venv-final`
的实际 Python 3.11.5。安装的 monitor `durable.py` SHA-256 为
`8a72fbdf2c0bb8bcce3fbe4d3a4c9d30a3fa6759424ebb692f6ed03f0eb10f23`；
其 wheel 来源见 [risk 替换后的 consumer 记录](risk-version-consumer-2026-09-26.md)。
本轮没有重建 monitor 或运行 monitor 包测试。

| 项目 | 结果 |
| --- | --- |
| 测量生产 / 消费 | 6000 / 6000，精确 event ID 集合一致 |
| warmup / 最终唯一行数 / checkpoint | 1000 / 7000 / 7000 |
| 丢失 / 重复 | 0 / 0 |
| CPU 单核百分比 | 4.0260417%，单项门槛通过 |
| lag p50 / p95 / p99 / max | 73.9322 / 126.1151 / 135.2471 / 219.9324 ms |
| 峰值 RSS | 46,268,416 bytes |
| 持久增量按 300 秒外推 | 605,159,424 bytes/day，非长期保留上界 |
| 资源样本 / 最大采样间隔 | 5442 / 172.1741 ms |
| 生产最大迟到 / 容许迟到 | 93.3955 / 50 ms，失败 |
| 最终排空 | 41.5413 ms |

## 原始计数与失败定位

CPU 起止计数分别为 703,125,000 和 12,781,250,000 ns，差值 12,078,125,000 ns，
除以固定的 300 秒得 4.0260417%。起始观察早于计划起点 68.0195ms，截止观察晚于
计划终点 41.2884ms，公式保留这些保守边界。原始正向 CPU 采样差值仍是
15.625ms 的整数倍；`GetProcessTimes()` 的名义 100ns 分辨率不能当作实际更新粒度。
本次结果不能抹去三秒 smoke 的 6.25% 失败，也不能用五分钟替代正式 30 分钟矩阵。

超 50ms 的生产迟到共四条，集中为两段：

| event index | 迟到 ms |
| --- | --- |
| 1057 | 93.3955 |
| 1058 | 89.0127 |
| 4604 | 80.0584 |
| 4605 | 68.2725 |

两段首条之前的 append 分别仅约 7.276ms、7.337ms，随后 origin 间隔为
143.094ms、129.802ms，额外时间发生在两次 append 之间的等待/调度区间。
首条自身 append 另耗约 45.595ms、38.193ms，加重了各段第二条的迟到。
另外有 14 条 append 自身超过 50ms，最长 89.9522ms，p99 为 23.2756ms。
这同时保留了定时调度抖动和同步 SQLite append 长尾两种观察。

目前没有 producer CPU、sleep-return、SQLite lock/fsync 或 OS scheduler trace，
不能精确判定每次暂停的根因。consumer lag 没有持续增加且全部事件及时排空，
但这不能排除瞬时锁或磁盘等待。未修改阈值，也未通过追加重跑选择通过样本。

## 可复核材料

- [原始结果](monitor-bm59-five-minute-diagnostic-2026-09-26-result.json)，SHA-256
  `4e48832730822d7f9f88d1174558e36aa07260fb122dcdeebc67f545c5e562bf`。
- [根代理复核与逐文件 hash 清单](monitor-bm59-five-minute-diagnostic-2026-09-26.json)，
  SHA-256 `4aba608c9efe968b9e0b8025d5b7e67ab605b18b58d1408a5f1b0cf44db67174`。
- [原始 CSV、脚本、差分与日志](monitor-bm59-five-minute-diagnostic-2026-09-26-raw.zip)，
  SHA-256 `a1d9aa6ad5ad9b990905c50f68f1f5a2c4741d9f13021b299523bcb690a5d7ff`。

测试数据库保留于本机临时目录，没有收入压缩包。Windows/Linux、每侧五轮配对和
每轮 30 分钟的正式矩阵，以及存储/电源模式和持久保留策略仍未验收。
