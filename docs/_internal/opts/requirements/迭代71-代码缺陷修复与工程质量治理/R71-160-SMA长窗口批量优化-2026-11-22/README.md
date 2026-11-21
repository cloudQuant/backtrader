# R71-160：SMA 长窗口批量计算小轮

日期：2026-11-22。仓库：Backtrader，`dev`。源码与重点回归提交 `e25e59627`，父提交 `889a8ca64`。本目录记录该轮及原始性能证据；本记录的提交状态以实际 Git 记录为准。

## 范围与正确性

本轮仅优化 `MovingAverageSimple.once` 中可证明为共同二进制定点尺度且整数前缀和有界的长窗口；不满足条件时回退既有路径。原始逐窗合同是 `math.fsum(window) / period`。不修改 StdDev，也不声称加速 next、replay 或所有数据。快路径要求 NumPy 已加载；轻量导入中未安装 NumPy 可回退，不表示完整包默认导入无需 NumPy。

主代理在提交前现有 checkout 验证重点回归：Python 3.11 为 15 passed，Python 3.14 为 13 passed、2 skipped；跳过项使用的 `set_numeric_ops` 在 NumPy 2 中已移除。Ruff 和 diff check 通过。隔离独立复审为 GO_NARROW_BEHAVIOR：Python 3.11 为 80 passed，包含公开 NumPy 运算符替换、strict、非有限值和独立参考。独立 214160 个窗口与逐窗 `fsum` 的十六进制结果相同；公开 XAU 三均线策略子类在所测双模式、信号有无缺失下，与基线的指标及已记录订单、交易通知和终值相同。该策略是测试子类，缺失注入独立信号线；这是历史模拟证据。原始 Inf 在进入指标前可能被框架投影，原始数组层的回退不证明所有 Feed 保留 Inf。

隔离候选源码为 LF，SHA-256 `d8db3df6a348b89514f1611481668a0606f1403687a0d61bd233459eb355b830`；提交 blob 相同。现有 checkout 为 CRLF，原字节 SHA-256 `b1ee81d7d7b8b8ea95909d181faeda8474dac51083213e758c54ee6d6917cb6b`，仅 CRLF 归一化后与隔离候选一致。源码结果限所测 Windows、输入和公式约束；跨平台 `fsum` 舍入、并发重绑及主动篡改 NumPy 内部 core 不在本轮证明范围。

## 原始性能结果

主代理在没有其他代理基准负载时串行执行，但未独占设备。Python 3.11.5 和 3.14.2 各取公开 XAUUSD M15 数据前 30000 根，真实 Cerebro `runonce=True`，单 SMA 周期 512、八个 SMA 周期 512–568；每种场景四对，每对各一个基线和候选，顺序交替。计时覆盖 `cerebro.run`；准备 DataFrame 不在计时内。先验门槛：八 SMA 的中位数加速至少 5%，单 SMA 的中位数回退不超过 3%。以下比值均为候选耗时除以基线耗时，越小越快：

| Python | 场景 | 四个配对比值的中位数 | 候选耗时中位数 / 基线耗时中位数 |
| --- | --- | ---: | ---: |
| 3.11 | 1 SMA | 0.965726 | 0.938911 |
| 3.11 | 8 SMA | 0.910921 | 0.915184 |
| 3.14 | 1 SMA | 0.904092 | 0.901255 |
| 3.14 | 8 SMA | 0.885791 | 0.886469 |

两种统计下均达到该先验门槛。单次波动仍存在：3.11 单 SMA 的第 3 对候选比基线慢 10.29%，不能把中位数结果解释为每次运行都更快，也不能外推至其他数据、机器或负载。worker 不记录快路径命中次数，输出只以数组字节的 SHA-256 对照；逐对哈希相等不能替代保存并逐值比较输出，也不能据该基准单独证明快路径实际被触发。快路径命中与逐槽正确性来自上面的独立回归，而非此性能脚本。

固定证据（原始字节；本目录局部 `.gitattributes` 的 `-text` 规则保留这些字节）：

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `bench_serial_r4_driver.py` | 1366 | `2d41d4cc255d7e60d3dd2dbd071cc2abb3a38892317d2802f404ad181f31d2f7` |
| `bench_serial_r4_worker.py` | 1602 | `7c326e9d5f478d48c1474fc2f47a1a08f4d24e46042500814bbb3608989e6ea3` |
| `sma_r4_root_gate_311_20261122.json` | 11415 | `5c13b388384b2a02cb9411bd421d30fe7a151073f06be8247aa5f333a633d3ab` |
| `sma_r4_root_gate_314_20261122.json` | 11178 | `fab02d755e8bd7c33b5371a0433a9b0228b72d1989153f8ae5984959c5f0dac6` |

每份 JSON 保存 16 条运行记录、数据和源码哈希、Python 版本、平台、耗时与输出哈希；driver 在每对结束核对两个输出哈希。公开 CSV 原字节 SHA-256 `d364dea806a6ef634277184d1edc71fb90216fadacf673f70ea9706c55a1f51f`。性能基线取公开 Git `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d` 的隔离快照；其 SMA LF blob 与父提交 `889a8ca64` 相同（`6bc3b96143d5af26c3201ccb78393daca70ca447317e348887fee357b38e836f`）。基准所用基线源码实际为 CRLF，原字节 SHA-256 `c7e8fa855a97a5befb5ae20871f1a2ac90c97ebfa38e9f9e1a87284a18f2b487`。候选快照使用同一基线其余文件，只替换 LF SMA 源码为上面的提交 blob。

## 重建方法

原始 driver 固定使用 `D:/temp/i71_sma_pair_opt/baseline` 和 `candidate`，并验证上述原字节哈希。只在这些路径不存在的干净环境运行；如果已存在，保留原目录，不覆盖、不删除。需要 Git、tar、对应 Python 及其 NumPy、pandas 等依赖。重复实验不保证相同耗时。

1. 从仓库根目录将 `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d` 用 `git archive` 分别解包到上述两个新目录，避免通过 PowerShell 文本管道传递 tar 原始字节。确认 CSV 原字节哈希与上文一致。
2. 用二进制方式读取同一提交的 `backtrader/indicators/sma.py` LF blob，确认不含 CR 后将 LF 替换为 CRLF，写到 `baseline` 对应位置，核对 `c7e8fa85…`；用二进制 `git show e25e59627:backtrader/indicators/sma.py` 的 LF blob 写入 `candidate`，核对 `d8db3df6…`。不要以 PowerShell 的文本重定向写二进制 blob。
3. 将本目录 driver 和 worker 原字节复制到新建的 `D:/temp/i71_sma_pair_opt` 根目录。执行下列命令；结果文件必须不存在，driver 以独占创建方式写出。

```powershell
C:/Python314/python.exe -B D:/temp/i71_sma_pair_opt/bench_serial_r4_driver.py C:/Python314/python.exe D:/temp/i71_sma_pair_opt/new_314.json
C:/anaconda3/python.exe -B D:/temp/i71_sma_pair_opt/bench_serial_r4_driver.py C:/anaconda3/python.exe D:/temp/i71_sma_pair_opt/new_311.json
```

原始证据记录历史实际运行，不因重新执行而改变。
