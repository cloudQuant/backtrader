# Contributing to Backtrader

感谢你对 Backtrader 的贡献兴趣！本文档说明如何参与项目开发。

## 快速开始

### 环境搭建

```bash

# 1. Fork 并克隆仓库

git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader

# 2. 切换到 dev 分支

git checkout dev

# 3. 安装依赖

pip install -r requirements.txt

# 4. 编译 Cython 加速文件 (可选但推荐)

cd backtrader && python -W ignore compile_cython_numba_files.py && cd ..

# 5. 安装开发模式

pip install -e .

# 6. 验证安装

python -c "import backtrader as bt; print(bt.__version__)"
make test-fast        # 快速回归（约 3.5 分钟）

```

### 开发命令速查

```bash
make test-fast         # 快速开发回路（~3.5min）：全部非策略测试 + 最快 ~35% 策略测试
make test-strategies   # 仅重型策略回归套件（~9min，多时间框架时钟回归网）
make test-slow         # 仅 test-fast 跳过的最慢 ~65% 策略测试
make test-all          # 全量并行（~10min）
make test-coverage     # 测试 + 覆盖率
make format            # 代码格式化 (Black, line-length 100)
make format-check      # 仅检查格式
make lint              # ruff / pylint 检查
make type-check        # mypy 类型检查（非阻塞）
make quality-check     # 全部质量检查
make docs              # 生成文档（en + zh）
```

- --

## 分支策略

| 分支 | 用途 |

|------|------|

| `dev` | **主开发分支** — 所有新功能和修复提交到这里 |

| `master` | 稳定版本，仅从 dev 合并经过验证的代码 |

**工作流程**:

1. 从 `dev` 创建功能分支: `git checkout -b feature/your-feature dev`
2. 开发、测试、提交
3. 向 `dev` 提交 Pull Request

- --

## 代码规范

### 风格要求

- **格式化**: Black (line-length=100)
- **Lint**: Pylint + Ruff
- **类型检查**: MyPy (可选)
- **import 排序**: isort (profile=black)

### 架构规则

1. **禁止新增元类**— 使用 `donew()` + `BaseMixin` 模式

2.**保持 API 兼容**— 现有用户代码必须无修改可运行
3.**初始化顺序**— 先调用 `super().__init__()` 再访问 `self.p`

```python

# ✅ 正确

class MyIndicator(bt.Indicator):
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)

# ❌ 错误 — self.p 在 super().__init__() 之前不可用

class BadIndicator(bt.Indicator):
    def __init__(self):
        print(self.p.period)  # 会失败!
        super().__init__()

```

### 提交信息规范

使用 [Conventional Commits](<https://www.conventionalcommits.org/):>

```bash
feat: add live tick aggregation to BtApiFeed
fix: keep BtApiBroker alive before first live bar
perf: cache broker reference in total_value.next()
docs: update CTP live trading guide
test: add regression coverage for live broker startup
refactor: extract retry logic to _retry_api_call()

```

- --

## 测试要求

### 必须

- 新功能必须有对应测试
- 修复 bug 必须有回归测试
- 不得删除或弱化现有测试

### 测试规范

```python
import pytest


def test_sma_calculation(sample_data, cerebro_engine):
    """Verify the SMA indicator calculates correctly (use fixtures, not manual setup)."""
    cerebro_engine.adddata(sample_data)
    results = cerebro_engine.run()
    assert len(results) > 0


@pytest.mark.slow
def test_full_year_multi_timeframe_regression(sample_data, cerebro_engine):
    """Heavy end-to-end run; tagged `slow` so `make test-fast` can skip it."""
    ...
```

### 测试分级（重要）

策略回归套件很大，按耗时分级运行（详见 `Makefile` 与 `README`）：

| 命令 | 范围 | 大致耗时 | 用途 |
| --- | --- | --- | --- |
| `make test-fast` | 全部非策略测试 + 最快 ~35% 策略测试 | ~3.5min | 日常开发反馈 |
| `make test-strategies` | 全部策略回归（多时间框架时钟回归网） | ~9min | 改动 `cerebro`/`strategy`/line 系统/`_periodset` 后必跑 |
| `make test-slow` | test-fast 跳过的最慢 ~65% 策略 | — | 补充验证 |
| `make test-all` | 全量并行 | ~10min | 提交/发版前 |

慢/快分级由 `tests/functional/strategies/.test_durations.json` 的时长百分位决定，
阈值百分位用环境变量 `BT_SLOW_PERCENTILE`（默认 35）调整；新增策略默认归入快速档。

```bash
# 直接用 pytest 时
pytest tests -n 8 -q                 # 全量并行
pytest tests -n 8 -m "not slow"      # 跳过慢速策略
pytest tests/unit/brokers/test_btapibroker.py -v   # 单文件

# 切换到 pip 安装的 backtrader 而非工作区源码
BACKTRADER_USE_INSTALLED=1 pytest tests -q
# 或：pytest --use-installed-backtrader tests -q
```

### 日志规范

框架代码**不要直接 `import logging`**，统一走 `backtrader.utils.log_message`：

```python
from backtrader.utils.log_message import get_logger
logger = get_logger(__name__)   # -> "backtrader.<module>"
```

- 默认静默（库导入时只挂 `NullHandler`）；用户用 `bt.configure_logging(...)` 开启。
- 禁止静默吞异常：`except ...: pass` 必须带解释性注释，或落 `logger.debug/warning(..., exc_info=True)`。
- 热路径（`next`/`once`/`__len__`/`__getattribute__` 等）加日志要用
  `if logger.isEnabledFor(logging.DEBUG):` 守护，避免格式化开销。

完整规范见 `docs/LOGGING_GUIDELINES.md`。

- --

## Pull Request 流程

### 1. 创建 PR 前

- [ ] 代码通过 `make format-check`
- [ ] 代码通过 `make lint` (无新增 warning)
- [ ] 所有测试通过 `pytest tests/ -v`
- [ ] 新功能有测试覆盖
- [ ] 更新 `CHANGELOG.md` (Unreleased 部分)

### 2. PR 描述模板

```markdown

## 变更说明

简要描述做了什么。

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 性能优化
- [ ] 文档更新
- [ ] 重构

## 测试

- 描述如何测试这些变更
- 附上测试命令

## 影响范围

- 列出可能受影响的模块

```

### 3. 审查标准

- 代码清晰可读
- 无硬编码值
- 错误处理完善
- 性能不退化
- API 向后兼容

- --

## 报告问题

### Bug 报告

请包含:

1.**环境**: Python 版本, 操作系统, backtrader 版本

1. **复现步骤**: 最小可复现代码
2. **预期行为**vs**实际行为**
3. **错误日志**(完整 traceback)

### 功能请求

请说明:

1.**使用场景**: 为什么需要这个功能

1. **期望行为**: 功能应该如何工作
2. **替代方案**: 是否有现有的替代方式

- --

## 项目结构导航

| 目录 | 说明 | 开发频率 |

|------|------|----------|

| `backtrader/brokers/` | Broker 实现 | 🔥 高 |

| `backtrader/feeds/` | 数据源 | 中 |

| `backtrader/indicators/` | 技术指标 | 中 |

| `backtrader/analyzers/` | 分析器 | 低 |

| `tests/functional/strategies/` | 策略回归套件（最大、分级） | 🔥 高 |

| `docs/` | 文档 | 中 |

详细架构参见 `docs/ARCHITECTURE.md`。
