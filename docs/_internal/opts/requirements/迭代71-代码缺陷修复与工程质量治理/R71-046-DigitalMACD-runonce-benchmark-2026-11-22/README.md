# R71-046 DigitalMACD 串行性能样本

本目录保存 2026-11-22 Root 实际执行的一次公开数据基准。原始 `result.json`、`executed_driver.py` 和 `executed_worker.py` 均按原字节保存。代码已提交 Backtrader dev：`0ef1994c6b06a741c091e10cc2e194fffb51beb2`；对照基线是 `a2472f5b0baedf460de043847ab9f9189dc3a42f`。

本次使用 Python 3.14.2、NumPy 2.4.1 和 pandas 2.3.3，生成 8,000 根合成数据，在 `runonce=True` 下分别测量 signal 周期 5、256、1024，每组四对并交替先后顺序。每个样本独立启动 Python，包含 Cerebro 运行耗时；输入和输出哈希逐对一致。Root 在没有其他代理基准负载时串行执行，但未独占设备，计时受系统与硬件影响；这些结果不证明 next 模式、其他数据或其他环境的性能。

| signal 周期 | 基线耗时中位数（秒） | 候选耗时中位数（秒） | 四对候选/基线耗时比中位数 |
| --- | ---: | ---: | ---: |
| 5 | 0.155330 | 0.143239 | 0.9231 |
| 256 | 0.206803 | 0.145577 | 0.7039 |
| 1024 | 0.391572 | 0.178255 | 0.4565 |

周期 5 的测量波动较大，不据此声称默认短窗口获得稳定收益。每对原始值、环境、来源和哈希均见 `result.json`；表中耗时中位数的比值不等于逐对耗时比的中位数。

原始文件 SHA-256：

- `result.json`：`610a9fe3b54f1cf9f382da6b3fbba4e6527e76cc4a623223dcdbd8f898d55df6`
- `executed_driver.py`：`58988a4c30b4c8f40d347b75d5560f178f1c3cb212ab982b1a8e0a61fba779e8`
- `executed_worker.py`：`a3bd2e365d57ddad869176cd71726a3934ac5549ec96848d4eeb62de9e0dc8f7`
- 基线指标源码：`42b6595b25aa48c48570aa19ecb528eeeeb0d3c81dcd9404f5815184ae13e0b7`
- 候选指标源码：`d3e862d8beb9a36ae966677534f06f3c50cca9c53eed7e0a51904c5dcf99a386`

## 重建

原始 driver 固定写入旧临时路径，仅作执行证据，勿直接运行。`rebuild.py` 从上述两个固定 Git 提交归档公开 `backtrader` 源码，用归档的原始 worker 按同一周期、顺序和次数运行；它在系统临时目录创建全新目录，使用独占创建写入结果，不覆盖已有目录或历史证据。它校验两个指标源码、合成输入和各周期输出的 SHA-256，并要求相同的 Python、NumPy 和 pandas 版本。重跑所得时间会随环境变化，不能替代原记录。

两个 Git blob 都是 LF，但原实验使用的基线源码是 CRLF，候选源码是 LF；本机 Git archive 的换行投影还可能受配置影响。脚本核对两个 Git blob 后，仅在新建临时树内将指标源码恢复为原实验字节，并再次核对运行源码哈希。基线 Git blob 的 SHA-256 为 `af1bd8411c1811c393a5305260a76bed292f9624563f3329a7a98e783e381ffa`。

在仓库任意工作目录执行，只读核验提交、源码、worker 和解释器，不运行基准：

```powershell
& 'C:/Python314/python.exe' '<本目录>/rebuild.py' --check
```

确认要自行重跑时，去掉 `--check`：

```powershell
& 'C:/Python314/python.exe' '<本目录>/rebuild.py'
```

脚本打印新临时目录和 `reproduced_result.json` 路径；如果提交、源码、输入、输出或解释器版本不匹配，则停止，不覆盖原目录。也可用 `--python <解释器路径>` 显式指定 Python 3.14.2。此脚本不运行历史策略或其他已接受测试。
