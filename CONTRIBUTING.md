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

python -m pytest tests/new_functions/ -v

```bash

### 开发命令速查

```bash
make test              # 运行测试

make test-coverage     # 测试 + 覆盖率

make format            # 代码格式化 (Black)

make lint              # 代码检查 (Pylint)

make quality-check     # 全部质量检查

make docs              # 生成文档

```bash

- --

## 分支策略

| 分支 | 用途 |

|------|------|

| `dev` | **主开发分支** — 所有新功能和修复提交到这里 |

| `master` | 稳定版本，仅从 dev 合并经过验证的代码 |

- *工作流程**:
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

```bash

### 提交信息规范

使用 [Conventional Commits](<https://www.conventionalcommits.org/):>

```bash
feat: add WebSocket health check to CCXTFeed
fix: handle order-not-found in CCXTBroker.cancel()
perf: cache broker reference in total_value.next()
docs: update CCXT live trading guide
test: add error handling tests for CCXTBroker
refactor: extract retry logic to _retry_api_call()

```bash

- --

## 测试要求

### 必须

- 新功能必须有对应测试
- 修复 bug 必须有回归测试
- 不得删除或弱化现有测试

### 测试规范

```python
import pytest

@pytest.mark.priority_p1
def test_3_1_UT_001_sma_calculation(sample_data, cerebro_engine):
    """Test 3.1-UT-001: Verify SMA indicator calculates correctly.

    Priority: P1 - High
    """

# 使用 fixtures，不要手动创建
    cerebro_engine.adddata(sample_data)
    results = cerebro_engine.run()
    assert len(results) > 0

```bash

### 运行测试

```bash

# 快速烟雾测试 (P0 only)

pytest tests/ -v -m priority_p0

# 预提交验证 (P0 + P1)

pytest tests/ -v -m "priority_p0 or priority_p1"

# 完整测试

pytest tests/ -v -n 4

# 单个测试文件

pytest tests/new_functions/test_ccxt_error_handling.py -v

```bash

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

```bash

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

| `backtrader/ccxt/` | CCXT 实盘交易模块 | 🔥 高 |

| `backtrader/brokers/` | Broker 实现 | 🔥 高 |

| `backtrader/feeds/` | 数据源 | 中 |

| `backtrader/indicators/` | 技术指标 | 中 |

| `backtrader/analyzers/` | 分析器 | 低 |

| `tests/new_functions/` | 新功能测试 | 🔥 高 |

| `docs/` | 文档 | 中 |

详细架构参见 `docs/ARCHITECTURE.md`。
