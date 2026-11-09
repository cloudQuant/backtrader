# 第二十九轮：SDK 显式 Gateway 入口审阅

日期：2026-11-09。结论：本轮限定实现及本地源码/隔离安装验证通过；整期仍 IN_PROGRESS / 未验收。SDK 本地 dev 提交 `643734fab65c3dd0598998a561f18d6d963b4882`，未推送。BT、Base、CTP、Gateway 和 ZMQ 产品本轮未修改。

## 交付范围

`BtApi.from_gateway` 惰性创建独立 `GatewayBtApi`，复用调用方提供的原 GatewayStrategyClientSession，不运行 direct provider 初始化，不创建第二套线程、连接或持久宿主。默认传输保持 bt_api_transport_zmq。显式委托预留、派发、原键状态、释放、撤单及状态、事件流、已配置账户/命名行情/合约规格端口；缺能力明确拒绝。

命令继续返回原类型和原结果，不将 QUEUED 或 SENT 解释为订单 Accepted、成交或撤单完成。`idempotency_key` 是持久请求键，`client_order_id` 不替代它；route 名与原生 exchange_id 不混同。读取事件不会自动 ACK。此入口是能力 facade，尚不满足普通 UnifiedBtApiFacade 的完整映射合同，也不是现有 Store 的即插即用替代品。

borrowed close 只关闭 facade；owned close 仅关闭原 runtime，保留未完成或异常后的重试和原不确定性，不关闭 durable host。检测绑定漂移后仍拒绝业务，原进程的状态和清理可以访问构造时捕获的 runtime，不跟随替换对象。

详细合同见[冻结稿 §31](../分轮合同冻结稿-2026-11-08.md#31-r29显式-sdk-gateway-能力入口)。共提交 2 个产品文件、3 个测试文件和 README。

## 审阅发现与处理

- E070：候选把业务绑定检查置于 close 之前，身份漂移后无法清理原 runtime。独立审阅用未启动合成会话复现；已启动线程的资源滞留只作控制流推导。修复后独立定向复核确认 borrowed/owned 行为与业务拒绝均正确。
- T015：旧测试以字符串前缀匹配退役 gateway 命名空间，误含合法 gateway_api 等模块。修正为精确根或点分隔子模块，保留前后均为空断言；没有以单独运行隐藏联合失败。
- T016：首轮来源 guard 改变不存在模块的 find_spec 返回语义。主代理同14文件首次为 296 passed/1 failed；最小复现确认是临时验证脚本。仅对四个精确退役名称允许已确认缺失返回 None，保留原失败、脚本与审计，新目录同输入复跑。

原工人集成测试首次误读计数器，修正合成 provider 下单叶子的计数后通过，失败记录保留。安装镜像为旧测试根目录假设建立到精确安装 target 的包链接，未复制源码替代安装包。完整 wheel 辅助校验还保留两次 RECORD 路径/pycache 假设失败；pip 重写的 RECORD 不是原 wheel 字节，入口脚本记录路径与 --target 实际位置的差异已单独记录。

## 验证证据

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 最终源码，同14文件 | 297 passed，2 warnings | 合成单元、独立 Gateway 进程、真实 CURVE 回环、账户读取委托、原键派发/撤单、显式 ACK、身份和关闭故障 |
| 最终隔离安装，同14文件 | 297 passed，1 warning | 相同选择器和测试字节；固定依赖 wheel 加新 SDK wheel |
| 主代理字节与 Git 核对 | PASS | 17 个冻结输入；314 个源码和35个测试/helper共349路径；与最终提交逐字节匹配 |
| 包内容 | PASS | 309 个 SDK 包文件与源码副本、工作树和安装目标完全一致，成员集合一致；README 原字节在 metadata 中匹配 |
| 来源审计 | PASS，有限范围 | 源码/安装各7个已记录进程，均有 guard 和退出审计，无已记录违规；不是完整沙箱或所有进程覆盖证明 |
| Ruff / diff-check | PASS | 产品、测试及中文文档；原始日志的空白按原字节保留 |
| Markdown | 见文档检查记录 | 严格 UTF-8/BOM、无替换符、相关本地链接；Windows PowerShell 5.1 NOT_RUN |
| 真实账户、原生交易调用、完整平台/依赖解析 | NOT_RUN | 不外推本地合成与安装结果 |

源码额外 warning 是现有 pytest asyncio 配置项未加载；另一项与安装相同，为既有 Quandl 弃用提示。没有跳过或预期失败。ZMQ 和 Monitor 仍为已记录 editable 依赖，CTP native 仅复用既有扩展且工厂受测试 guard 限制，不是重新编译或 native 连接验收。

新 SDK wheel SHA256：`5d356b565675411947dfa0f1b73e0845e7c2cc707d24a2323e183957eb8046f0`。

原始日志、脚本、失败候选、来源审计和新 SDK wheel 以 [证据 manifest](../evidence/round29-20261109/manifest.json) 逐文件标识。重点记录：[源码最终结果](../evidence/round29-20261109/source-final/sdk-source.log)、[安装最终结果](../evidence/round29-20261109/install/sdk-installed-v2.log)、[主代理提交核对](../evidence/round29-20261109/source-final/primary-delivery-committed.json)、[独立审阅摘要](../evidence/round29-20261109/review-summary.json)。脚本保留当时绝对临时路径；复现需按 manifest 和提交重新建立对应输入，不能把归档路径直接当现成安装环境。

## 剩余工作

完整 Store/Broker/Feed 接线、生产事件投影/通知确认/网络 ACK、可信配置到独立服务及策略的完整启动、资金/费用/今昨仓经济账本、控制/代理、示例/Web 和整体验收仍未交付。E049 自然日期/实际费用与 E020 归档并发调整仍开放；后者仍需原限定范围外的批准。本轮不关闭 63.05/63.06，正式14步仍13 GAP、1 NOT_RUN，不能据测试数计算完成率。
