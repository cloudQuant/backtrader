# Backtrader Gateway 策略启动接线调整申请

状态：用户要求优先放在 Broker；暂不实施 Strategy 启动钩子。日期：2026-11-09。

后续选择：优先由 Broker/Store 在现有启动路径恢复编号并在 Broker 现有 next/下单调用中绑定；用户 start() 直接读取策略内部恢复状态早于 Broker 绑定的时序限制仍未解决，不能声称所有恢复均发生在 user.start() 之前。本文原申请保留作待审参考，不代表已经批准。

## 现状与问题

Store/Broker 启动先于 Strategy 实例创建；现有 Gateway Broker 绑定需要真实 Strategy、Feed、持久 host、合约和时间规则。Strategy 的私有 `_start()` 在实例创建和 Feed 关联之后、用户 `start()` 之前由 Cerebro 现有调度调用。目前没有通用的 Gateway Strategy 自动注册点，因此仅有 config.yaml 无法完成绑定和重启通知恢复。

在首个订单创建后才按 submit 懒绑定无法覆盖用户 start 前的重启恢复，也无法可靠恢复全局 Order ref 高水位。已批准的调整明确 Store/Broker 接线及 Strategy 私有通知钩子，但未明确增加 Strategy 私有启动钩子。

## 请求的限定调整

1. 在现有 `Strategy._start()` 中用户 `start()` 前增加一个仅显式 Gateway 配置启用的私有委托，交由已绑定 Store/Broker 安装该 Strategy 的现有 Gateway 消费/通知绑定及恢复；继续使用 Cerebro 原有调度，不新建调度器，不修改 Strategy 公共 API 或用户回调顺序。
2. 由已批准的 Store/Broker 启动路径在创建 Strategy 前获取策略状态 run lock、验证身份并调用现有 `SequenceAllocator.restore_ref_basis()`；失败拒绝 Gateway 启动，不放宽 E020 锁，也不对 direct/回测路径生效。
3. 用户策略 `__init__` 中若试图在 Gateway 绑定前下单，明确拒绝；不能偷偷走 direct 或创建未持久化订单。Strategy/Feed/持久 host/绑定不匹配时启动失败，不伪造恢复或准入成功。
4. 保持用户 `start()`、`next()`、`stop()` 的现有生命周期和顺序；启动失败按现有资源清理路径关闭所拥有的 Gateway facade，不关闭借用 host。真实账户及凭据仍由独立 Gateway 服务管理。

## 检查范围

真实 BT + 独立 Gateway + 合成 provider，从公开配置启动，在 Strategy 用户 start 之前恢复旧订单及通知，再验证正常下单；覆盖启动异常清理、重复启动、未绑定下单拒绝、direct/回测不受影响及 ref 高水位。真实 CTP/账户另按既定授权验收。
