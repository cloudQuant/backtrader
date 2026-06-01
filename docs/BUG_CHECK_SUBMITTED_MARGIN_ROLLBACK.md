# BUG 报告：`check_submitted` 在多资产再平衡中错误保留被拒订单的 trial cash / position 副作用

## 结论摘要

**结论：是的，你怀疑的方向是对的，但需要更精确地描述。**

问题不只是“`master` 在 `check_submitted` 时会顺序占用保证金/现金”，而是：

- `master` 在 `check_submitted()` 中对每一笔订单做 **pseudo execution**
- 如果某笔订单 trial 后现金变成负数，它会把该订单标记为 `Margin`
- **但是它没有回滚这笔被拒订单对 `cash` 和 `position` 造成的 trial 副作用**
- 于是后续同一批次的订单会在一个**已经被污染的现金/持仓快照**上继续判断
- 最终导致：
  - 本来应该可以成交的后续订单，也被错误标记为 `Margin`
  - 多资产组合调仓时，某些买单会被级联错杀
  - 组合路径、持仓路径、成交次数、净值和风险指标全部漂移

因此，**根因是 `check_submitted` 对“被拒订单”的 trial 状态没有回滚**。

这比“顺序占用保证金”更精确。

- **顺序试算 / 顺序预留** 本身不是 bug，属于一种合理的提交校验策略
- **被拒订单仍然污染后续校验状态** 才是 bug

---

## 现象背景

在 `tests/functional/strategies_regression/asset_allocation` 中，以下策略在 `dev`/`master` 比较时出现明显差异：

- `0018_optimal_gold_allocation_strategy`
- `0019_crypto_optimal_allocation_strategy`
- `0022_adaptive_asset_allocation_strategy`
- 以及其他多资产再平衡策略

从 `TradeLogger` 日志看，差异主要集中在：

- `order.log`
- `position.log`
- `value.log`
- `trade.log`

其中最关键的差异模式是：

- 在 `master` 中，某些后续买单被记为 `Margin`
- 在当前 `dev` 中，这些买单可以继续被 `Accepted`

这说明差异核心在 **broker 对同批订单的提交期现金/保证金判断**，而不是：

- 数据对齐
- 指标计算
- 结果序列化
- TradeLogger 本身

---

## 代码级根因定位

## 1. `master` 的问题实现

`master:backtrader/brokers/bbroker.py`

```python
664:    def check_submitted(self):
665:        cash = self.cash
666:        positions = dict()
667:        while self.submitted:
668:            order = self.submitted.popleft()
669:            if self._take_children(order) is None:
670:                continue
671:            position = positions.setdefault(
672:                order.data, self.positions[order.data].clone())
673:            cash = self._execute(order, cash=cash, position=position)
674:            if cash >= 0.0:
675:                self.submit_accept(order)
676:                continue
677:            order.margin()
678:            self.notify(order)
679:            self._ococheck(order)
680:            self._bracketize(order, cancel=True)
```

这里有两个关键问题：

- **问题 A：`cash` 先被覆盖，再决定是否接受订单**
  - `cash = self._execute(...)`
  - 如果 trial 后现金变负，这笔单虽然被 `Margin`，但 `cash` 已经被污染

- **问题 B：`position` 是原地被 `_execute(..., position=position)` 修改的 clone 对象**
  - `position = positions.setdefault(...)`
  - `_execute` 内部会调用 `position.update(...)`
  - 如果 trial 失败，没有回滚，后续订单看到的是“被拒订单已经试图成交后的持仓快照”

也就是说，`master.check_submitted()` 的语义实际上变成了：

- **接受订单**：提交并保留 trial 结果
- **拒绝订单**：拒绝，但仍然保留 trial 结果

后者显然是错误的。

---

## 2. 当前 `dev` 的修正实现

当前工作树 `backtrader/brokers/bbroker.py`

```python
1140:    def check_submitted(self):
1147:        cash = self._cash
1148:        positions = dict()
1151:        while self.submitted:
1153:            order = self.submitted.popleft()
1158:            preview_key = self._preview_position_key(order)
1159:            position = positions.setdefault(preview_key, self._clone_position_for_order(order))
1170:            trial_position = position.clone()
1171:            trial_cash = self._execute(order, cash=cash, position=trial_position)
1173:            if trial_cash >= 0.0:
1174:                cash = trial_cash
1175:                positions[preview_key] = trial_position
1176:                self.submit_accept(order)
1177:                continue
1179:            order.margin()
1180:            self.notify(order)
1181:            self._ococheck(order)
1182:            self._bracketize(order, cancel=True)
```

这个版本的核心修复点是：

- 用 `trial_position = position.clone()` 做隔离试算
- 用 `trial_cash = self._execute(...)` 获取试算结果
- **只有当 trial 成功时，才提交这笔 trial 结果到 `cash` 与 `positions`**

也就是把提交校验的语义修正为：

- **接受订单**：提交并保留 trial 结果
- **拒绝订单**：拒绝，并丢弃 trial 结果

这是正确的。

---

## 3. `_execute` 为什么会放大这个 bug

`master:backtrader/brokers/bbroker.py`

```python
817:    def _execute(self, order, ago=None, price=None, cash=None, position=None, dtcoc=None):
...
868:                price = pprice_orig = order.created.price
...
880:            psize, pprice, opened, closed = position.update(size, price)
...
936:            cash -= opencash
938:            openedcomm = cinfocomp.getcommission(opened, price)
940:            cash -= openedcomm
...
946:            if cash < 0.0:
947:                opened = 0
948:                openedvalue = openedcomm = 0.0
...
957:        if ago is None:
958:            return cash
```

在 pseudo execution 模式下：

- `position.update(...)` 会直接修改传入的 `position`
- `cash` 会按开/平仓现金流进行试算并返回
- 即使最终 `cash < 0`，也只是把 `opened = 0`
- **函数本身不会替调用方恢复先前的 `cash` 和 `position`**

因此，调用方必须负责：

- 将 `_execute` 运行在临时快照上
- trial 失败时丢弃快照

`master.check_submitted()` 没做到这一点。

---

## 运行时序说明：为什么这是“上一根 bar 提交、当前 bar 校验”的问题

`backtrader/cerebro.py`

```python
2245:                if d0ret or lastret:
2246:                    self._check_timers(runstrats, dt0, cheat=True)
...
2253:                if d0ret or lastret:
2254:                    self._brokernotify()
...
2260:                if d0ret or lastret:
2261:                    self._check_timers(runstrats, dt0, cheat=False)
2262:                    for strat in runstrats:
2263:                        strat._next()
```

`_brokernotify()` 会先调用 broker 的 `next()`：

```python
1928:        self._broker.next()
```

这说明在普通 `runnext` 流程里：

- **broker 先处理已提交订单**
- **strategy 再在当前 bar 里发出新订单**

因此：

- `check_submitted()` 处理的是**上一轮 `strategy._next()` 提交的订单**
- 这些订单的 `created.price` 是**下单时那个 bar 的 `close`**

而 `order.py` 也证实了 market order 创建时参考价来自 `close`：

```python
567:        pclose = self.data.close[0] if not self.p.simulated else self.price
568:        price = pclose if self.price is None and self.pricelimit is None else self.price
573:        self.created = OrderData(..., price=price, pclose=pclose, ...)
```

因此，`check_submitted()` 的 trial 价是**订单创建 bar 的 close**，而真实执行价是下一次 `_try_exec_market()` 给出的市场价（通常是下一 bar 的 `open`）。

这意味着：

- 提交校验本身就是一种**近似试算**
- 所以更要求对失败 trial **严格回滚**
- 否则近似误差会被叠加并放大为级联误杀

---

## 用真实样本验证：`0019_crypto_optimal_allocation_strategy`

## 1. 真实订单序列

在 `0019` 的一次关键调仓中，`master` 的订单顺序为：

1. `equity` 卖出
2. `bond` 买入
3. `gold` 卖出
4. `crypto` 买入

对应 `master` 日志：

```text
137: equity  Sell  Accepted
138: bond    Buy   Margin
139: gold    Sell  Accepted
140: crypto  Buy   Margin
```

而当前 `dev` 的同一批订单是：

```text
137: equity  Sell  Accepted
138: bond    Buy   Margin
139: gold    Sell  Accepted
140: crypto  Buy   Accepted
```

这说明：

- `bond` 这笔单在两边都被拒绝
- 分歧发生在 **bond 被拒之后，crypto 是否还能继续买**

这正是“被拒订单是否污染后续 trial 状态”的典型症状。

---

## 2. 关键现金数据

`master` 在该调仓前后的现金日志：

- `2025-04-21 broker_cash = 21748.771498699993`
- `2025-04-22 broker_cash = 125469.46480890003`

也就是说，**实际成交完成后，账户现金是明显充足的**。

这至少说明一件事：

- `crypto` 并不是“在真实成交语义下必然买不起”
- 它之所以在 `master` 被判 `Margin`，一定是提交阶段的试算路径有问题

---

## 3. 用 `master` 公式做 trial cash 复盘

按 `master` 的 pseudo execution 逻辑，使用订单创建时的参考价进行试算，现金路径如下：

### 3.1 `master` 现有逻辑：失败 trial 也污染 cash

```text
start cash = 21748.771498699993

equity sell  -> after_trial = 71456.463019799993   accepted=True
bond   buy   -> after_trial = -31096.949661000007  accepted=False
gold   sell  -> after_trial = 22002.907728699993   accepted=True
crypto buy   -> after_trial = -112.662130100007    accepted=False
```

也就是说：

- `bond` 被拒以后，负现金 trial 仍然被保留下来
- `gold` 卖单虽然把现金重新拉回正数，但已经被拖到边界附近
- 最终导致 `crypto` 也被错杀

### 3.2 正确逻辑：失败 trial 必须回滚

```text
start cash = 21748.771498699993

equity sell  -> after_trial = 71456.463019799993   accepted=True
bond   buy   -> after_trial = -31096.949661000007  accepted=False  (rollback)
gold   sell  -> after_trial = 124556.320409499993  accepted=True
crypto buy   -> after_trial = 102440.750550699993  accepted=True
```

这正好与当前 `dev` 的日志一致：

- `bond` 仍然是 `Margin`
- `crypto` 变成 `Accepted`

因此，这个真实样本已经足以证明：

**`master` 的错误不是“整体资金不足”，而是“失败的 `bond` 试算结果污染了后续 `crypto` 的现金判断”。**

---

## 对你原始判断的精炼回答

你的原始判断是：

> `master` 处理保证金的方式存在问题，似乎是 `check_submitted` 的时候把保证金占据了，导致多数据判断的时候，在保证金够其中某些数据交易的时候，如果总体上保证金不足，也不能交易。

这个判断的方向是对的，但更精确的表述应该是：

- `check_submitted` 确实在**顺序试算**每笔订单对资金的影响
- 这本身不是 bug
- **bug 在于：即使订单最后被判 `Margin`，它的试算结果仍然被保留下来，等同于“失败订单也占用了资金/持仓快照”**
- 这会导致后续订单在错误的上下文里继续判断，于是出现“本来可以成交的单也被误判成 `Margin`”

所以：

- **是这个原因，但准确说不是“总体资金不足就不能交易”**
- 而是“**某笔失败订单本不应该继续占用 trial 资金，却被保留了下来**”

---

## 修复方案

## 最小正确修复

只修 `check_submitted()` 的提交校验语义：

1. 获取当前已确认的 `cash`
2. 获取当前已确认的 `position` 快照
3. 为当前订单创建 `trial_position`
4. 用 `_execute(..., cash=cash, position=trial_position)` 计算 `trial_cash`
5. **只有 `trial_cash >= 0` 时，才把 `trial_cash/trial_position` 提交为新的基线**
6. 否则：
   - `order.margin()`
   - 通知
   - 继续下一单
   - **绝不污染 `cash` 和 `positions`**

也就是当前 `dev` 这套逻辑。

---

## 不建议的错误修法

以下方式不建议作为最终修复：

- **只在 `Margin` 后手工把 `cash` 加回去**
  - 因为 `_execute` 不只改 `cash`，也可能改 `position`
  - 手工回补现金无法保证持仓状态一致恢复

- **改成先把所有卖单执行完，再处理买单**
  - 这会改变 broker 的通用语义
  - 属于策略层排序/撮合策略变更，不是最小修复

- **忽略 `check_submitted`，直接全部先 `Accepted` 再执行**
  - 会破坏风险控制语义
  - 不是修 bug，而是删约束

---

## 额外观察：`created.price` 与真实执行价不一致

这个调查中还发现一个**次级问题**：

- `check_submitted` 的 trial 使用的是 `order.created.price`
- 对 market order 来说，这个值来源于**下单时 bar 的 close**
- 但真实执行通常发生在**下一 bar 的 open**

这会导致：

- 提交期试算价 ≠ 实际成交价
- gap 行情下，trial 本身可能偏保守或偏乐观

不过，这不是这次 `asset_allocation` 级联 `Margin` 的主因。

主因已经足够明确：

**即使保持现有 price 近似逻辑不变，只要对失败 trial 正确回滚，`0019` 这类误杀就会消失。**

因此建议：

- **本次修复只修回滚 bug**
- `created.price` / `next open` 的价格近似问题可作为后续独立议题处理

---

## 建议补充的回归测试

## 1. 单元测试：失败订单不得污染后续 trial cash

建议新增一个最小单测，构造以下场景：

- 初始 cash 有限
- 同一批次 4 笔单：
  - 卖出 A（成功）
  - 买入 B（失败）
  - 卖出 C（成功）
  - 买入 D（应成功）

断言：

- B 的状态是 `Margin`
- D 的状态必须是 `Accepted`
- 如果 D 变成 `Margin`，说明失败 trial 污染了后续状态

## 2. 功能回归测试：复用真实策略

至少建议针对以下策略回归：

- `0018_optimal_gold_allocation_strategy`
- `0019_crypto_optimal_allocation_strategy`
- `0022_adaptive_asset_allocation_strategy`

验证点：

- `order.log` 中后续买单不再被级联 `Margin`
- `buy_count` / `sell_count` / `total_trades` 恢复稳定
- `position.log` / `value.log` 路径与预期一致

---

## 风险评估

这是一个**低风险、高收益**修复：

- **改动范围小**
  - 核心只在 `check_submitted()`
- **语义更正确**
  - 失败 trial 不应污染后续判断，本来就是 broker 应有语义
- **兼容性风险可控**
  - 只影响多笔待提交订单中“前一笔失败、后一笔本应成功”的场景
- **行为变化是预期修正，不是副作用**
  - 一些原先在 `master` 上生成的 baseline 可能会变化
  - 但那是因为 baseline 继承了 `master` 的错误行为，不是因为修复破坏了正确性

---

## 最终结论

**是的，问题核心就是 `master.check_submitted()` 的提交期保证金/现金处理有 bug。**

但精确定义不是“顺序占用保证金有问题”，而是：

> `check_submitted()` 对被拒订单执行了 pseudo execution，却没有回滚 trial cash / trial position，导致后续订单在被污染的状态上继续判断，从而引发多资产再平衡中的级联 `Margin` 误判。

当前 `dev` 中的 `trial_cash + trial_position clone + 仅成功提交` 逻辑，正是这个 bug 的正确修复方向。

---

## 推荐动作

- **动作 1**：保留当前 `dev` 的 `check_submitted()` 回滚逻辑，不要回退到 `master`
- **动作 2**：补一个最小单元测试，专门防止“失败 trial 污染后续订单”回归
- **动作 3**：对 `0018 / 0019 / 0022` 重新生成或校验基线
- **动作 4**：将 `created.price` 与实际执行价的偏差，单独列为后续优化议题，而不是和本 bug 混修
