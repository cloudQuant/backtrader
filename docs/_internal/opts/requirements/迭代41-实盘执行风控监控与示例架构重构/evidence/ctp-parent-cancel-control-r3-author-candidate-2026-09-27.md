# parent 撤单控制端 r3 作者候选（2026-09-27）

裁决：`AUTHOR_FAKE_FOCUS_PASS / INDEPENDENT_FIRST_RELEASE_REJECTED / NO_WRITE`。r2 后续审计发现：首次释放的注入授权回调可把时钟推进到命令过期后仍继续释放；首次 monitor append 返回值未做精确事件读回，append 后删行可留下 `RELEASED` 与已清锁；假证明门未核对 execution provider/account 的代码登记元组，人工构造的 CTP 标签可进入本地假门。r3 在新的隔离快照修复这些局部问题，保持 r2 字节未变。

r3 在授权回调后与最终风险锁释放前复核到期；首次 monitor 事件必须经精确只读读回；假证明 authority 在构造和使用时都核对代码登记的 strategy、execution provider、account、risk policy 及 offline replay 合同。作者聚焦 `15 passed`，到期、append 后删行、CTP 标签、错误账户以及最后锁释放前到期的负探针均保留零释放或两锁冻结状态。冻结 payload manifest SHA-256 `65af6f048a1148182b35a18b8998f738a306d83b5d33352bd469c809c3a8d28f`，证据 manifest SHA-256 `210394a328c01695c8616189314715157ca5879a715881d378ee6c9ee07cb391`。root 核对 154 项候选 payload、112 项证据的大小/摘要，并封存关键四个源码/测试文件与声明的证据至[原始归档](ctp-parent-cancel-control-r3-author-candidate-2026-09-27.raw.zip)：119 项，ZIP 完整性与内部摘要通过，SHA-256 `757031302dd302fe8e46af883df3c74b5ca5b7d70765bad4259f160493d5e215`。

独立 QA 已完成：冻结焦点独立复跑 `15 passed`（本冻结 manifest 展开为 15 项，不是 23）；本机并发 writer 可在 readback 后、最终清锁前删除 monitor event，而首次释放仍写入 RELEASED 并清除两锁，因此独立裁决为 `FIRST_RELEASE_REJECTED`。详见[独立 QA 回执](ctp-parent-cancel-control-r3-independent-review-2026-09-27.md)。主仓 bridge 的原三项失败/73 项焦点不属于本次独立复跑，仍不能据此接受。monitor 和 risk 仍位于不同 SQLite 数据库，精确读回后到最终清锁之间若有具写权限的外部进程篡改 monitor 行，r3 无跨库原子保护。注入授权回调也不是生产操作者认证或真实 CTP 终态证据。默认 CTP 撤单、模拟盘和实盘路由仍关闭。
