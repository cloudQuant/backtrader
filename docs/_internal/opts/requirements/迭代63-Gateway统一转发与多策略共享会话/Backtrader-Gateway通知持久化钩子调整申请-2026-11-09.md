# Backtrader Gateway 通知持久化钩子的限定调整申请

日期：2026-11-09。状态：用户已于 2026-11-09 明确批准上述限定调整，实施中、未验收。原 pending、Broker/Store 接线批准继续有效；本申请只新增下列 Strategy 私有通知接线，不要求全面重构。

## 源码依据

Cerebro 的既有 `_brokernotify` 先调用 Broker.next，再将取到的 Order 交给 `Strategy._addnotification`。后者才用执行片段更新真实 `_trades`。普通通知随后在 `_notify` 投递，quicknotify 在 `_addnotification` 内直接调用 `_notify`，费用更正则在 `_apply_fee_corrections` 内直接调用用户、分析器和观察器的费用回调。

既有 `_NotificationRecovery` 包装器可在普通 `_addnotification` 返回后观察 Trade，但 quicknotify 的用户回调已经执行；它还持有独立通知 SQLite，不能作为 R24 pending 原子事务。managed paper receipt 绑定专用成交合同，不能把 Gateway 回报伪装成 paper receipt。

因此，仅修改 Broker/Store 无法在全部既有通知路径上保证：真实框架状态更新 → 同一 pending 文件保存投影与待通知记录 → 用户回调 → 确认通知。R24 已完成持久端口，但尚未增加以下 Strategy 钩子。

## 请求批准的具体范围

1. 在 `backtrader/strategy.py` 的私有 `_notify` 方法中增加仅显式 Gateway 恢复模式启用的提交与成功确认钩子，委托给已绑定的 Broker。提交在 `_notify_inner` 用户回调之前，成功确认在原回调全部正常返回之后；异常保留待通知记录并传播，不自动 ACK 或继续交易。
2. 在 `_apply_fee_corrections` 的既有费用通知路径增加同类提交/确认接线。Gateway 费用更正须与新增成交分开表示，不能在一个未完成的成交投影中途提交。原费用计算和 `Trade` 更新逻辑继续复用，估计费用与实际费用不混为一谈。
3. 钩子的具体对象编码、请求/事件身份、投影与待通知记录、幂等恢复均由 Broker 的 Gateway 分支和原 pending v4 持久机制实现；Strategy 不获得 SDK 客户端、网络调用、凭据、原生日切或账户账本。没有注册该模式时，原 direct、回测和 managed paper 行为保持原合同。
4. Broker 只有在真实 Order/Position/Trade 投影已经耐久保存后才能显式推进 Gateway 事件 ACK。用户回调允许按稳定通知 ID 至少一次恢复；回调已执行但确认尚未落盘时可能重投，不能承诺用户任意外部副作用恰好一次。

不修改 Cerebro 调度、策略公共生命周期、订单和持仓的核心算法，不新建第二套 Trade 更新算法、事件调度器或通知数据库。本申请不包含 E020 的跨目录状态归档锁调整，该申请独立保留。

## 可审阅的接线位置与检查

- `Strategy._notify`：在既有 `_notify_inner` 前后各增加显式 Gateway 分支委托；保留既有 managed receipt 分支与异常语义。
- `Strategy._apply_fee_corrections`：在每次原费用通知的用户回调前后委托，失败时保留可恢复标记。
- Broker：验证当前 Strategy、Order 所属与事件范围，只处理本实例注册的 Gateway 事务；缺失、错绑定或不完整投影拒绝，不能跳过持久化。

实现后覆盖普通/quicknotify、部分和终态成交、迟到成交、费用更正、回调异常、持久写入前失败/替换后报错、重启重投与重复事实；真实 `Order`、`Position`、`Trade` 必须保持一致，远端 ACK 不提前。并回归原 direct、框架通知与相关策略测试。合成进程验证仍不替代实际账户或完整迭代验收。

批准记录：用户答复“批准上述限定调整”。可按以上范围实施 Strategy 私有通知钩子，无须重复申请。本批准不包括独立的 E020 跨目录状态归档锁调整；整条通知恢复链仍需实现和验证。
