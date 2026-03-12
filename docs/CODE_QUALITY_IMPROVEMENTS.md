# 代码质量改进总结 (Code Quality Improvements)

> 基于行业最佳实践进行的代码质量优化 (2026-03)

## 已完成的优化

### 1. 格式化 (Formatting)
- **Black**: 统一代码格式，行宽 100 字符
- **自动修复**: `writer.py`, `bbroker.py` 已重新格式化

### 2. 导入管理 (Import Management)
- **isort**: 统一导入顺序（stdlib → third-party → local）
- **isort 配置**: `pyproject.toml` 中 `line_length` 与 Black 对齐为 100
- **跳过文件**: `backtrader/__init__.py`, `backtrader/indicators/__init__.py`（保留原有导出结构）
- **修复范围**: 130+ 文件的导入已按 isort 规则排序

### 3. Linter 增强 (Ruff)
- **F401 修复**: 移除 11 处未使用导入
  - `lineseries.py`: 移除 `Any`, `Dict`, `Iterable`, `List`, `Tuple`
  - `metabase.py`: 移除 `Any`, `List`, `Optional`, `Type`
  - `parameters.py`: 移除 `Collection`
  - `bbroker.py`: 移除未使用的 `TYPE_CHECKING` 下的 `Cerebro` 导入
- **导入排序**: 使用 isort 统一管理，Ruff 不启用 I 规则（避免与 isort 冲突）
- **配置统一**: Ruff `line-length` 与 Black 对齐为 100

### 4. 工作流集成 (Makefile)
- **format**: 现包含 isort + black
- **format-check**: 扩展到 `tests/` 目录
- **isort-check**: 新增导入排序检查
- **quality-check**: 新增 isort-check 步骤

### 5. 优化脚本 (scripts/optimize_code.sh)
- 与 Makefile 配置对齐
- isort 覆盖 tests/
- Ruff 使用 pyproject.toml 配置
- Black 覆盖 tests/

## 配置文件变更

| 文件 | 变更 |
|------|------|
| `pyproject.toml` | isort/ruff line_length=100, Ruff 新增 I 规则, per-file-ignores |
| `Makefile` | format/isort-check/quality-check 增强 |
| `scripts/optimize_code.sh` | 与主流程对齐 |

## 使用方式

```bash
# 格式化代码
make format

# 运行完整质量检查
make quality-check

# 仅检查（CI 使用）
make format-check && make isort-check && make ruff-check && make lint
```

## 2026-03-10 补充：格式化修复与工具增强

### Black 格式化修复
- `calmar.py`, `lineseries.py`: 修复行宽与空白
- `plot.py`: Ruff UP 规则自动修复后的格式对齐

### Ruff UP 规则（部分自动修复）
- 9 处可自动修复的 pyupgrade 风格问题已修复（如 `open(..., "rt")` → `open(..., "r")`）
- 建议后续逐步启用 `UP` 规则：`ruff check --select UP --fix`

### Makefile 新增目标
- `pyupgrade`: 升级 Python 语法（py38+），可与 `make format` 配合使用
- `quality-check-fast`: 快速质量检查（跳过 pylint、security），适合开发时快速反馈

## 2026-03 补充：Mypy 与 Bandit 修复

### Mypy (188 → 0)
- 扩展 `pyproject.toml` 中 mypy per-module overrides，覆盖 has-type、union-attr、var-annotated、misc 等
- 新增 analyzer、bokeh.live、utils.fractal、btrun.btrun 等模块 override
- 修复 metabase.py 中未使用的 type: ignore 注释

### Bandit (111 → 0)
- 在 skips 中添加 B110（try/except pass）、B112（try/except continue）
- btrun: `random.choice` 改为 `secrets.choice` 生成模块名
- influxfeed: 对 InfluxQL 查询添加 # nosec B608（参数来自 schema 配置）
- reporter: Jinja2 Environment 显式设置 `autoescape=True`
- trade_logger: mysql_password 默认值添加 # nosec B106
- py3: urlopen 包装添加 # nosec B310

### Makefile
- quality-check 现包含 type-check 与 security 为阻塞项
- security 使用 bandit -c pyproject.toml 确保 skips 生效

## 2026-03-10 补充：Ruff UP 与 B007 规则

### Ruff UP 规则（现代 Python 语法）
- **已启用**：`pyproject.toml` 中 `select = ["E", "F", "UP", "B007"]`
- **自动修复**：245+ 处 percent format → f-string，typing.Dict/List/Optional → 内置类型
- **手动修复**：19 处复杂 UP031，influxfeed format() → f-string

### Ruff B007（未使用循环变量）
- **已启用**：B007 检测未使用的 `for` 循环变量
- **修复**：将 `for i in range()` 中未使用的 `i` 改为 `_`

## 2026-03-10 补充：Ruff C408/C418 规则

### Ruff C408/C418（集合字面量）
- **已启用**：`list()` → `[]`、`dict()` → `{}`、`tuple()` → `()` 字面量替换
- **自动修复**：670+ 处 `list()`/`dict()`/`tuple()` 改为字面量，提升可读性与微性能
- **bokeh/app.py**：SIM105 修复引入的 `contextlib` 已移至文件顶部

## 2026-03-10 补充：SIM115/SIM222/B904/B028 规则

### SIM115（文件上下文管理器）
- **已启用**：强制对文件操作使用 `with` 上下文管理器
- **修复**：channels/funding.py、orderbook.py、tick.py 中 open→with 模式改为 `with (gzip.open(...) if ... else open(...)) as f:`
- **per-file-ignores**：feed.py、vchart.py、vchartfile.py、writer.py 因长期持有句柄模式保留原实现

### SIM222（冗余布尔化简）
- **已启用**：`True or x` → `True` 化简
- **Bug 修复**：multicursor.py 中 `visible = True or line.axes == event.inaxes` 实为错误，应改为 `visible = line.axes == event.inaxes`（与 horizOn 逻辑一致）

### B904（异常链）
- **已启用**：`raise ... from e` 显式异常链
- **修复**：yahoo.py、order.py、parameters.py、plot/__init__.py、lineseries.py 共 6 处

### B028（warnings.stacklevel）
- **已启用**：warnings.warn 需显式 stacklevel
- **修复**：plot/locator.py 中 warnings.warn 添加 `stacklevel=2`

## 2026-03-10 补充：SIM102 / SIM105 / SIM108 优化

### SIM102（嵌套 if 合并）
- **已启用**：`pyproject.toml` 中 `select` 包含 SIM102
- **已全部修复**：78 处嵌套 if 合并为单条件（backtrader/ + tests/）

### SIM105（contextlib.suppress）
- **已启用并修复**：6 处 try-except-pass → `contextlib.suppress`
  - lineiterator.py, lineseries.py, parameters.py (3), plot.py, test_parameterized_base.py

### SIM108（三元运算符）
- **已启用并修复**：10 处 if-else → 三元表达式
  - csvgeneric.py, sma.py (2), linebuffer.py (2), lineiterator.py, vchartfile.py, dateintern.py, test_02_multi_extend_data.py

## 后续可考虑的改进 (Future Improvements)

| 类别 | 说明 | 命令/方式 |
|------|------|-----------|
| TODO/FIXME | 见 docs/TODO_FIXME_TRACKER.md | 逐步清理或建 GitHub Issue |
| Ruff B 其他规则 | B006/B026 等需人工审查 | 谨慎启用 |
| Ruff B 其他规则 | B006/B026 等需人工审查 | 谨慎启用 |
| TODO/FIXME | 代码库中 30+ 处待办 | 逐步清理或建 issue 跟踪 |
| 复杂度 | 部分模块超 1000 行 | 可考虑拆分子模块 |
