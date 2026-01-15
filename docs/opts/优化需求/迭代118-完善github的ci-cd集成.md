# 迭代118 - 完善 GitHub CI/CD 集成

## 需求描述

完善 CI/CD 集成功能：

1. **本地提交前检查**：使用 `scripts/optimize_code.sh` 优化代码，运行测试确保通过
2. **GitHub Actions 自动测试**：推送后在多平台、多 Python 版本上自动测试

## 实现方案

### 一、本地 Pre-commit 钩子

使用 `pre-commit` 框架，在 `git commit` 前自动执行检查。

**配置文件**：`.pre-commit-config.yaml`

**检查项**：
- 代码格式化（black, isort, ruff）
- 运行测试（pytest）

### 二、GitHub Actions 工作流

**工作流文件**：`.github/workflows/test.yml`

**测试矩阵**：

| 平台 | Python 版本 |
|------|-------------|
| ubuntu-latest | 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14-dev |
| macos-latest | 3.8, 3.10, 3.11, 3.12, 3.14-dev |
| windows-latest | 3.8, 3.10, 3.11, 3.12, 3.14-dev |

> **注意**：Python 3.14 使用开发版 `3.14-dev`，正式版发布后可更新为 `3.14`。

### 三、文件结构

```
.github/
└── workflows/
    ├── docs.yml          # 文档构建（已有）
    └── test.yml          # 测试工作流（新增）
.pre-commit-config.yaml   # Pre-commit 配置（新增）
pyproject.toml            # 项目配置（更新）
```

## 使用方法

### 安装 pre-commit

```bash
pip install pre-commit
pre-commit install
```

### 手动运行检查

```bash
# 运行所有检查
pre-commit run --all-files

# 或使用优化脚本
./scripts/optimize_code.sh
```

### 跳过 pre-commit（紧急情况）

```bash
git commit --no-verify -m "urgent fix"
```

## 状态

- [x] 需求分析
- [x] 创建 pre-commit 配置（已存在 `.pre-commit-config.yaml`）
- [x] 创建 GitHub Actions 测试工作流 (`.github/workflows/test.yml`)
- [x] 创建本地 pre-push 检查脚本 (`scripts/pre-push-check.sh`)
- [ ] 推送并验证 GitHub Actions

## 创建的文件

| 文件 | 描述 |
|------|------|
| `.github/workflows/test.yml` | GitHub Actions 测试工作流 |
| `scripts/pre-push-check.sh` | 本地推送前检查脚本 |

## 测试矩阵详情

共 **17 个测试任务**：

- **Ubuntu**: Python 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14-dev (7个)
- **macOS**: Python 3.8, 3.10, 3.11, 3.12, 3.14-dev (5个)
- **Windows**: Python 3.8, 3.10, 3.11, 3.12, 3.14-dev (5个)