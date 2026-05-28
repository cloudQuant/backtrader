# 代码质量迭代计划 (Code Quality Iteration Plan)

> 基于 2026-05 代码库静态分析结果制定 | Based on static analysis of the codebase (2026-05)

## 核心原则 (Guiding Principles)

1. **日志先行** — 先建立可观测性，再做其他优化（无日志的重构无法验证回归）
2. **零破坏性变更** — 所有公共 API、模块路径、类继承关系必须保持兼容
3. **测试是验收唯一标准** — 现有 2,869 个测试用例必须 100% 通过
4. **渐进式推进** — 每个 Sprint 独立可交付、可回滚、可验证

## 代码库现状概览 (Current State Summary)

| 指标 | 数值 | 评价 |
| --- | --- | --- |
| 源码文件数 | 228 | — |
| 源码总行数 | 79,000 | 中大型项目 |
| 测试文件数 | 1,514 | — |
| 测试函数数 | 2,869 | 测试/源码函数比 0.96 |
| 函数/方法总数 | 2,996 | — |
| 类型注解覆盖率 | 9.2% (263/2,858) | ⚠️ 极低 |
| 文档字符串覆盖率 | 79.7% (2,690/3,377) | ✅ 良好 |
| Ruff 告警 | 63 (E402:36, F811:18, F401:8, F841:1) | ✅ 可控 |
| Mypy 错误 | 543 (含 override 抑制后) | ⚠️ 偏高 |
| 高复杂度函数 (>15) | 150 个 | ❌ 严重 |
| 超大文件 (>1000行) | 20 个 | ⚠️ 需关注 |
| Star imports | 117 处 | ⚠️ 影响可维护性 |
| 长参数列表 (>7) | 61 处 | ⚠️ 接口设计问题 |
| 泛化异常捕获比例 | 40.7% (272/668) | ⚠️ 偏高 |
| 静默异常 (`except: pass`) | 110 处 / 21 文件 | ❌ 严重 |
| 当前使用 logging 的文件 | 46 / 228 (20%) | ⚠️ 覆盖不足 |
| eval/exec 使用 | 10 处 | ⚠️ 安全风险 |
| print vs logging 调用 | 63 vs 306 | 部分模块需迁移 |
| 无专属测试的核心模块 | 17 个 | ⚠️ 测试盲区 |

---

## 迭代一：统一日志基础设施 (Sprint 1: Unified Logging Foundation) 🔥

**目标**: 建立项目级统一日志框架，为所有后续优化提供可观测性

**优先级**: P0 | **预计工时**: 3-4 天

### 现状问题

- 仅 46/228 (20%) 文件使用 logging，且各自独立 `getLogger(__name__)`，无统一格式
- 无日志级别策略：什么是 `error` / `warning` / `info` / `debug` 没有规范
- 无统一的日志配置入口（无 `logging.basicConfig`、无 logger handler 注册）
- 110 处 `except: pass` 完全静默，故障无法追溯
- 63 处 `print()` 散落在 `reports/`, `btrun/`, `observers/` 中
- 无日志轮转、无文件输出、无结构化字段

### 任务清单

#### 1.1 设计日志架构 (0.5 天)

- [ ] **新建 `backtrader/utils/logging_config.py`**
  - 提供 `get_logger(name)` 工厂函数（模块统一入口）
  - 提供 `configure_logging(level, log_file=None, fmt=None)` 配置入口
  - 默认 handler：`StreamHandler` (stderr) + 可选 `RotatingFileHandler`
  - 默认格式：`%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s`
  - 提供 `set_level(name, level)` 用于运行时调整子 logger 级别

- [ ] **定义日志级别使用规范 (`docs/LOGGING_GUIDELINES.md`)**

  | 级别 | 使用场景 | 示例 |
  | --- | --- | --- |
  | `CRITICAL` | 引擎无法继续运行 | Cerebro 配置错误、broker 连接彻底失败 |
  | `ERROR` | 操作失败但可恢复 | 订单被拒、数据加载失败、网络重连 |
  | `WARNING` | 异常但不影响主流程 | 数据缺失填补、参数自动修正、降级行为 |
  | `INFO` | 关键里程碑事件 | 策略启动/结束、broker 连接成功、订单成交 |
  | `DEBUG` | 详细诊断信息 | 每根 bar 的 next() 调用、指标计算中间值 |

- [ ] **零破坏性策略**
  - `get_logger()` 内部仍调用 `logging.getLogger()`，不阻碍现有 46 个文件的 logger 使用
  - 不强制注册 handler，用户未调用 `configure_logging()` 时行为与现状一致（NullHandler）
  - 在 `backtrader/__init__.py` 中添加 `from .utils.logging_config import get_logger, configure_logging`

#### 1.2 异常 → 日志规范化 (1.5 天)

- [ ] **消除 110 处 `except: pass` 静默异常**
  - 统一改造为：

    ```python
    except SomeError as e:
        logger.warning("operation X failed, ignoring: %s", e, exc_info=True)
    ```

  - 对真正不关心的（如清理析构），改为 `logger.debug(...)` + 注释说明原因
  - 涉及 21 个文件，按子目录批次提交：
    - 第 1 批：`backtrader/*.py` (核心)
    - 第 2 批：`backtrader/brokers/`, `backtrader/feeds/`
    - 第 3 批：`backtrader/plot/`, `backtrader/bokeh/`, `backtrader/reports/`

- [ ] **泛化异常分级落日志 (272 处中的高优先级部分)**
  - 网络/IO 类：`logger.error("connection lost: %s", e, exc_info=True)`
  - 数据解析类：`logger.warning("malformed data row %s: %s", row_id, e)`
  - 用户输入校验类：`logger.error("invalid parameter %s=%s", name, value)`
  - 注意：本 Sprint 只加日志，**不细化异常类型**（细化交给 Sprint 5）

- [ ] **保留所有 `raise` 语义**
  - 已有 `raise` 的代码不修改控制流，仅在 `raise` 之前添加 `logger.error(...)`
  - 已有 `raise ... from e` 的不变

#### 1.3 print → logging 迁移 (1 天)

按使用场景分类处理，**保留用户可见输出**，**避免破坏 CLI 体验**：

- [ ] **`backtrader/reports/reporter.py` (18 处)**
  - 进度类输出 → `logger.info()`
  - 调试类输出 → `logger.debug()`

- [ ] **`backtrader/btrun/btrun.py` (12 处)**
  - 用户面向 CLI 输出 → 保留 `print()` 或改为 `click.echo()`（保持 CLI 兼容）
  - 内部诊断 → `logger.info()` / `logger.debug()`

- [ ] **`backtrader/observers/trade_logger.py` (9 处)**
  - 已有 `self.log()` 机制 → 内部改用 `logger.info()`，外部接口不变

- [ ] **其他散落的 print (24 处)**
  - 全部改为 `logger.debug()`

#### 1.4 日志测试与文档 (0.5-1 天)

- [ ] **新增 `tests/unit/utils/test_logging_config.py`**
  - 测试 `get_logger()` 返回正确的 logger 名称
  - 测试 `configure_logging()` 不影响已存在的 logger 实例
  - 测试默认情况下 logger 不输出（NullHandler 行为）
  - 测试日志级别切换生效

- [ ] **更新 `README.md` / `docs/source/`**
  - 添加"日志使用"章节，示例：

    ```python
    import backtrader as bt
    bt.configure_logging(level="INFO", log_file="run.log")
    ```

- [ ] **回归验证**
  - 运行 `pytest tests/ -n 4` 确保 2,869 个测试 100% 通过
  - 性能 benchmark：`pytest tests/performance/ --benchmark-only` 不应有显著回归

### Sprint 1 验收标准

| 指标 | 当前 | 目标 |
| --- | --- | --- |
| `except: pass` 静默异常 | 110 | 0 |
| 使用 logging 的文件占比 | 20% | >50% |
| 散落的 `print()` 调用 | 63 | <10（仅保留 CLI 用户输出） |
| 日志级别规范 | 无 | ✅ 已发布 |
| 统一日志入口 | 无 | ✅ `bt.get_logger` / `bt.configure_logging` |
| 现有测试通过率 | 100% | 100% |

---

## 迭代二：配置统一与工具链对齐 (Sprint 2: Configuration Alignment)

**目标**: 消除工具配置矛盾，建立一致的质量基线

**优先级**: P0 | **预计工时**: 1-2 天

### 任务清单

- [ ] **统一 Python 版本目标为 3.8+**（保持现有兼容性，不抬高门槛）
  - `pyproject.toml` 中 `[tool.black]` target-version 保持 py38-py313
  - `[tool.ruff]` target-version 保持 `"py38"`
  - `[tool.mypy]` python_version 保持 `"3.8"`
  - `setup.py` `python_requires` 明确为 `">=3.8"`
  - `.pre-commit-config.yaml` 中 `pyupgrade --py311-plus` **降级为 `--py38-plus`**（避免新语法破坏 3.8 用户）

- [ ] **统一行宽配置 — 采用方案 B (121)**
  - `[tool.black] line-length = 121`
  - `[tool.ruff] line-length = 121`（已是）
  - `[tool.isort] line_length = 121`（已是）
  - `Makefile` 中 `black --line-length=100` 改为 `--line-length=121`
  - `.pre-commit-config.yaml` 中 `ruff-format --line-length=100` 改为 `--line-length=121`
  - 一次性运行 `make format` 重新格式化全部代码（独立 PR）

- [ ] **修复 Makefile 测试路径**
  - `make test` 应运行完整测试套件 `tests/`（与 `pytest.ini` 一致）
  - 新增 `make test-quick` 仅运行 `tests/original_tests/`（保留快速反馈）
  - 新增 `make test-unit`、`make test-integration` 分层运行

- [ ] **清理 Ruff 现有告警 (63 个)**
  - 8 个 F401 (unused import) — `ruff check --fix` 自动修复
  - 1 个 F841 (unused variable) — 自动或人工
  - 18 个 F811 (redefined-while-unused) — 需人工审查（多为故意覆盖）
  - 36 个 E402 (module-import-not-at-top) — 评估每处必要性，无必要则修复

### Sprint 2 验收标准

- 所有工具配置无矛盾（Python 版本、行宽统一）
- Ruff 告警归零
- 全部测试通过

---

## 迭代三：异常处理细化 (Sprint 3: Exception Handling Refinement)

**目标**: 将泛化异常比例从 40.7% 降至 <15%，与 Sprint 1 的日志体系联动

**优先级**: P1 | **预计工时**: 4-5 天

> **前置依赖**: Sprint 1 已建立日志体系，本 Sprint 在已有 `logger.error/warning` 调用的基础上细化异常类型。

### 任务清单

- [ ] **审查 272 处 `except Exception` / `except:`**
  - 数据解析场景 → `except (ValueError, TypeError, KeyError) as e:` + `logger.warning`
  - 网络操作场景 → `except (ConnectionError, TimeoutError, OSError) as e:` + `logger.error`
  - 文件操作场景 → `except (IOError, OSError, PermissionError) as e:` + `logger.error`
  - 第三方库调用场景 → 查阅其异常类型（如 ccxt 的 `NetworkError`）
  - 真正需要兜底的（如顶层事件循环）→ 保留 `except Exception` + `logger.exception()`

- [ ] **完善异常上下文**
  - 所有 `raise X(...)` 改为 `raise X(...) from e`（如果有上层 except）
  - 异常消息标准化：`f"{operation_name} failed: {context}: {reason}"`

- [ ] **eval/exec 安全审查 (10 处)**
  - 评估是否可用 `ast.literal_eval` / `getattr` 替代
  - 对必须保留的：
    - 添加输入白名单/校验
    - 添加 `# nosec` 注释 + 风险说明
    - 用 `logger.warning` 记录每次 eval 调用（生产可关闭）

- [ ] **新增异常基类（可选）**
  - 在 `backtrader/errors.py` 中扩展业务异常层级：
    - `BacktraderError` (root, 已存在)
    - ├── `DataError` — 数据相关
    - ├── `BrokerError` — 经纪商相关
    - ├── `OrderError` — 订单相关
    - └── `ConfigError` — 配置相关
  - **零破坏**: 现有异常类不删除，只新增父类做 isinstance 兼容

### Sprint 3 验收标准

| 指标 | 当前 | 目标 |
| --- | --- | --- |
| 泛化异常比例 | 40.7% | <15% |
| `raise X` 无 `from` 子句 | 多数 | 仅显式重抛或新创建保留 |
| eval/exec 风险点 | 10 | 0 (全部经过审查) |
| 现有测试通过率 | 100% | 100% |

---

## 迭代四：高复杂度函数治理 (Sprint 4: Complexity Reduction)

**目标**: 将最高复杂度函数降至可维护水平

**优先级**: P1 | **预计工时**: 5-8 天

### 重点目标 (Top 10 高复杂度函数)

| 复杂度 | 文件 | 函数 | 建议 |
| --- | --- | --- | --- |
| 162 | stores/btapistore.py | `_create_ctp_wrapper_class` | 拆分为多个工厂方法 |
| 158 | brokers/tickbroker.py | `process_orderbook` | 提取状态机模式 |
| 91 | metabase.py | `__init_subclass__` | 拆分为独立 hook 方法 |
| 84 | strategy.py | `_next_signal` | 提取信号处理子方法 |
| 67 | lineiterator.py | `__init__` | 分阶段初始化 |
| 64 | metabase.py | `patched_init` | 提取初始化步骤 |
| 60 | metabase.py | `_initialize_indicator_aliases` | 拆分注册逻辑 |
| 58 | cerebro.py | `runstrategies` | 提取准备/执行/清理阶段 |
| 55 | cerebro.py | `_runnext` | 提取数据推进/通知子方法 |
| 55 | plot/plot.py | `plotind` | 提取绘图配置/渲染子方法 |

### 重构策略

1. **不改变外部行为** — 纯内部重构，保持 API 兼容
2. **每个函数单独 PR** — 便于 review 和回滚
3. **重构前后跑全量测试** — 确保 2,869 个测试不变
4. **关键决策点添加 logger** — 利用 Sprint 1 日志在分支中记录路径
5. **目标**: 将 >50 复杂度降至 <30，将 >30 降至 <20

### 兼容性保证

- 所有提取出的辅助方法以 `_` 开头标识为内部
- 函数签名（参数、返回值）不变
- 即便是 `__init__`、`__new__` 等魔法方法也只重构内部，不改外部约定

---

## 迭代五：类型注解渐进覆盖 (Sprint 5: Type Annotation)

**目标**: 将类型注解覆盖率从 9.2% 提升至 40%+

**优先级**: P1 | **预计工时**: 5-7 天

### 分层策略

**第一层 — 公共 API (必须)**:

- [ ] `cerebro.py` — 所有公共方法添加类型注解
- [ ] `strategy.py` — `buy()`, `sell()`, `close()`, `order_target_*()` 等
- [ ] `order.py` — Order 类及其状态枚举
- [ ] `feed.py` — DataBase 类公共接口
- [ ] `broker.py` — BrokerBase 公共接口

**第二层 — 核心内部 (推荐)**:

- [ ] `linebuffer.py` — LineBuffer 核心方法
- [ ] `lineseries.py` — Lines/LineSeries 接口
- [ ] `lineiterator.py` — 迭代协议方法
- [ ] `parameters.py` — Params 类

**第三层 — 子模块 (渐进)**:

- [ ] `indicators/` — 每个指标的 `__init__` 和 `next()`
- [ ] `analyzers/` — `create_analysis()`, `stop()` 等
- [ ] `feeds/` — 各数据源的 `_load()` 方法

### Mypy 错误治理 (543 → <100)

| 错误类型 | 数量 | 修复策略 |
| --- | --- | --- |
| call-arg | 78 | 修正函数签名或调用参数 |
| union-attr | 62 | 添加 None 检查或类型窄化 |
| misc | 54 | 逐个分析，多为动态属性 |
| operator | 42 | 添加 `__add__` 等协议 |
| index | 34 | 明确容器类型 |
| arg-type | 34 | 修正参数类型不匹配 |
| var-annotated | 33 | 添加变量类型声明 |

### 兼容性保证

- 类型注解使用 `from __future__ import annotations`，避免运行时求值
- 使用 `TYPE_CHECKING` 守护循环导入
- 不引入运行时类型检查（如 `pydantic`），保持零依赖

---

## 迭代六：超大文件拆分 (Sprint 6: Module Decomposition)

**目标**: 将 >2000 行的文件拆分为可维护的子模块

**优先级**: P2 | **预计工时**: 5-7 天

### 拆分计划

| 文件 | 行数 | 拆分方案 |
| --- | --- | --- |
| `strategy.py` | 3002 | → `strategy/base.py` + `strategy/orders.py` + `strategy/signals.py` |
| `lineiterator.py` | 2923 | → `lineiterator/core.py` + `lineiterator/init.py` + `lineiterator/once.py` |
| `linebuffer.py` | 2802 | → `linebuffer/buffer.py` + `linebuffer/operations.py` + `linebuffer/delayed.py` |
| `cerebro.py` | 2440 | → `cerebro/engine.py` + `cerebro/runner.py` + `cerebro/config.py` |
| `lineseries.py` | 2446 | → `lineseries/core.py` + `lineseries/ops.py` + `lineseries/meta.py` |
| `metabase.py` | 1996 | → `metabase/mixin.py` + `metabase/params.py` + `metabase/patches.py` |

### 兼容性保证

1. **导入路径完全保留** — 通过包 `__init__.py` re-export 所有原模块的公共名称：

   ```python
   # backtrader/strategy/__init__.py
   from .base import Strategy, StrategyBase  # noqa: F401
   from .orders import *  # noqa: F401, F403
   from .signals import *  # noqa: F401, F403
   ```

   用户的 `from backtrader.strategy import Strategy` / `import backtrader.strategy` 都继续工作

2. **逐个文件拆分** — 每次只拆一个，确保测试通过

3. **先拆最独立的部分** — 如 signal 处理、once 模式等

4. **不改变类继承关系** — 只移动代码位置

5. **`pickle` 兼容性** — 序列化的类需要 `__module__` 重定向（如有用户存档需求）

---

## 迭代七：Star Import 清理 (Sprint 7: Import Hygiene)

**目标**: 消除非 `__init__.py` 中的 star import

**优先级**: P2 | **预计工时**: 3-5 天

### 策略

1. **`__init__.py` 中的 star import 保留** — 这是 Python 包的标准导出模式，且兼容现有用户导入习惯
2. **非 `__init__.py` 中的 star import 必须清理** — 改为显式导入
3. **工具辅助**: `ruff check --select F403 --fix` 检测，人工确认导入列表

### 分批处理

- 第一批: `indicators/` 子模块
- 第二批: `analyzers/`, `observers/`, `feeds/`
- 第三批: 核心模块中的 star import

---

## 迭代八：接口设计优化 (Sprint 8: API Design)

**目标**: 改善长参数列表

**优先级**: P3 | **预计工时**: 3-5 天

### 长参数列表治理 (61 处)

- [ ] **引入 dataclass / TypedDict 作为参数对象**
  - 如 `OrderParams`, `PlotConfig`, `BrokerConfig`
  - 旧签名通过 `@deprecated` 装饰器保留，提供平滑过渡

- [ ] **使用 `**kwargs` + 明确文档** 替代超长位置参数

- [ ] **Builder 模式** — 对复杂配置对象（如 Cerebro 配置）

### 兼容性保证

- 所有现有调用方式必须继续工作
- 新接口为附加，不替换旧接口
- 通过 `DeprecationWarning` 引导用户迁移（不强制）

---

## 迭代九：测试质量与文档 (Sprint 9: Test Quality & Docs)

**目标**: 提升测试质量与开发者体验

**优先级**: P3 | **预计工时**: 3-4 天

### 测试质量提升

- [ ] **增加 fixture 使用** — 当前仅 7 处，为常用测试数据创建 fixture
- [ ] **增加参数化测试** — 当前 62 处，指标/分析器适合参数化
- [ ] **目标覆盖率**: 核心模块 >80%，整体 >60%

> 注：补全 17 个无专属测试的核心模块的任务**暂不纳入本迭代**，可作为后续工作。

### 文档与 DX

- [ ] **CONTRIBUTING.md** — 贡献指南（代码风格、PR 流程、测试要求、日志规范）
- [ ] **ARCHITECTURE.md** — 架构决策记录（ADR 格式）
- [ ] **补充模块级 docstring** — 12 个文件缺失
- [ ] **API 文档自动生成** — 基于 Sphinx autodoc + type hints
- [ ] **CI 质量门禁** — GitHub Actions 中集成:
  - ruff check (阻塞)
  - mypy (警告，不阻塞)
  - pytest --cov (覆盖率不降)
  - black --check (阻塞)

---

## 优先级总览与时间线

```text
2026-06 ─────────────────────────────────────────────────────────
  Sprint 1: 统一日志基础设施 (3-4d)   ██████████  🔥 最高优先级
  Sprint 2: 配置统一 (1-2d)           ████
  Sprint 3: 异常处理细化 (4-5d)       ████████████

2026-07 ─────────────────────────────────────────────────────────
  Sprint 4: 复杂度治理 (5-8d)         ████████████████
  Sprint 5: 类型注解 (5-7d)           ██████████████

2026-08 ─────────────────────────────────────────────────────────
  Sprint 6: 文件拆分 (5-7d)           ██████████████
  Sprint 7: Import 清理 (3-5d)        ██████████

2026-09 ─────────────────────────────────────────────────────────
  Sprint 8: 接口优化 (3-5d)           ██████████
  Sprint 9: 测试/文档/DX (3-4d)       ████████
```

---

## 度量与验收标准

| 指标 | 当前值 | Sprint 完成后目标 |
| --- | --- | --- |
| `except: pass` 静默异常 | 110 | 0 (Sprint 1) |
| 使用 logging 的文件占比 | 20% | >50% (Sprint 1) → >80% (Sprint 3) |
| 散落 `print()` 调用 | 63 | <10 (Sprint 1) |
| Ruff 告警 | 63 | 0 (Sprint 2) |
| Mypy 错误 | 543 | <100 (Sprint 5) |
| 类型注解覆盖率 | 9.2% | >40% (Sprint 5) |
| 高复杂度函数 (>30) | ~80 | <20 (Sprint 4) |
| 超大文件 (>1500行) | 12 | 0 (Sprint 6) |
| 泛化异常比例 | 40.7% | <15% (Sprint 3) |
| Star imports (非__init__) | ~50 | 0 (Sprint 7) |
| 配置一致性 | 3 处矛盾 | 0 (Sprint 2) |
| **现有测试通过率** | **100%** | **100% (每个 Sprint)** |

---

## 兼容性约束 (Compatibility Constraints) ⚠️

**贯穿所有 Sprint 的硬性要求**：

1. **公共 API 不删除、不改签名** — `bt.Cerebro`, `bt.Strategy`, `bt.Indicator` 等所有公开类/方法
2. **导入路径不变** — `from backtrader import X`、`from backtrader.indicators import SMA` 等所有现有路径继续可用
3. **类继承关系不变** — `isinstance()` 检查在用户代码中应保持原行为
4. **参数默认值不变** — 不允许在保留参数名的前提下改变默认值
5. **行为不变** — 数值计算结果、订单执行逻辑、事件顺序必须可重现
6. **每个 Sprint 完成必须通过**：
   - `pytest tests/ -n 4` 全部通过（2,869 个用例）
   - `pytest tests/performance/ --benchmark-only` 无显著性能回归（>5% 视为回归）
7. **破坏性变更必须先经讨论** — 如确实需要 deprecation，使用 `DeprecationWarning` 至少保留 2 个版本

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| Sprint 1 添加 logger 影响热路径性能 | 中 | 在 `next()`、`once()` 等热点用 `logger.isEnabledFor()` 守护；benchmark 验证 |
| Sprint 4 复杂度重构破坏隐式行为 | 高 | 每个函数提取前后跑相关测试；增加更多 logger 跟踪关键决策点 |
| Sprint 5 类型注解触发循环导入 | 中 | 全程使用 `from __future__ import annotations` |
| Sprint 6 文件拆分破坏 pickle 兼容 | 低 | 保留 `__module__` 路径；提供迁移说明 |
| 重构引入隐藏 bug | 中 | 每个 Sprint 独立 PR、独立分支；先小批量验证 |

---

## 附录：分析工具与命令

```bash
# 复杂度分析（推荐安装 radon）
pip install radon
radon cc backtrader -n C -s

# 类型覆盖率
mypy backtrader --config-file=pyproject.toml | grep "error:" | wc -l

# Lint 统计
ruff check backtrader --statistics

# 测试覆盖率
pytest tests/ --cov=backtrader --cov-report=term-missing

# 静默异常检测（自定义脚本，本文档第一版基于此生成）
python3 scripts/find_silent_excepts.py

# 全量回归
pytest tests/ -n 4 -v
```
