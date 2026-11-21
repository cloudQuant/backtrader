# StochasticHistogram WIP 隔离复核与 HOLD 交接

日期：2026-11-22。状态：**HOLD，未验收、未暂存、未提交**。本记录只涉及公开源码、公开历史行情及合成输入；不构成账户或实盘能力证据。

## 基线与原有未提交内容

- 固定对照：Backtrader 公开 Git 基线 `47ad807087424b38ed10d30d54637de5c08453be`。复核期间共享 dev 的 HEAD 继续变化；本记录不声称当前 HEAD 仍为该版本。
- 原 dirty 源码 `backtrader/indicators/contrib/stochastic_histogram_indicator.py`：18,406 字节，SHA-256 `56ed0ee7f6cbd8ce59770bb8c5bcacd9481789816b17e444c5efd639dcbc0627`。
- 原 untracked 专项 `tests/unit/indicators/test_iter71_stochastic_histogram_execution_modes.py`：22,855 字节，SHA-256 `4fcdc91c3db6256282e7f531119563a289df7c0a3f3bce14b80eb3af66fe19d3`。
- 原源码相对基线的 diff：14,389 字节，SHA-256 `5572ff3ddd5daec85bf183162f823ec8f72c0384f26f2783c6b99a4c28d1b9fd`。原始源码、测试及 diff 的公开隔离副本位于 `C:/Users/yunji/AppData/Local/Temp/i71-stochhist-wip-47ad/`。源码差异为 313 行新增、2 行删除，包含预热、受限缓冲、同 bar 修订、动态 hook 回退和输出回滚；不能把它当作已接受的单一小改动。
- 本次结束前复核，共享工作区上述两文件仍为原始哈希；没有修改它们或 Git 索引。此前交接中的完成表述与本次实际 dirty 状态不能混同。

## 已验证事实

原 WIP 与原专项叠加公开基线，在独立快照中连同历史策略 `tests/functional/strategies/trend_following/test_0092_0926_stochastic_histogram.py` 为 **28 passed，1 条既有 Quandl 弃用警告**。同一基线上，原专项中四种均线及缺失行情相关的 9 项失败；例如默认示例首次有效位置的流式值为 NaN，而独立公式期望约 63.9307384。独立审阅另对下文所列冻结合并实验源码（SHA-256 `8e102c71765f3677d0b4083fcf39372c83b0c641a6f2f4d62b619196cd5cf903`），在有限值下覆盖四种均线、四种 K 周期、三种平滑组合及 `exactbars=0/1` 共 96 组；这不证明 strict 或所有时钟合同，也不能据此认定原 WIP 已全面通过。

真实 `FactorStrategy` 的源表保持有限，在 Feed 第 12 根将 high 或 low 的底层线槽注入 Inf：HEAD 的逐根模式抛 `FactorComputationError`，其 cause 为 `ArithmeticError`；原 WIP 因流式路径直接读数组而静默成功、上下文未标记失败。批量模式下 HEAD 与原 WIP 均静默成功，是既有独立缺口，不能算作本次引入。复现脚本 `C:/Users/yunji/AppData/Local/Temp/i71_stochhist_strict_injected.py`，SHA-256 `a59ed4931511fcbeb2adce4fa072eed5597ce6be22a474129c2197875908a9b7`。独立审阅进程记录了被捕获的环境探测拦截，不能称零拦截。

历史策略对照脚本 `C:/Users/yunji/AppData/Local/Temp/i71_stochhist_history.py`，SHA-256 `0bd184d8a8dd0beae27512aac6c00b696fa83e4d37ab72317bd5057d1f6d95d6`。所测 next/once 新旧均为 570 条订单通知、190 条交易通知，事件摘要均为 `ba17a101602fa9ba6bc1235c2a407130d03f1b50a9f695142dce5f6b58bd5f23`，最终权益均为 1001042.20。HEAD 的 next 全量指标及汇总摘要为 `5880f6483df47914b16834af8cb16978e23b04d4b9325dc3a916f911ef69740d`；隔离候选的 next 与两侧 once 摘要为 `c0297707e11cc9fa77c67f5ec4bda07611378bac56b2a041816ad34d1c489dcc`。这些是公开历史回测通知，不是真实账户事件。

## 两个阻断反例

1. **真实 strict 输入窗口被扩大。** 原始表数据有限，在第 2 根的 high 线槽注入 Inf，参数 `k_period=3, slowing=1, d_period=1`。该槽在第一次指标计算前已滑出 HEAD 实际读取的窗口：HEAD 的真实 `FactorStrategy` 逐根运行成功；第一版独立窄候选由于从头回填而抛 `FactorComputationError`。后来合并实验让 strict 上下文走旧路径，此样本恢复成功，但不能因此声称 strict 的流式/批量数值一致。脚本 `D:/temp/i71-stochhist-review-668ba460/strict_expired.py`，SHA-256 `68c45a8aac64f97be25a035eede75bca7f9a3b2a3498f06626e7f01b5c997074`。
2. **阈值回调改写未反映到递推状态。** 真实 Cerebro、有限恒定行情、EMA 平滑，`high_level.__float__` 首次被求值时将当前 main 线写为 7。HEAD 第 8、9、10 根 main 为 `[7.0, 35.666666666666664, 45.22222222222222]`；合并实验为 `[7.0, 50.0, 50.0]`：虽然当根写入顺序已修正，私有平滑状态仍保留回调前的值。脚本 `D:/temp/i71-stochhist-review-668ba460/threshold_ema.py`，SHA-256 `dd485b635e78de3321024bb0a3171d5bb29ba6023b125cc9b37ff214079869b1`。该反馈行为尚无接受的修复。

审阅还发现合并实验首版直接调用固定的 legacy 方法，绕过用户 WIP 子类的 `_next_legacy` 覆写；后续隔离修改恢复实例分派，定向自测通过，但该修改尚未完整独立复审。阈值回调仍是阻断，不能以该项自测取代验收。

## 隔离候选与恢复方式

- 从 HEAD 独立做的受限第二套流式原型：`C:/Users/yunji/AppData/Local/Temp/i71-stochhist-limited-47ad/`；源码 SHA-256 `79811481435d2244cdab9a9ad3d8bb38c636c22ac14ffd0e1c38246deb1ffe6e`，新增测试 SHA-256 `1f9819385694f9bc8b80f29609a9cdc76e8ef53265a4a53d22c557e30d0acd08`，补丁 SHA-256 `3f453b6d5be77bda63e2ab06bd155feafd115cc5170bfad86254838b3f790641`。该补丁不能直接应用到现有 WIP；三方预览有 5 处冲突。此方案已被保留原 WIP 算法的合并实验取代，不应集成。
- 原 WIP 的隔离合并实验：`C:/Users/yunji/AppData/Local/Temp/i71-stochhist-wip-projected-47ad/`。曾冻结的相对原 WIP 增量 `wip_overlay.patch` SHA-256 `4a9b6c6da20ed0fd50ca4b8c5dce48b0c1e048876694fdec16df8c80666b129d`，在原 WIP 隔离副本上通过 `git apply --check`；对应审阅冻结源码 SHA-256 `8e102c71765f3677d0b4083fcf39372c83b0c641a6f2f4d62b619196cd5cf903`，保存在 `D:/temp/i71-stochhist-review-668ba460/projected/backtrader/indicators/contrib/stochastic_histogram_indicator.py`。
- 上述合并实验后来为子类分派做了隔离修订：当前该目录源码 SHA-256 `ebbc0b93d2bf0927b27ef0347a46e92a7cf2484f0b2f81ce734c3b687f3de62a`，新测试 SHA-256 `49599de28f77ed52b83f7c491e74ee1c87089d495c8bdab3787324ca51013c9b`。自测原 WIP 专项、新专项及历史策略 **49 passed，1 条既有警告**；它不是上面的冻结补丁版本，也没有完整独立通过，阈值递推反例仍存在。不要把它覆盖到用户工作区或当作可提交成品。
- 已知开放项包括 strict 指标双模式 parity、批量 strict 中间溢出、非有限值和复杂多 Feed/replay 组合。未来应先确定如何在保留原 WIP 的同时恢复动态回调与严格读取合同，再在公开隔离快照重新运行公式、受限缓冲、真实时钟、策略通知和独立复审。