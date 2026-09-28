# BM59-M 测量脚本与 smoke

## 当前结论

新增 `scripts/run_iteration41_monitor_benchmark.py`，用真实独立 Python monitor 进程
运行现有 `DurableOutboxConsumer`，另一个进程负责固定速率的合成事件生产。默认参数
为 1000 条 warmup、20 events/s、1800 秒和最多 30 秒收敛；`--smoke` 固定为
20 条 warmup、20 events/s、3 秒。脚本仅创建本地测试 SQLite 和证据文件，无 provider
或私有配置入口。

2026-09-26 完成的 smoke 为 **SMOKE_ONLY / exit 2**，CPU 测量超过 5% 单核门槛。
没有运行正式 30 分钟 profile；此时其他开发/测试也在进行，不能视为串行性能验收。
BM59-M 仍未通过，五轮及双平台矩阵均未完成。

## 测量内容

- 生产事件使用同机 `perf_counter_ns` 绝对计划时点；保存每条计划、实际进入 append、
  append commit 时间，调度最迟容差为一个 50ms 周期，不能通过延长生产期掩盖降速。
- consumer 使用现有逐条 SQLite 事务 ACK，fake sink 仅在内存记录身份；每次最多处理
  32 条。lag 到达真实 checkpoint 已提交之后，批次结束时点对早期记录作保守上界。
- 原始消费样本和资源样本在计时结束后写 CSV。CPU 为子进程 CPU 时间 / 单调墙钟时间，
  不除以 CPU 核数；50ms 采样 RSS，Windows 同时使用 `peak_wset`。
- 对照 consumer 唯一事件数、数据库 row/distinct 数和最终 checkpoint；warmup 与测量
  使用不同事件 ID，测量事件 ID 必须与合法 index 一一对应。
- 持久增长按 SQLite 已分配页比较，另报含 WAL/SHM 的峰值文件大小。统计读取显式关闭
  连接，避免读连接残留使 WAL/SHM 生命周期污染最终增长。
- 保存真实模块来源、`durable.py` SHA256、解释器、SQLite、psutil、CPU 核数和 RAM。
- 内存 fake sink 没有外部通知 I/O。进程内网络/native/private-config guard 不是 OS 隔离。

monitor 当前没有 retention/prune API，本次所有记录均保留。脚本明确记录这一事实；
30 分钟采样也不能证明有界保留策略。存储类型、文件系统、电源模式、fsync syscall
计数、另一平台和五轮比较仍需补齐，单次结果固定输出 `NOT_ACCEPTED_FULL_MATRIX`。

## 审查前 smoke（本机临时证据 c）

| 项目 | 结果 |
| --- | --- |
| monitor 固定源码 | `82e5282ea6aff6a52874f5cf62e86a8df984bde0` |
| base 固定源码 | `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f` |
| warmup / 测量 / 最终数据库行数与 checkpoint | 20 / 60 / 80 |
| 丢失 / 重复 / 网络或原生访问尝试 | 0 / 0 / 0 |
| checkpoint lag p50 / p95 / p99 | 18.4642 / 30.7466 / 35.7015 ms |
| CPU（单核百分比） | 18.703365%：超出 5% 门槛 |
| 峰值 RSS | 47,165,440 bytes |
| 持久增长按短样本外推 | 588,356,990.68 bytes/day，仅短样本观测 |
| 生产最大调度延迟 / 排空耗时 | 13.9092 / 7.4802 ms |
| Ruff / Black（显式 py311） | 通过 |

原始目录为 `D:/temp/iteration41-bm59-smoke-20260926-c`，包含 result、consumer summary、
生产/消费/资源 CSV 与测试数据库。`result.json` SHA256 为
`0357c44da9551d6538611a6eebc29aa63c6cb38f3aa3545758f042f8c90641ee`。
该时点脚本 SHA256 为 `bd048c5450ae3b838daeba3b528c555aab573261962210aab89ab9834d623168`。
前两个 harness smoke 是开发过程记录；第二次发现了 SQLite 只读连接未显式 close 和
瞬态 WAL/SHM 基线不一致的测量问题，修复后得到 c 记录，未据它们宣称性能通过。

## 独立审查后的 smoke d

独立 reviewer 指出了仅验收到数量、生产结束时点及 drain 参与 CPU/磁盘分母可能导致
误判的问题。脚本随后补齐 SQL phase 行数和精确 checkpoint 对照、50ms 最大生产迟到
约束、append 延迟样本，并固定使用计划生产时长作 CPU/磁盘归一分母。CPU 使用到
计划结束后首个观测的保守上界，单独记录 drain CPU；资源最大采样间隔超过 250ms
会使测量检查失败。退出码 0 至多代表一次局部阈值检查，下游必须检查 JSON 的
`acceptance`，不能把它解释为完整性能验收。

该时点 `d` 的结果仍为 **SMOKE_ONLY / exit 2**：60 条测量事件、20 条 warmup，SQL
phase/unique/总数和 checkpoint 全部一致，无网络/native 尝试。lag p50/p95/p99 为
17.6872/24.2786/31.5065 ms；CPU 保守上界 **15.1041667%**（门槛未通过），峰值 RSS
46,673,920 bytes，最大资源采样间隔 70.3841 ms；增长为 589,824,000 bytes/day
的短样本外推，生产最大迟到 5.4565 ms，排空 3.3269 ms。

目录为 `D:/temp/iteration41-bm59-smoke-20260926-d`。
`result.json` SHA256 为 `3a5523f7182d12d313b4242e84ee413586d15a14367db4ada50e81e8114dca62`；
当时脚本 SHA256 为 `0f9b3fd5900662acc53a54acd076905298eefc7c30d0e990b9eeea22dc8637f5`。
Ruff 与显式 py311 Black 均通过。该次仍不属于串行/长稳/双平台或完整 BM59 验收。

一次额外的定性 cProfile（200 次空 `consume`，非 BM 计时）共记录 0.341 秒，
SQLite `execute`/`close`/`connect` 分别占约 0.158/0.130/0.041 秒。空轮询每次均
重新建连、执行 PRAGMA/读取并关连接，是后续调查方向；这些 profile 时间包括等待，
不能直接当作 CPU 百分比或优化收益。脚本为
`D:/temp/iteration41-bm59-empty-poll-profile-20260926.py`，网络/native 尝试为零。

## 有界轮询调度 smoke e

脚本的消费调度从每 10ms 空轮询改为每批结束后 100ms 再读取，资源采样仍为 50ms；
每批最多 32 条，每条仍单独执行真实 WAL/FULL ACK，未改变库源码或持久性。
JSON 记录精确轮询间隔、批次上限与包括 warmup 的消费次数。该调度由 benchmark
进程实现，因为 public `consume()` 自身不含调度器，不代表部署监督者已经接线。

同一冻结 monitor/base 的 3 秒 smoke `e` 完整消费 60 条测量事件，SQL/checkpoint
均为 80，无重复和网络/native 尝试；总调用 30 次，其中空调用 2 次。
CPU 保守上界 **6.25%**，仍未通过 5% 门槛；lag p50/p95/p99 为
87.7277/141.8796/160.4990 ms，RSS 46,194,688 bytes，最大资源间隔 95.1101 ms。
生产最大迟到 28.8179 ms，排空 50.3177 ms，持久增长短样本外推仍为
589,824,000 bytes/day。阈值结果仅 CPU 为 false；不能用两次短测推导配对性能收益。

目录 `D:/temp/iteration41-bm59-smoke-20260926-e`；`result.json` SHA256
`2472d0d1a2ac414d7630e92d770fdf66be916d334493c191c3afbd858a1db3c9`；
脚本 SHA256 `802bef362cff5a22f5d419e271f7930503e63df54c82fe1c8a68cf3c1826f4fe`。
Ruff 通过。JSON 仍为 `SMOKE_ONLY / NOT_ACCEPTED_FULL_MATRIX`；PowerShell 包装命令
报告非零退出（1），Python main 的失败返回值为 2。本次没有正式性能验收。

## 批内连接复用候选与 smoke f

monitor 已保存 clean local commit **`f3583e744922d556a6015576f386c2d26e3aae51`**。
一次有界 `consume()` 复用一个短期连接，回调之前读完页面；每条 ACK 仍独立执行
`BEGIN IMMEDIATE` / 连续 cursor 验证 / `COMMIT`，保持 WAL/FULL。连接不跨调用缓存，
回调执行时不持事务。实例、子类和类级 public read/ack override 都走旧公开调用路径；
无效 read 参数在打开数据库前拒绝。

作者全包 **90 passed**。独立 reviewer 对初版优化全包 **86 passed**，然后对最后
两个 public 兼容修复窄复验 **4 passed**；未将这两次说成独立运行的最新全包。
真实 SQLite trigger 故障测试证明第一条 ACK 已持久、第二条回滚后重放、其余仍 pending；
handler 失败、回调重入 read/append、连接关闭与公开 override 均有验证。

根代理使用相同脚本 SHA `802bef36…1826f4fe` 对最终候选执行 smoke `f`：
**exit 2 / SMOKE_ONLY / NOT_ACCEPTED_FULL_MATRIX**，CPU 仍为 **6.25%**。
60 条测量和 20 条 warmup 的唯一行数/checkpoint 一致；无重复或网络/native 尝试。
lag p50/p95/p99 为 74.5517/124.7051/142.1750 ms，RSS 46,108,672 bytes，最大资源
间隔 81.6725 ms，排空 55.6317 ms，持久增长短样本外推 589,824,000 bytes/day。
31 次消费（含 warmup），空消费 2 次。两次短样本不能证明性能收益，CPU 门槛仍失败。

最终源码 `durable.py` SHA256 为
`72981948606b1d51d457d69734a24724538d2f16750972165b74dfa3ae81a073`。
目录 `D:/temp/iteration41-bm59-smoke-20260926-f`，`result.json` SHA256 为
`2357fb6e3fecb823883e6a17bb7d2cf92200acda998fb4fd8638bcc515c0fc7d`。

## CPU 短样本复核与后续诊断字段

独立只读复核确认 e/f 均为 **3 秒**、60 条测量事件。两份原始资源 CSV 的
`process_cpu_ns` 均落在 15,625,000 ns 格点；f 首尾为 640,625,000 与
828,125,000 ns，差为 187,500,000 ns，即三秒分母下的 6.25%。这支持存在
CPU 记账量化，不能证明结果虚高；每事件的持久 ACK 也可能实际消耗这些 CPU。
当前分子还保守包含计划起点前和首次截止观察时的 CPU，不能把短 smoke 当作
正式 30 分钟平均 CPU 裁决，也不能因为量化而忽略门槛失败。

随后脚本只增加原始诊断字段：CPU 起止/差值、实际起点与计划起点偏移、
截止观察超调以及 process-time clock 的 implementation/nominal resolution。
名义分辨率不代表实际记账更新粒度。计量公式、门槛、时长、状态和采样频率未变。
此后脚本 SHA-256 为
`f9d89f460522eaf36b6ed7a70908d0ea05598d8de36cd0717f5218b7faef228d`；
py_compile 与目标 Ruff 通过。后续已用此版本的临时副本完成[五分钟诊断](monitor-bm59-five-minute-diagnostic-2026-09-26.md)：CPU 约 4.03%，生产迟到四条超过 50ms，仍为 exit 2，未通过正式矩阵。

下一步先在其他测试/构建/磁盘负载停止后，以临时副本作五分钟诊断，保留
1000 warmup、20 events/s、WAL/FULL、32 batch 与 100ms cadence，并保存宿主负载。
该诊断不替代正式 Windows/Linux、五轮配对、每侧每轮 30 分钟矩阵。

## 运行入口

在明确的 frozen/installed monitor 环境中执行（输出目录必须尚不存在）：

```powershell
python scripts/run_iteration41_monitor_benchmark.py --smoke --output-dir <new-evidence-dir>
python scripts/run_iteration41_monitor_benchmark.py --output-dir <new-full-run-dir>
```

正式执行应排除其他测试和负载。CPU 短测超限需在串行环境复测，再决定是否优化消费
调度或连接寿命；不得降低 FULL durability、跳过真实 ACK 或把计时移到事务之后。
