# 迭代12 · M6 结构评估与 TODO 复核（只评估）

> 创建：2026-06-01
> 适用分支：`dev`
> 范围：Q-3 `btapistore.py` 模块化评估（不实拆）、Q-4 源码 TODO 复核
> 性质：P4 评估类任务，输出结论，原则上不改业务逻辑

---

## Q-3 `backtrader/stores/btapistore.py` 模块化评估

### 现状

- 文件规模：约 2243 行（实测 `wc -l`）。
- 顶层结构（实测）：
  1. CTP 常量与字段映射表（L31–L204）：`_GATEWAY_PROVIDERS`、`_CTP_EXCHANGES`、
     `_CTP_OFFSET_FLAG`、`_CTP_*_MAP`、`_CTP_LOGIN/RSPINFO/ORDER/TRADE_FIELDS` 等。
  2. 异常类型（L206–L216）：`BtApiStoreError` / `BtApiMissingDependencyError` /
     `BtApiProviderNotImplementedError`。
  3. 纯函数工具（L218–L449）：`_coerce_float/int/text`、`_safe_text_attr`、
     `_split_ctp_symbol`、`_normalize_ctp_instrument`、`_infer_tick_direction`、
     `_build_ctp_tick_datetime`、`_ctp_field_to_dict`、`_ctp_extract_fields`、
     `_normalize_bar`、`_normalize_datetime`。
  4. 客户端包装工厂（L450–L1353）：`_resolve_bt_api_client`、
     `_create_ctp_wrapper_class`（约 700 行，最大块）、
     `_create_ctp_gateway_wrapper_class`、`_gateway_timeframe_str`、
     `_is_gateway_provider`。
  5. 主类 `BtApiStore(LiveStoreBase)`（L1359 起，约 880 行）。

### 复杂度实测

`radon cc backtrader/stores/btapistore.py -n C` 的最高项仅为 **C 级（CC 11–13）**：
`BtApiStore.__init__`(13)、`_emit_broker_runtime_event`(13)、`_gateway_timeframe_str`(12)、
`_order_to_payload`(12)、`fetch_history`(11)、`_ensure_api_ready`(11)。

> 结论：文件内**没有 F/E 级高复杂度函数**，单个函数都在可维护区间。"大"来自
> 数量（常量表 + 三套包装工厂 + 主类），而非单点复杂度。

### 可安全抽出的边界（如未来确需拆分）

按"低耦合、可独立测试、对外零行为变化"排序，推荐的拆分单元：

1. **`_ctp_constants.py`**（最低风险）：把 L31–L204 的 CTP 常量与字段映射表整体抽出。
   纯数据、无逻辑、无外部依赖，几乎零回归风险。
2. **`_ctp_normalize.py`**（低风险）：L218–L449 的纯函数工具。无状态、已被单测覆盖
   （`test_btapistore.py` 中有 `_split_ctp_symbol` 等用例），可连同测试一起迁移。
3. **`_ctp_client.py` / `_ctp_gateway_client.py`**（中风险）：两个 `_create_*_wrapper_class`
   工厂。它们体量最大（尤其 CTP 约 700 行）且依赖 `bt_api_py` 动态导入与 SPI 回调补丁，
   迁移需保证 import 时序与 `pytest.importorskip("bt_api_py.ctp.client")` 守卫不被破坏。
4. **`BtApiStore` 主类**：保留在 `btapistore.py`，从上述子模块 import。

### 评估结论

- **本迭代不实施拆分**。理由：
  1. 无高复杂度热点，拆分收益主要是"文件变短"，可读性收益有限。
  2. CTP 包装工厂与 `bt_api_py` 动态导入 / SPI 补丁强耦合，拆分需要细致处理 import
     时序，存在回归风险，超出本迭代"安全加固"主题。
  3. 拆分会牵动 `tests/unit/stores/test_btapistore.py` 中对 `_create_ctp_wrapper_class`
     等私有符号的直接 import，需同步调整测试，属于"为成立而改测试"的信号，应另立批次。
- **推荐**：若后续要拆，按上面 1→2→3 顺序分批，每批单独通过 `pytest tests/unit/stores`
  + 全量回归。常量表（步骤1）可作为零风险的首个示范批次。

---

## Q-4 源码 TODO/FIXME 复核

实测源码内真实 TODO/FIXME 标记 2 处（`grep -rEn "#.*(TODO|FIXME|HACK)\b"`，
排除 docstring 占位符 `XXX`）：

| 文件:行 | 原标记 | 性质 | 处置 |
|---------|--------|------|------|
| `brokers/bbroker.py` | `# int2pnl, default is True. TODO: Understand literally as ...` | 文档串里的翻译遗留注释，非代码缺陷 | ✅ 改写为正式说明（`int2pnl` 默认 True，将利息成本计入平仓 PnL），移除 TODO |
| `feeds/vchartfile.py` | `# FIXME: find reference to tick counter for format` | 旧 VisualChart tick 格式的已知限制说明 | 保留：这是真实的已知限制备忘，非可立即修复项；该 feed 为遗留数据源，无回归测试支撑改动 |

> 结论：源码内不再有"无主/误导性 TODO"。`bbroker` 的翻译遗留已转为正式文档；
> `vchartfile` 的 FIXME 是合理的已知限制备注，保留可追溯性。

---

## M6 总结

- Q-3：评估完成，**本迭代不拆分** `btapistore.py`，给出分批拆分路线图供后续参考。
- Q-4：`bbroker` TODO 已清理为正式说明；`vchartfile` FIXME 作为已知限制保留。
- M4 Q-2 关联结论：`btapistore.py` 无 F/E 级高复杂度函数，无需在本迭代做复杂度重构。
