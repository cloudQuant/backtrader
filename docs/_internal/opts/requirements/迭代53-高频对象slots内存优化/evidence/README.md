# 迭代53：隔离对象布局诊断

日期：2026-10-24（Asia/Shanghai）。状态：**DIAGNOSTIC_COMPLETE_NOT_ACCEPTANCE**。

本目录提供[迭代计划](../迭代计划.md)的初步量化依据。生产源码没有添加slots；所有生产候选的功能/性能验收仍为NOT_RUN。

## 文件与复现

- [benchmark_slots.py](benchmark_slots.py)：一次性诊断脚本，读取公开类源码，通过AST重建隔离类，只在原型中插入slots；不导入或替换生产类。它不是正式Cerebro基准工具。
- [layout-probe.json](layout-probe.json)：100,000对象/进程、128对象预热、每类每原型3轮配对，共36个独立串行子进程的原始结果。
- [review-smoke.json](review-smoke.json)：主线程审阅脚本后独立复跑的小样本，1,000对象/进程、每原型1轮配对，共12个子进程；仅验证诊断工具。

完整复现命令（在仓库根目录执行，输出到一个新的临时目录，避免覆盖本次证据）：

```bash
slots_probe_output=$(mktemp -d /tmp/backtrader-slots-repro.XXXXXX)
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python \
  docs/_internal/opts/requirements/迭代53-高频对象slots内存优化/evidence/benchmark_slots.py \
  --repo /Users/yunjinqi/Documents/new_projects/backtrader \
  --output "$slots_probe_output"
```

脚本使用base中已有的psutil。CLI固定完整诊断规模，小样本复核通过导入脚本后调用 `_run_parent(argparse.Namespace(repo=..., output=新目录, count=1000, warmup=128, repeats=1))` 完成；该私有入口不属于Backtrader接口。原始JSON保留当时的临时目录和PID，用作溯源，不要求这些临时路径永久存在。

## 基线

| 项目 | 实际值 |
|---|---|
| Git HEAD | `01555f804db818fdd987e35da8175d58258dc25b` |
| Python | CPython 3.11.8，conda-forge |
| 系统 | macOS-26.5.1-arm64-arm-64bit |
| order.py SHA-256 | `717b980d2afdf0a6a335b1071b867a73fee7a6e3fef019577a800f166b56ab19` |
| position.py SHA-256 | `b921772e74628a50e3dfe68a523e4211f1ec15b056a4a86a9a9cde8013d790f1` |

三类位于两个源文件，JSON按类及按唯一文件分别记录哈希。未读取真实配置、凭据或私有捕获。其他工作区修改未进入隔离类定义。

## 方法与数据

每轮按baseline→原型或原型→baseline交替执行，各自新进程。strict包含固定字段和弱引用槽；hybrid另保留实例字典。baseline同样从原始类AST重建，没有添加槽；不通过继承原有带字典类伪造“无字典”原型。

测量前构造128个对象预热后释放并GC。启动tracemalloc，再创建并持有100,000个默认对象；先记录traced current/peak，停止tracemalloc后读取RSS。随后才检查样本字段、弱引用、对象壳/字典大小及扩展属性；这些检查不计入所报分配量。OrderData的成交deque及单次add/pending检查也在测量后执行。

tracemalloc retained bytes中位数：

| 类 | baseline | strict | hybrid | strict / hybrid每对象差值 |
|---|---:|---:|---:|---:|
| OrderExecutionBit | 25,600,952 | 20,800,952 | 24,000,952 | 48 / 16 bytes |
| OrderData | 100,000,976 | 95,200,976 | 98,400,976 | 48 / 16 bytes |
| Position | 15,201,048 | 11,201,048 | 14,401,048 | 40 / 8 bytes |

表内包含列表以及构造实际产生的对象/负载；常量可能共享。本样本两组baseline的traced中位数相同，不意味着其他指标或不同输入也完全相同。

RSS增量中位数，单位MiB：

| 类 | strict配对baseline | strict | hybrid配对baseline | hybrid |
|---|---:|---:|---:|---:|
| OrderExecutionBit | 60.125 | 43.750 | 51.969 | 47.422 |
| OrderData | 95.516 | 121.516 | 93.969 | 99.422 |
| Position | 30.828 | 18.578 | 27.047 | 29.797 |

RSS包含开启/关闭tracer与分配器的影响，不是无tracing峰值；OrderData和Position hybrid存在反方向结果。原因未定位，不能把这些数据当正式性能通过或把反例删除。构造耗时也在tracing下测量，不能据此声称更快或更慢。

## 主线程复核与限制

主线程审阅了AST字段收集、property/backing映射、类重建、预热、采样顺序和配对检查，并独立核算了上述中位数与差值。`OrderData.plimit` 被排除出槽列表，setter写入的 `_plimit` 保留；字段数分别为14/18/8，不含布局控制槽。

完整样本和独立小样本均得到六项诊断检查true：抽样字段配对一致、weakref可用、OrderData deque保留、strict拒绝未知属性、hybrid允许扩展、hybrid固定字段不在字典内。主线程还核对了隔离baseline与实际生产类默认构造字段、两个源文件哈希及归档脚本一致性。

这些检查不覆盖全字段外部赋值、非默认输入完整状态空间、copy/deepcopy/pickle、子类、恢复、交易、Cerebro或生产RSS。strict会收窄现有公共对象扩展能力；hybrid仍改变vars/字典反射。`OrderParams`及其他候选未测，3.8–3.13矩阵未跑。不能把本目录标记为迭代53功能或整体内存验收通过。
