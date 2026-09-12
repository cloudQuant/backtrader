# 迭代24 文档入口

本目录定义 CTP 期权期货中频三腿候选的目标合同，并记录了本地合成 replay 切片。`examples/014_2_ctp_options_midfreq/` 是一个可从自身目录直接运行的单策略：它用 Cerebro、BackBroker 和合成的一分钟 C/P/F 数据验证本地 next-only 普通决策、因果窗口和零外部写。

该本地结果仅为 `LOCAL_REPLAY_PASS`。完整 BtApiStore→BtApiFeed→BtApiBroker→CTP 链、安装消费者、第一套只读、SimNow、真实订单/成交/实际 PnL、OOS 和生产均未验收；G1 为 `INCOMPLETE`，G2/G3/G4/R1/R2 为 `NOT_RUN`，production 为 `NO-GO`。

1. [初始需求](初始需求.md)：保留原始诉求。
2. [需求文档](需求文档.md)：范围、功能与非功能约束。
3. [设计文档](设计文档.md)：目标公共 owner、分钟因果与本地回放边界。
4. [验收文档](验收文档.md)：局部本地验证与完整 Gate 的分层验收。
5. [公共架构与基线](../迭代23-CTP期权期货低频套利策略/公共架构与基线.md)：三迭代共享的能力、资金、scope 和证据边界。

运行时不得 import、读取或隐式依赖任何其他 `examples/` 目录的代码、fixture、状态、审批或公共包；012/013 仅可做设计参考。真正共用能力只能进入 `backtrader`、`bt_api_py` 或 `bt_api_ctp` 的明确 owner，或保留在唯一消费它的策略目录内。
