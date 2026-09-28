# Managed notional allocation sizing

`bt.sizers.NotionalAllocationSizer` sizes against a strategy's local risk
allocation. It requires a managed `BtApiBroker` with an attached allocation
reader and an optional `bt_api_risk` build providing `allocation_sizing`.
The current implementation is an Iteration 41 source candidate; adding the
sizer does not register or enable a CTP trading route.

## Configure the sizer

Supply an already reviewed instrument registry, an explicit Decimal limit
price callback, and the clock used by that registry's metadata:

```python
cerebro.addsizer(
    bt.sizers.NotionalAllocationSizer,
    strategy_id="strategy-a",
    instrument="FUTURE",  # Must equal the data feed's name.
    registry=reviewed_instrument_registry,
    limit_price=bounded_limit_price,  # (data, isbuy) -> Decimal
    clock_ns=metadata_clock_ns,      # () -> int
)
```

The callback must return the price bound used by the intended order. The sizer
does not infer a price from the last close. It uses the registry's multiplier,
adverse-price allowance, fees and quantity step to round the suggestion down.
Missing, stale or differently denominated metadata raises an error. A complete
allocation too small for one permitted lot returns zero.

## Read the allocation

`broker.get_strategy_allocation(strategy_id)` reads the attached runtime's
current local reservation ledger without refreshing provider balances:

| Snapshot field | Meaning |
| --- | --- |
| `revision` | Allocation version used by the risk gate |
| `allocated_notional` | Strategy's configured notional ceiling |
| `used_notional` / `reserved_notional` | Occupancy retained by the local ledger |
| `available_notional` | Remaining local notional budget |
| `notional_unit` | Explicit valuation unit, for example CNY |
| `source` / `completeness` / `reason` | Whether this local view can be used |

This view is advisory. Another order may reserve the same budget after sizing;
submission must still pass the gate's atomic account and strategy checks with
the current allocation revision. A custom sizer can propose any quantity, but
it cannot bypass those checks. Allocation installation belongs to the account
authority, outside strategy sizing.

`getcash()` and `getvalue()` keep their existing account semantics. This sizer
does not calculate margin, remaining position capacity, closing quantities or
provider account equity. Allocations requiring a remaining-position view are
rejected. Complete real-account and CTP acceptance remains separate.
