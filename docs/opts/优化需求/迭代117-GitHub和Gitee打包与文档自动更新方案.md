# 迭代 117 - GitHub 和 Gitee 打包与文档自动更新方案

## 需求概述

1. **打包发布**：如何在 GitHub 和 Gitee 上实现自动打包发布（PyPI、GitHub Releases）
2. **文档自动更新**：每次发布时自动更新项目文档

- --

## 一、打包发布方案

### 方案 A：GitHub Actions + PyPI 自动发布（推荐）

- *优点**：
- 全自动化，创建 tag 即触发发布
- 同时发布到 PyPI 和 GitHub Releases
- 业界标准做法

- *实现方式**：

创建 `.github/workflows/release.yml`：

```yaml
name: Release

on:
  push:
    tags:

      - 'v*'

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    steps:

      - uses: actions/checkout@v4

      - name: Set up Python

        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies

        run: |

          python -m pip install --upgrade pip
          pip install build twine

      - name: Build package

        run: python -m build

      - name: Publish to PyPI

        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*

      - name: Create GitHub Release

        uses: softprops/action-gh-release@v1
        with:
          files: dist/*
          generate_release_notes: true

```bash

- *发布流程**：

```bash

# 1. 更新版本号

vim backtrader/version.py  # 修改 __version__ = "1.0.1"

# 2. 提交并创建 tag

git add .
git commit -m "chore: release v1.0.1"
git tag v1.0.1
git push origin development --tags

# 3. 自动触发 GitHub Actions，发布到 PyPI

```bash

- *配置要求**：
- 在 GitHub 仓库 Settings → Secrets 中添加 `PYPI_API_TOKEN`
- PyPI token 在 <https://pypi.org/manage/account/token/> 创建

- --

### 方案 B：手动打包 + 脚本辅助

- *优点**：
- 简单直接
- 完全控制发布过程
- 无需配置 CI/CD

- *实现方式**：

创建 `scripts/release.sh`：

```bash

# !/bin/bash

set -e

VERSION=$1
if [-z "$VERSION"]; then
    echo "Usage: ./scripts/release.sh <version>"
    echo "Example: ./scripts/release.sh 1.0.1"
    exit 1
fi

echo "📦 Releasing version $VERSION..."

# 1. 更新版本号

sed -i '' "s/__version__ = \".*\"/__version__ = \"$VERSION\"/" backtrader/version.py

# 2. 提交更改

git add .
git commit -m "chore: release v$VERSION"
git tag "v$VERSION"

# 3. 构建包

python -m build

# 4. 上传到 PyPI

twine upload dist/*

# 5. 推送到远程

git push origin development --tags

echo "✅ Released v$VERSION successfully!"

```bash

- *发布流程**：

```bash
./scripts/release.sh 1.0.1

```bash

- --

### 方案 C：Gitee 发布 + 同步到 GitHub

- *优点**：
- 国内用户访问快
- Gitee 有类似的 CI/CD 功能（Gitee Go）

- *实现方式**：

创建 `.gitee/pipelines/release.yml`：

```yaml
name: Release
displayName: 'Release to PyPI'
triggers:
  push:
    tags:
      include:

        - v*

stages:

  - name: build

    displayName: 'Build and Publish'
    jobs:

      - name: release

        displayName: 'Release Job'
        steps:

          - step: execute@python

            name: build
            displayName: 'Build Package'
            inputs:
              python: '3.11'
              run: |

                pip install build twine
                python -m build
                twine upload dist/*--username __token__ --password $PYPI_TOKEN

```bash

- *注意**：Gitee Go 是付费功能，免费用户可使用方案 A 或 B。

- --

### 方案对比

| 方案 | 自动化程度 | 复杂度 | 成本 | 推荐度 |

|------|-----------|--------|------|--------|

| **A: GitHub Actions**| ⭐⭐⭐⭐⭐ 全自动 | 中等 | 免费 | ⭐⭐⭐⭐⭐ |

|**B: 手动脚本**| ⭐⭐ 半自动 | 低 | 免费 | ⭐⭐⭐ |

|**C: Gitee Go** | ⭐⭐⭐⭐ 全自动 | 中等 | 付费 | ⭐⭐ |

- *推荐**：方案 A（GitHub Actions），免费、全自动、业界标准。

- --

## 二、文档自动更新方案

### 方案 1：GitHub Pages 自动部署（推荐）

- *优点**：
- 每次推送自动更新文档
- 免费托管
- 自定义域名支持

- *实现方式**：

创建 `.github/workflows/docs.yml`：

```yaml
name: Documentation

on:
  push:
    branches:

      - development
      - master

    paths:

      - 'docs/**'
      - 'backtrader/**'

  release:
    types: [published]

jobs:
  build-docs:
    runs-on: ubuntu-latest
    steps:

      - uses: actions/checkout@v4

      - name: Set up Python

        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies

        run: |

          pip install -r docs/requirements.txt
          pip install -e .

      - name: Build documentation

        run: |

          cd docs
          sphinx-build -b html source build/html

      - name: Deploy to GitHub Pages

        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./docs/build/html
          publish_branch: gh-pages

```bash

- *配置要求**：
1. GitHub 仓库 Settings → Pages → Source 选择 `gh-pages` 分支
2. 文档将托管在 `<https://cloudquant.github.io/backtrader/`>

- --

### 方案 2：Read the Docs 集成

- *优点**：
- 专业的文档托管平台
- 自动版本管理
- 支持多语言

- *实现方式**：

1. 在 <https://readthedocs.org/> 导入项目
2. 创建 `.readthedocs.yaml`：

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.11"

sphinx:
  configuration: docs/source/conf.py

python:
  install:

    - requirements: docs/requirements.txt
    - method: pip

      path: .

```bash

- *文档地址**：`<https://backtrader.readthedocs.io/`>

- --

### 方案 3：发布时触发文档更新

- *优点**：
- 文档版本与代码版本同步
- 仅在发布时更新，减少构建次数

- *实现方式**：

修改 `.github/workflows/release.yml`，添加文档构建步骤：

```yaml
name: Release

on:
  push:
    tags:

      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:

# ... 打包发布步骤 ...

      - name: Build documentation

        run: |

          pip install -r docs/requirements.txt
          cd docs && sphinx-build -b html source build/html

      - name: Deploy docs

        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./docs/build/html

```bash

- --

### 方案 4：Gitee Pages 部署

- *优点**：
- 国内访问快
- 与 Gitee 仓库集成

- *实现方式**：

1. Gitee 仓库 → 服务 → Gitee Pages
2. 选择分支和目录（如 `docs/build/html`）
3. 手动或自动更新

- *注意**：Gitee Pages 免费版需要手动更新，Pro 版支持自动更新。

- --

### 方案对比

| 方案 | 自动化 | 访问速度 | 版本管理 | 成本 | 推荐度 |

|------|--------|---------|---------|------|--------|

| **1: GitHub Pages**| ⭐⭐⭐⭐⭐ | 国外快 | 单版本 | 免费 | ⭐⭐⭐⭐⭐ |

|**2: Read the Docs**| ⭐⭐⭐⭐⭐ | 国外快 | 多版本 | 免费 | ⭐⭐⭐⭐ |

|**3: 发布触发**| ⭐⭐⭐⭐ | 取决托管 | 与版本同步 | 免费 | ⭐⭐⭐⭐ |

|**4: Gitee Pages** | ⭐⭐ (需 Pro) | 国内快 | 单版本 | Pro 付费 | ⭐⭐⭐ |

- --

## 三、综合推荐方案

### 最佳实践：GitHub Actions 全自动化

```bash
推送代码 → GitHub Actions 自动运行
    ├── 普通推送 → 运行测试 + 更新文档
    └── 创建 tag → 运行测试 + 打包发布 + 更新文档

```bash

- *完整的 CI/CD 配置**：

创建 `.github/workflows/ci.yml`：

```yaml
name: CI/CD

on:
  push:
    branches: [development, master]
    tags: ['v*']
  pull_request:
    branches: [development, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:

      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5

        with:
          python-version: '3.11'

      - name: Install

        run: |

          pip install -r requirements.txt
          pip install -e .
          pip install pytest pytest-xdist

      - name: Test

        run: pytest ./backtrader/tests -n 4 -v

  docs:
    needs: test
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:

      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5

        with:
          python-version: '3.11'

      - name: Build docs

        run: |

          pip install -r docs/requirements.txt
          pip install -e .
          cd docs && sphinx-build -b html source build/html

      - name: Deploy

        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./docs/build/html

  release:
    needs: test
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:

      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5

        with:
          python-version: '3.11'

      - name: Build

        run: |

          pip install build twine
          python -m build

      - name: Publish PyPI

        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*

      - name: GitHub Release

        uses: softprops/action-gh-release@v1
        with:
          files: dist/*
          generate_release_notes: true

```bash

- --

## 四、实施步骤

### 第一阶段：基础配置

1. [ ] 在 PyPI 注册账号并创建 API Token
2. [ ] 在 GitHub 仓库添加 `PYPI_API_TOKEN` Secret
3. [ ] 创建 `.github/workflows/ci.yml` 文件
4. [ ] 启用 GitHub Pages（gh-pages 分支）

### 第二阶段：测试验证

1. [ ] 推送代码，验证测试自动运行
2. [ ] 验证文档自动部署到 GitHub Pages
3. [ ] 创建测试 tag，验证 PyPI 发布

### 第三阶段：文档完善

1. [ ] 更新 README 添加文档链接
2. [ ] 添加版本徽章（PyPI 版本、文档状态）
3. [ ] 配置自定义域名（可选）

- --

## 五、待决策事项

请选择以下方案：

### 打包发布

- [ ] **方案 A**：GitHub Actions 自动发布（推荐）
- [ ] **方案 B**：手动脚本发布
- [ ] **方案 C**：Gitee Go 发布

### 文档更新

- [ ] **方案 1**：GitHub Pages 自动部署（推荐）
- [ ] **方案 2**：Read the Docs
- [ ] **方案 3**：发布时触发更新
- [ ] **方案 4**：Gitee Pages

### 其他决策

- [ ] 是否需要同时发布到 PyPI 和 TestPyPI？
- [ ] 是否需要支持多版本文档？
- [ ] 是否需要配置自定义域名？

- --

## 六、参考资源

- [GitHub Actions 文档](<https://docs.github.com/en/actions)>
- [PyPI 发布指南](<https://packaging.python.org/tutorials/packaging-projects/)>
- [GitHub Pages 文档](<https://docs.github.com/en/pages)>
- [Read the Docs 文档](<https://docs.readthedocs.io/)>
- [Sphinx 文档](<https://www.sphinx-doc.org/)>

- --

- *创建日期**：2026-01-14
- *状态**：待决策
