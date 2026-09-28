# Store / parent V2 本地源码切片验收

日期：2026-09-26。状态：`ACCEPTED_LOCAL_STORE_PARENT_V2_SLICE_ONLY`。
本记录保存各自真实测试时点，不将多个源码环境合并成统一制品验收。

## 已核对结果

| 范围 | 结果 | 执行来源 |
| --- | --- | --- |
| 主仓四个 Store/bridge 文件 | 60 passed，0 skipped | 独立 QA，execution V17 r1 冻结源码 |
| parent OrderRef consume 合同文件 | 41 passed，0 skipped | 独立 QA，最初 V17 冻结源码 |
| account-session V2 组合文件 r4 | 32 passed，0 skipped | 作者测试；root 核对 JUnit、日志及两文件 hash |

三个测试进程均记录一项已有 pytest 配置 warning。root 验证了 12 个当前源文件与相应回执 hash 一致，主仓四文件切片的七个源码/测试文件首尾 hash 一致。parent 三文件随后提交到本地 `e53b6b559bdc378d144cca5917814d0ac5beb2c1`；测试时 HEAD 仍为旧提交，验收绑定的是文件字节。原有四个 dirty gitlink 未包括在该提交中。

V2 把 Store 分配的正 int32 `OrderActionRef` 与逻辑 cancel/action 身份分开，使用单独的 native payload/hash 绑定。回调关联保留 RequestID、action ref、目标订单及会话的精确校验。逻辑 RequestID 若存在，必须与 Store binding 的 exact int 一致。

## 组合正验实际覆盖

作者的 `test_fake_store_to_sdk_partial_fill_cancel_terminal_order_return_preserves_fills` 经真实 Python Store/SDK 入口和 fake native API 完成：两次 submit、同源成交两手、目标五手订单的部分成交投影、fresh cancel target、Store 分配的 ActionRef 撤单、非终态 `OnRspOrderAction` ACK，以及原 SUBMIT 关联的终态 `OnRtnOrder`。撤单后成交和累计数量仍为两手且账本 MATCHED；目标终态后第三次 submit 到达 fake API。复用已消费的旧 cancel target 被拒绝。

这条正验只证明**目标终态之后**恢复提交的路径。目标仍为 OPEN/PARTIAL 时，仅收到 cancel ACK 就再次提交的账户级阻断，V17 尚未实现，另由 V18 开发与独立验收。fake CTP 状态及数量组合是源码形状夹具，不是厂商语义或真实交易证据。

## 来源与限制

- 独立测试使用显式源码路径及标明 SOURCE-ONLY 的 metadata。主仓测试用了 `--noconftest`；parent 单独运行并显式登记 `xdist_group` marker。
- 最初跨仓共同收集遇到 `tests/conftest.py` 同名导入冲突，随后改为两个独立进程。parent 另一次运行因 marker 未登记失败，最终日志保留修正后的通过结果。失败不是被当成成功或跳过。
- 独立测试进程未保存同进程模块 `__file__` 断言。另有此前独立 origin probe，但不能冒充本次 pytest 同进程来源证明。更严格的统一 source-root 广域复验单独记录。
- parent 回执保留重建的有效 pytest 命令，并明确原始 shell 命令文本未单独保存。
- root 未重复执行 32 项组合测试，也未把作者结果标成独立重跑。
- 未安装统一 wheel，未调用真实 native/provider，未接受外部授权、账户独占、默认 runner、模拟交易或实盘交易。

## 原始证据

[机器回执与逐文件 SHA-256](ctp-store-parent-v2-source-review-2026-09-26.json)；[原始源码、独立 JUnit/日志与作者组合 JUnit/日志](ctp-store-parent-v2-source-review-2026-09-26.raw.zip)。归档共 27 个条目，SHA-256：`ac4efc6c142ec876f18112aa59336afa2861ed33de9fd368e153329609fd7573`。
