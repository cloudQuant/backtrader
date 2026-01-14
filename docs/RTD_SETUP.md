# Read the Docs 双语文档配置指南

## 概述

本项目使用 Read the Docs 托管中英文双语文档，顶部有语言切换链接。

## 架构说明

```
┌─────────────────────────────────────────────────────────┐
│                    Read the Docs                         │
├─────────────────────────────────────────────────────────┤
│  backtrader (英文)          backtrader-zh (中文)        │
│  ├── .readthedocs.yaml      ├── .readthedocs-zh.yaml    │
│  ├── conf.py                ├── conf_zh.py              │
│  └── index.rst              └── index_zh.rst            │
├─────────────────────────────────────────────────────────┤
│  URL: /en/latest/           URL: /zh/latest/            │
│       ↑                          ↑                      │
│       └──── 语言切换链接 ────────┘                      │
└─────────────────────────────────────────────────────────┘
```

## 配置步骤

### 步骤 1：创建英文项目

1. 登录 https://readthedocs.org/
2. 点击 **Import a Project**
3. 选择 GitHub 仓库：`cloudQuant/backtrader`
4. 项目设置：
   - **Name**: `backtrader`
   - **Language**: `English`
   - **Default branch**: `development`
   - **Configuration file**: `.readthedocs.yaml`（默认）

### 步骤 2：创建中文项目

1. 再次点击 **Import a Project**
2. 选择同一个仓库：`cloudQuant/backtrader`
3. 项目设置：
   - **Name**: `backtrader-zh`
   - **Language**: `Simplified Chinese`
   - **Default branch**: `development`
4. 创建后，进入项目 **Admin** → **Advanced Settings**
5. 设置 **Configuration file** 为：`.readthedocs-zh.yaml`

### 步骤 3：禁用 stable 版本（两个项目都要设置）

对于 `backtrader` 和 `backtrader-zh` 两个项目：

1. 进入项目的 **Versions** 页面
2. 找到 `stable`，点击 **Edit**
3. **取消勾选 Active**，保存
4. 确保 `latest` 是 **Active**

### 步骤 4：设置默认版本

对于两个项目：

1. **Admin** → **Advanced Settings**
2. **Default version** 选择 `latest`
3. 保存

## 完成后的 URL

| 语言 | URL |
|------|-----|
| 英文 | https://backtrader.readthedocs.io/en/latest/ |
| 中文 | https://backtrader-zh.readthedocs.io/zh/latest/ |

页面顶部会显示语言切换链接：**English** | 中文

## 本地构建测试

### 构建英文文档

```bash
cd docs
sphinx-build -b html source build/html/en -D language=en
```

### 构建中文文档

```bash
cd docs
sphinx-build -b html source build/html/zh -D language=zh_CN
```

### 生成翻译模板

```bash
cd docs
# 生成 .pot 文件
sphinx-build -b gettext source build/gettext

# 更新中文翻译文件
sphinx-intl update -p build/gettext -l zh
```

## 翻译工作流

1. 修改英文文档 (`docs/source/*.rst`)
2. 运行 `sphinx-build -b gettext` 生成翻译模板
3. 运行 `sphinx-intl update` 更新翻译文件
4. 编辑 `docs/source/locales/zh/LC_MESSAGES/*.po` 文件进行翻译
5. 提交更改，RTD 自动构建

## 文件结构

```
docs/
├── source/
│   ├── conf.py              # Sphinx 配置（支持 RTD）
│   ├── index.rst            # 英文主页
│   ├── index_zh.rst         # 中文主页
│   └── locales/
│       └── zh/
│           └── LC_MESSAGES/
│               └── *.po     # 中文翻译文件
├── requirements.txt         # 文档依赖
└── RTD_SETUP.md            # 本文件
```

## 注意事项

1. **自动触发构建**：每次推送到 `development` 或 `master` 分支都会触发构建
2. **Webhook**：确保 GitHub 仓库配置了 RTD Webhook
3. **翻译覆盖**：未翻译的内容将显示英文原文
4. **版本管理**：可以为不同 tag 构建不同版本的文档

## 相关链接

- [Read the Docs 文档](https://docs.readthedocs.io/)
- [Sphinx 国际化指南](https://www.sphinx-doc.org/en/master/usage/advanced/intl.html)
- [sphinx-intl 工具](https://sphinx-intl.readthedocs.io/)
