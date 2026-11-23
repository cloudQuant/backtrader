# SPLIT-03b 打包、Wheel 构建与离线导入闭合证据（T-038 / S-07 轨道一子集）

> 采集日期：2026-11-23　证据等级：**STATIC + PACKAGE**
> 目标包：`back_trader_python-1.4.0-py3-none-any.whl`

## 1. 检查项与结果

| 检查项 | 结果 | 详情 |
| --- | --- | --- |
| `backtrader/` 全量 AST 扫描 6 个可选 SDK 子包直接导入 | **PASS** | `0` 处直接导入（`bt_api_gateway` / `bt_api_risk` / `bt_api_execution` / `bt_api_monitor` / `bt_api_runtime` / `bt_api_transport_zmq`） |
| 隔离子进程导入检查（通过 `sys.meta_path` 硬阻断 6 个可选子包） | **PASS** | 全部 18 个双模式公开符号正常导入，`sys.modules` 中 0 个禁导子包 |
| `python -m pip wheel . --no-deps --no-build-isolation` | **PASS** | 成功产出 `back_trader_python-1.4.0-py3-none-any.whl`（共 749 文件），包含全部 14 个新增双模式模块 |

## 2. Wheel 收录新增模块清单（14/14）

- `backtrader/stores/btapi_composition.py`
- `backtrader/stores/base_btapi_store.py`
- `backtrader/stores/direct_btapi_store.py`
- `backtrader/stores/gateway_btapi_store.py`
- `backtrader/stores/service_readonly_store.py`
- `backtrader/feeds/_market_source_port.py`
- `backtrader/feeds/_calendar_query_port.py`
- `backtrader/feeds/base_btapi_feed.py`
- `backtrader/feeds/direct_btapi_feed.py`
- `backtrader/feeds/gateway_btapi_feed.py`
- `backtrader/feeds/replay_btapi_feed.py`
- `backtrader/brokers/base_btapi_broker.py`
- `backtrader/brokers/direct_btapi_broker.py`
- `backtrader/brokers/gateway_btapi_broker.py`

## 3. 边界声明

- 轨道一打包闭合已验证；轨道二跨仓 SDK（`bt_api_py` 及其子包）发布闭合仍属 `NOT_RUN`（待 `T-R2-01`～`T-R2-09` 合龙）。
