from pathlib import Path
root=Path('/Users/yunjinqi/Documents/new_projects/backtrader/docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话')
report=root/'archived/实施第三十一轮BT稀疏事件消费与通知恢复审阅-2026-11-09.md'
text='''# 迭代63第三十一轮：BT稀疏事件消费与通知恢复审阅

日期：2026-11-09。状态：本轮验收收口中；整期 **IN_PROGRESS / 未验收**。本轮沿用已批准的pending/Broker/Store接线和Strategy私有通知钩子范围，复用原Order、Position、Trade及Strategy通知时点。E020跨目录统一锁协议未实施。本报告中的独立Gateway进程使用合成provider，不是CTP或账户验收。

## 1. 交付范围及明确限制

- SDK增加显式GatewayExecutionTimePolicy，严格自然日期与HH:MM:SS按配置的IANA时区解释为UTC，拒绝非法、歧义或不存在的时刻。缺字段保持未知，已提供的非法字段不能因另一字段缺失而被忽略。没有provider/本机默认时区；摘要不固定tzdb版本，解释不证明原始时区、时钟或freshness。
- BT增加显式SDK执行流消费者，按实际请求上下文持久接收稀疏事件，核对完整instrument、请求、原始BT ref和时间规则；复用原Broker成交及订单状态计算。先消费可解释的本地事件；缺日期时可有界读取后页的同成交日期补充。每轮最多投影一条，用户通知确认后才请求远端ACK；UNKNOWN不推进水位。
- 日期补充通过无通知检查点保存，不新增成交、持仓、Trade或费用。普通通知路径以及旧v1批次的ACK/恢复均拒绝metadata-only混用。
- Strategy原_notify入口协调已持久通知重投，消费者不在Broker.next提前执行用户回调。保留原通知ID、至少一次回调、普通/quick/fee顺序和失败栅栏。
- pending显式v4→v5保存提交前单个真实Order的codec描述，与规范意图及local_seq/bt_ref在原pending文件原子提交；原execution水位规则不放松。同key内容幂等，不同key复用原ref拒绝。完整首次提交和首事件前恢复尚未接入该端口。

这是已有订单的显式消费能力和提交前持久端口，**不是完整config-only Gateway模式**。当前bind需调用方提供真实SDK session/host、原Order、Feed、instrument和时间规则；submit/cancel仍明确拒绝未装配的写适配。E077本地Submitted/Rejected耐久通知、E080资金/持仓getter旧刷新隔离及完整Store/Feed装配仍开放。E074、E023、E049整体不据此关闭。

## 2. 审阅发现与处理

| 编号 | 发现及本轮处理 | 证据边界 |
| --- | --- | --- |
| E075 | metadata-only可走普通v1通知而未保存日期就允许ACK；入口、prepare/commit、fee入口、ACK与恢复均增加检查 | 原复现和修后1项及7项独立定向检查留存；不是全状态空间证明 |
| E076 | 不同意图可保存同一原BT ref；schema5全量读取及原子保存拒绝碰撞 | 独立验证拒绝后原字节不变、同键幂等、不同ref可存、篡改重开拒绝；跨代编号仍须提交适配使用原SequenceAllocator协调 |
| E078 | 日期补充的已知time与原成交矛盾仍可拼接日期/时间 | pending落盘和消费者解释双层检查；独立原复现修后按预期拒绝 |
| E079 | 已保存的下一事件被额外read_after UNKNOWN阻塞 | 已完整本地事件优先，必要时每轮只读一页；独立确认ACK未知仍阻止下一投影、缺日期可读取后页 |
| T018 | resume提前改变原FAULT错误，或在fee_ready阶段重复fee回调 | 恢复原错误合同和原通知阶段；旧R28断言保持 |
| E077/E080 | 本地提交通知与旧账户读取入口尚未完整接线 | 已登记为下一段必要开发，未用测试夹具掩盖为完成 |
| E081 | 既有Broker分支10处未定义command，另3项旧未使用导入 | 主代理与原HEAD逐诊断、源码行核对；本轮未改，保留OPEN |

## 3. 验证范围

最终选择器固定为BT65文件、SDK20文件，覆盖direct提交/恢复、pending迁移与身份、原对象codec、普通/quick/fee通知、Cerebro通知回归及本轮独立Gateway进程。

独立进程场景使用真实spawn Gateway、Registry/CURVE/SQLite、SDK command/session/facade及先后两个客户端解释器；provider和执行事实为合成。覆盖回调失败时远端ACK=0、进程重开后同ID通知重投而不重复持仓/Trade、确认后ACK推进、日期补充无额外数量/通知、最终满量及完整instrument错配拒绝。它手工准备已有订单，不证明配置驱动提交或真实provider运行。

待最终原始日志和提交核对完成后，在此补入精确结果。初始源码为BT984 passed/1 strict xfailed/1 warning，SDK382 passed/2 warnings；预期失败沿用原Broker构造器SDK依赖。四个测试只调整14个fixture为显式同名导出，不改产品或断言；最终BT源码/安装须同集复跑。Ruff新owned问题已清零；全文件仍保留E081的13个基线诊断，不能写成全量lint通过。

## 4. 验收脚本修正与保留证据

初版安装镜像未覆盖跨目录、相对和动态helper导入：先发生复制脚本失败，再发生22项收集错误，再为959 passed/25 failed/1 strict xfailed；另一次刚启动的合成测试由验收代理停止以固定输入，exit2，不属于产品失败。原日志、清单与镜像版本保留。最终镜像合并R28/R30已通过的helper清单、补齐新子解释器tests路径和来源guard；65文件collect-only已收集985项。未修改产品或断言来处理这些镜像错误。

源码/安装来源守卫与offline guard仅覆盖有记录的Python进程和相应接口，不是完整OS沙箱。安装ZMQ、Monitor仍保留显式记录的editable来源；固定CTP扩展复用R30/R19已核对构件，未编译也未连接原生账户。全部源码副本、测试/helper、wheel成员与Git核对完成后补充清单位置。

## 5. 未完成范围

完整策略config-only启动与下单/撤单、首事件前自动恢复、策略资金和实际费用、external与可平账本、完整断线/跨日/UNKNOWN恢复、租约/控制/代理、11个示例和Web、性能/平台与授权SimNow仍按正式14步验收。E020仍只限制其未获批准的锁调整。没有真实账户或保留host操作，没有推送、发布或新建worktree。Windows PowerShell5.1读取验证为NOT_RUN。
'''
assert not report.exists()
report.write_text(text,encoding='utf-8-sig')
print(report)
