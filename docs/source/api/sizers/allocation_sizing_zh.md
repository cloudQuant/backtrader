# 受管策略名义额度 sizing

`bt.sizers.NotionalAllocationSizer` 按策略的本地风险额度计算建议数量。它要求
`BtApiBroker` 已连接受管 runtime 的额度读取接口，且可选的 `bt_api_risk`
版本提供 `allocation_sizing`。当前属于迭代 41 源码候选；配置这个 Sizer
不会登记或启用 CTP 交易入口。

## 配置 Sizer

传入已审核的合约注册表、明确返回 Decimal 限价的函数，以及合约元数据使用的时钟：

```python
cerebro.addsizer(
    bt.sizers.NotionalAllocationSizer,
    strategy_id="strategy-a",
    instrument="FUTURE",  # 必须与 data feed 的名称一致。
    registry=reviewed_instrument_registry,
    limit_price=bounded_limit_price,  # (data, isbuy) -> Decimal
    clock_ns=metadata_clock_ns,      # () -> int
)
```

价格函数应返回该笔订单实际采用的价格边界。Sizer 不从最新收盘价推断限价；它复用
注册表的合约乘数、不利价格余量、费用和数量步长，向下对齐建议数量。元数据缺失、
过期或计价单位不同会报错；完整额度不足一手时返回零。

## 读取额度

`broker.get_strategy_allocation(strategy_id)` 读取当前受管 runtime 的本地预留账本，
不会刷新 provider 余额：

| Snapshot 字段 | 含义 |
| --- | --- |
| `revision` | 风险门采用的分配版本 |
| `allocated_notional` | 策略名义金额上限 |
| `used_notional` / `reserved_notional` | 本地账本保留的已用量和预留量 |
| `available_notional` | 剩余本地名义额度 |
| `notional_unit` | 明确的计价单位，例如 CNY |
| `source` / `completeness` / `reason` | 当前本地视图是否可用及原因 |

该视图提供建议。计算数量后，其他订单仍可能占用同一额度；实际提交必须使用当前
分配版本，通过账户与策略双限额的原子检查。自定义 Sizer 可以提出越额数量，但
硬风险门仍须拒绝。分配额度由账户 authority 管理，不属于策略 sizing 的权限。

`getcash()`、`getvalue()` 保留原有账户语义。这个 Sizer 不计算保证金、剩余持仓容量、
平仓数量或真实账户权益；需要剩余持仓视图的分配会被拒绝。真实账号与 CTP 的完整
交易验收须另行完成。
