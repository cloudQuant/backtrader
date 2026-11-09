# 第二十八轮：Broker 与 Strategy 通知接线审阅

日期：2026-11-09。状态：**限定本地通知接线源码/安装验证通过；生产消费链及整期未验收**。用户已批准 E048；本轮复用原 pending v4、R25 真实对象 codec 和原 Strategy Trade/通知算法。Gateway 仍按既定方案独立于策略进程、默认使用 bt_api_transport_zmq，本轮本地通知测试不证明整套服务已可用。

## 实现与范围

BtApiBroker 新增显式 Gateway 通知绑定、逐事件 arm、恢复、重投和本地 ACK 准入检查。保存真实 Order/Position/Trade、通知/历史引用及费用已应用序号；正常、quicknotify 和费用回调前持久提交同一 pending 批次，全部回调成功后再确认。费用阶段成功不会单独确认整个批次。重启重投保留稳定通知 ID，不重新计算成交或费用；已确认批次不重投。

Strategy 只增加委托原 Broker 的私有通知接线与异常处理，追加入口在修改队列和 Trade 前检查重入条件；原 Trade 更新与 Cerebro 调度不变。未绑定保持原行为。绑定限定原 PID、Thread 对象、Strategy、Feed、Order 和 host；direct/managed/旧恢复模式互斥，关键操作持续拒绝其他 owner 的同 Feed 订单。该 Position 检查依赖相关订单保留在原 Broker 容器中，显式调用方仍负责真实对象和事件投影，不能据此证明账户归属事实。

本地 dev 产品提交：`ed125f81fcf2784d274ad7cd798785bb4c276fba`，仅六个本轮源码/测试文件，未推送。合同见[§30](../分轮合同冻结稿-2026-11-08.md#30-r28broker-与-strategy-的通知事务接线)，通知钩子授权见[批准记录](../Backtrader-Gateway通知持久化钩子调整申请-2026-11-09.md)。未实施 E020 跨目录锁。

## 审阅与修复

E062–E069 已在本轮限定范围修复：冻结已校验费用输入；内存更新后的持久写失败保留同一候选或锁定重开；费用预检失败不能被普通通知确认；初次与重投回调均防重入；模式互斥不再依赖启动/绑定顺序；后加入的其他策略订单不能污染投影；线程 ID 复用不能更换绑定线程；原追加通知入口在任何状态变化前拒绝重入。异常 abort 只结束 active 回调阶段、保留 pending，不能覆盖原异常。详见[裁定记录](../evidence/round28-20261109/review-triage.json)和[问题记录](../开发问题记录.md)。

首次候选虽然源码873 passed/1 xfailed，仍因审阅发现缺陷未接受；第二候选源码889 passed/1 xfailed也因 E069 未接受。最终入口修复另由独立审阅者定向6项通过，模式/归属/线程修复在第二候选有独立4项通过。没有把既有测试通过当作缺陷不存在的证明。

## 最终验证

主代理源码与隔离安装使用**相同58文件**，最终各 **897 passed、1 strict xfailed、1 warning**，退出码0。覆盖真实框架对象、独立新解释器恢复、普通/quick/费用通知、替换前后故障、回调/确认失败、稳定ID、CAS、重入、模式/归属/线程及既有 direct/框架通知回归。工人最终联合7文件175 passed/1 strict xfailed，属于补充证据，不能与主验重复累计。

strict xfail 对应既有 BtApiBroker 构造器在 _normalise_startup_account_state 导入 bt_api_py；屏蔽 SDK 时纯模块导入通过，但构造无 SDK 不支持。warning 为当前 pytest 配置项提示。真实账户、生产事件消费、网络 ACK、完整依赖解析、跨平台及完整 test-fast 未在本轮验证。

主代理独立核对62冻结输入、684源码清单行、81测试/helper行及4公开数据清单行；去重765路径均对应最终产品提交。BT wheel 的680个 payload成员（679 Python、1公开配置）与原仓、构建副本、安装目标逐字节一致，README metadata原字节匹配。wheel SHA256 为 `3435b1df02d50bdb5a6135605a86cc6de4b8a85c715d13885a8c04e7a7ba6981`。

固定R26 SDK/CTP等依赖wheel继续使用；Monitor/ZMQ仍为已记录的editable。源码和安装各记录41进程，均有guard、无已记录来源违规，其中各13个缺退出审计；不能据此宣称覆盖全部子进程或拥有操作系统沙箱。原生扩展复用既有字节，没有真实连接或账户调用。

[最终源码证据](../evidence/round28-20261109/source/)和[最终安装证据](../evidence/round28-20261109/install/)保留命令、选择器、输入/成员SHA、原始日志、JUnit与来源审计。candidate1/2目录保留未接受候选、六个受托文件快照及失败记录。candidate1复制脚本漏tracked integration helper；candidate2安装876 passed/13 failed/1 xfailed，13项均因漏复制公开 iter28_loop_baseline.json。最终脚本显式复制并哈希绑定该基线，测试断言不改。早期Strategy夹具的12项失败只有原会话工具记录，未伪造原始日志。

产品限定diff-check通过。中文文档为UTF-8 BOM，严格解码与本地链接检查通过；Windows PowerShell5.1默认读取未执行。原始证据尾部空白保持原字节。

## 仍需完成

生产消费者尚未把稀疏事件接到 Order/Position、原 Strategy 回调、通知确认和远端 ACK；Store/Feed/SDK完整facade及YAML装配仍需接线。CTP成交自然日、实际费用、完整策略经济账本和可信财务视图不能由合成输入代替。此次只证明显式本地通知端口，E023及完整E048链路不关闭。

其他租约/控制/代理、示例/Web、多策略SimNow及综合验收继续按主计划；正式14步仍13 GAP/1 NOT_RUN，整期 IN_PROGRESS。回调允许稳定ID的至少一次投递，不承诺任意用户副作用恰好一次，也不持久化分析器任意内部状态；不防御任意Python直接改写内部对象或绕调底层inner。
