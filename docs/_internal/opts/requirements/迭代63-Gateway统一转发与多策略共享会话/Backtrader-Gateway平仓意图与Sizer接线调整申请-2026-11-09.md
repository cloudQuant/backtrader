# Backtrader Gateway 平仓意图与 Sizer 接线调整申请

日期：2026-11-09。状态：用户已明确批准下述限定调整；实施和验收进行中。

## 问题与职责

下单、撤单、策略持仓读取、可平校验、订单恢复和 Gateway 调用都继续由 `BtApiBroker` 与 Gateway 负责。策略 helper 只表达用户原本选择的操作，不连接 Gateway、不持有账户事实或签发授权。

当前 `Strategy.close()` 的双向持仓分支已传 `offset=close`，但净仓分支直接调用 buy/sell，未携带平仓意图；`order_target_size()` 等目标仓位 helper 也会直接调用 buy/sell。Broker 收到一般买卖单时，无法可靠知道它来自平仓 helper 还是策略主动反向开仓，不能仅凭方向或当前持仓猜测原生开平。

另一个缺口是现金型 Sizer：`Sizer.getsizing()` 在没有策略账本时把 Broker 的 cash 传给任意 `_getsizing`；Gateway 策略资金未就绪时 Broker 返回 NaN 表示未知，但任意自定义 Sizer 仍可能忽略该值并返回数量。不能声称 NaN 自动阻止使用未知资金的仓位计算。

## 请求的限定调整

1. 仅当 Broker 已明确选择 Gateway 模式时，让现有 `Strategy.close()` 在净仓分支显式传递 `offset=close`，不覆盖策略已显式提供的合法开平意图；由 Broker/Gateway 继续核对策略持仓、方向、可平归属和 venue 原生规则。
2. 仅 Gateway 模式下，目标仓位 helper 在已有可信本策略仓位基础上，明确区分缩减现有仓位和增加同向仓位，并向 Broker 传递对应明确意图；跨零既包含平仓又包含开仓，不悄悄合并成单个订单，先明确拒绝，后续若支持拆分须另有完整订单身份与生命周期合同。目标金额/百分比在可信策略资金、估值及规格缺失时保持不可用，不用账户总资金替代。
3. 在 `Sizer.getsizing()` 增加仅 Gateway 模式启用的有限前置：声明 `uses_account_cash=True` 且可信策略现金不可用/非有限时明确拒绝，不能调用 `_getsizing`；声明不依赖现金的 Sizer 保持原路径。Broker 仍提供策略资金视图及其不可用原因。
4. 不改变 public 方法签名、Cerebro/Order/Trade 调度，不新增交易 owner 或第二账本；回测/direct、未绑定Gateway及现有非现金 Sizer 行为保持。Gateway 实际平仓仍须策略级可信基线、原子容量复核和 provider 原生 CLOSE；未选 Risk 时按计划执行，不强制引入 Risk。

## 验证

真实框架对象下覆盖净仓/双侧 close、增减仓及跨零拒绝、已显式指定意图冲突、未知策略持仓或现金、现金/非现金 Sizer、Gateway 下单和回报；同时回归 direct 与回测。合成基线不代替实际 CTP 同切点证据。此申请不涉及 E020 锁或真实账户操作。

用户批准记录：答复“批准上述限定调整（推荐）”。批准只覆盖本申请的 Gateway 条件分支，不扩大到其他框架重构或 E020 锁。
