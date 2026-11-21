# StochasticHistogram 受限修复小轮

日期：2026-11-22。状态：**已提交，限定源码及隔离复审范围**。本记录承接同目录的《StochasticHistogram WIP 隔离复核与 HOLD 交接》；历史 HOLD 记录原样保留。此次结果不代表 B11-03 整项、全部交易场景、账户或实盘能力完成。

## 范围与字节

- 仓库及分支：`D:/source_code/backtrader`，`dev`；提交 `d7af1dcb18e362ddf5c4413c702daf5af0ddd9ac`，父提交 `5f41176ca9da0c66faeb800e32c13858e43a47ef`。提交恰含指标源码、原 WIP 专项测试及新增专项测试三个路径。
- 原用户 dirty 指标源码 18,406 字节，SHA-256 `56ed0ee7f6cbd8ce59770bb8c5bcacd9481789816b17e444c5efd639dcbc0627`；原 untracked 测试 22,855 字节，SHA-256 `4fcdc91c3db6256282e7f531119563a289df7c0a3f3bce14b80eb3af66fe19d3`。提交中的原测试 blob 与此哈希完全一致。
- 基于原 WIP 的隔离增量补丁 `stochhist_wip_repair.patch` SHA-256 `db95efa5f6e0eb80f7f9b638fbdde2155d146aa55654d40f2929ff40819a0917`；它依赖上述原 WIP，不是可直接应用于干净 HEAD 的独立补丁。作者报告在原 WIP 隔离副本上 `git apply --check` 通过。该补丁位于公开临时目录 `C:/Users/yunji/AppData/Local/Temp/i71-stochhist-resume-535e/`，不是本提交的永久归档内容。
- 隔离测试源码与提交后工作区源码的原始字节相同，20,680 字节、SHA-256 `207d60abea4fbe3c04e6f83b70eaa5d856daa2ffedf8d585ccc88768ab692d2e`；提交 blob 是 LF 格式，20,176 字节、SHA-256 `46b932882ae1fdce915ac15a1935702cb3455c16c875d5e58b3817b323761da7`。二者统一换行为 LF 后逐字节一致。新增测试提交 blob 与隔离测试原字节一致，SHA-256 `bec55719ffc1d8312f6896f2ba6ff37159728f7b9ffb6e7097b2ba5fd83d2145`。
- 修复保留原 WIP 的流式算法和受限缓冲处理，调整 strict 检测及线读取、自定义阈值回退、阈值读取与输出写入时序，并在进入 strict 后使已有流式缓存失效。原有输出线写入失败恢复仍以对应专项验证为准。

## 测试和复审证据

- 作者在公开 Git `535eaa80e9aa5b4a8002855f4f3b61da8e585e28` 隔离快照及补丁独立应用副本，分别以禁用插件自动加载、`--noconftest` 和禁用 cacheprovider 的 pytest 运行原 WIP 专项、新专项及一项公开历史策略，各为 **59 passed、1 条 Quandl 弃用警告**。补丁应用副本耗时 4.92 秒。环境设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH` 指向对应快照；命令使用 `python -B -m pytest -q --noconftest -p no:cacheprovider -o addopts=''` 和三项测试路径。作者命令未安装额外文件、网络或私密访问 guard，不能称为 guarded 测试。
- 独立复审另在该固定公开快照，用 Python 3.11.5、pytest 8.4.2、`--noconftest` 和禁用外部插件自动加载运行两份专项：原 WIP 测试 27 项、新测试 31 项，**58 passed、1 条 Quandl 弃用警告**。历史策略那一项没有在这次独立 pytest 中重跑。先前独立 harness 首次因 pytest capture 访问 `os.devnull` 被文件 guard 拒绝，在收集前终止；第二版仅增加 `-s` 禁用 capture，未放宽 guard，得到上述结果。隔离进程禁止网络及子进程，私密路径读取自检被拒绝；每进程另有 3 次库的文件写探测被 guard 拒绝并被调用方捕获，因此不能写成零拦截。
- 独立有限数据检查覆盖 4 种均线、4 种 K 周期、3 组 slowing/D 参数和 `exactbars=0/1`，共 **96 组、0 组失败**。这是针对冻结候选的独立公式检查，不能推断所有参数、缺失值或时钟组合通过。测试工具输出为结果来源；保存的 guard JSON 只记拦截类别，不单独绑定源码或测试结果。
- 真实 `FactorStrategy` 公开合成数据中，当前窗口 high 的 Inf 逐根触发 `FactorComputationError`，cause 为 `ArithmeticError`；第 2 根已在第一次计算前滑出窗口的 high Inf 未导致失败。附着在线 owner 的 strict context 能被识别并转入旧路径；所测 WIP 子类回退分派保持。自定义阈值将 main 首次写为 7 的有限行情 EMA 样本，后两根分别约为 35.6667 和 45.2222，与 HEAD 所测行为一致。
- 作者的公开历史回测对照中，所测 next 与 once 均有 **570 条订单通知、190 条交易通知**，最终权益均为 **1001042.1999999995**；事件摘要 SHA-256 `ba17a101602fa9ba6bc1235c2a407130d03f1b50a9f695142dce5f6b58bd5f23`，候选两个模式完整摘要 SHA-256 `c0297707e11cc9fa77c67f5ec4bda07611378bac56b2a041816ad34d1c489dcc`。该对照是作者结果及公开历史回测证据，不是真实账户通知；HEAD next 的完整指标及汇总摘要与候选不同。作者脚本 `C:/Users/yunji/AppData/Local/Temp/i71_stochhist_history.py` SHA-256 `0bd184d8a8dd0beae27512aac6c00b696fa83e4d37ab72317bd5057d1f6d95d6`，分别以 `next`、`once` 参数运行；该脚本未安装额外访问 guard。

## 行为边界

- strict 或非精确内建 `int`/`float` 的自定义阈值会使用 legacy 路径；已有缓存后进入 strict，以及遇到自定义阈值后，继续沿用该回退。此范围不声称已经修复 next/once 数值一致性。
- 自定义阈值的 `__float__` 抛异常时，候选按 HEAD 的旧路径先写 `main` 和 `signal` 再抛；原 WIP 是先转换阈值并保留旧槽。这是明确的可见行为变化，不能表述为完全保留原 WIP 的异常语义。它与原 WIP 对输出线写入失败的回滚测试是不同场景。
- strict 批量模式既有缺口、有限输入造成的中间溢出、strict 流式与批量 parity，以及复杂多 Feed/replay 组合仍开放。本轮不证明完整交易策略、所有市场数据或真实账户验收。
