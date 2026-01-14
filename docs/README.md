# Backtrader 文档 / Documentation

[![Sphinx](https://img.shields.io/badge/Sphinx-8.0+-blue.svg)](https://www.sphinx-doc.org/)
[![Python](https://img.shields.io/badge/Python-3.7+-green.svg)](https://www.python.org/)

本目录包含 Backtrader 项目的完整文档源文件，支持中英文双语。

This directory contains complete documentation source files for the Backtrader project, supporting both English and Chinese.

## 文档特性 / Features

- 📚 **完整的 API 参考** - 自动从源代码生成，包含所有 50+ 指标、15+ 分析器
- 🌐 **中英文双语** - 用户指南和开发文档支持中英文
- 🎨 **现代化主题** - 使用 Furo 主题，支持暗色模式
- 🔍 **全文搜索** - 支持中英文搜索
- 📋 **代码复制** - 一键复制代码示例
- 📊 **继承图** - 自动生成类继承关系图

## 快速开始 / Quick Start

### 安装依赖 / Install Dependencies

```bash
pip install -r requirements.txt
```

### 构建文档 / Build Documentation

**构建中英文文档 / Build both languages:**
```bash
./build_docs.sh
# 或 Windows:
make html-all
```

**仅构建英文文档 / English only:**
```bash
./build_docs.sh en
# 或
make html
```

**仅构建中文文档 / Chinese only:**
```bash
./build_docs.sh zh
# 或
make html-zh
```

### 启动本地服务器 / Start Local Server

```bash
./build_docs.sh serve
```

然后在浏览器中打开 http://localhost:8000

## 目录结构 / Directory Structure

```
docs/
├── source/                 # 文档源文件
│   ├── conf.py            # Sphinx 配置
│   ├── index.rst          # 英文首页
│   ├── index_zh.rst       # 中文首页
│   ├── api/               # API 参考文档
│   ├── user_guide/        # 英文用户指南
│   ├── user_guide_zh/     # 中文用户指南
│   ├── dev/               # 英文开发文档
│   ├── dev_zh/            # 中文开发文档
│   ├── locales/           # 翻译文件
│   └── _static/           # 静态资源
├── Makefile               # Make 构建文件
├── make.bat               # Windows 构建脚本
├── build_docs.sh          # Shell 构建脚本
├── requirements.txt       # Python 依赖
└── README.md              # 本文件
```

## 更新文档 / Updating Documentation

### 添加新页面 / Adding New Pages

1. 在 `source/user_guide/` 创建新的 `.rst` 文件
2. 在 `source/index.rst` 的 toctree 中添加引用
3. 创建对应的中文版本在 `source/user_guide_zh/`
4. 在 `source/index_zh.rst` 的 toctree 中添加引用

### 更新 API 文档 / Updating API Documentation

运行以下命令从源代码自动生成 API 文档：

```bash
./build_docs.sh apidoc
# 或
make apidoc
```

### 翻译工作流 / Translation Workflow

1. 提取可翻译字符串：
   ```bash
   make gettext
   ```

2. 更新翻译文件：
   ```bash
   make update-po
   ```

3. 编辑 `source/locales/zh_CN/LC_MESSAGES/` 中的 `.po` 文件

4. 重新构建中文文档：
   ```bash
   make html-zh
   ```

## 文档风格指南 / Documentation Style Guide

### 代码示例 / Code Examples

使用 `.. code-block:: python` 指令：

```rst
.. code-block:: python

   import backtrader as bt
   cerebro = bt.Cerebro()
```

### 警告和提示 / Admonitions

```rst
.. note::
   这是一个提示

.. warning::
   这是一个警告

.. tip::
   这是一个技巧
```

### 交叉引用 / Cross References

```rst
参见 :doc:`strategies` 了解更多
使用 :class:`backtrader.Strategy` 类
调用 :meth:`buy` 方法
```

## 贡献文档 / Contributing

欢迎提交文档改进！请确保：

1. 使用清晰简洁的语言
2. 提供实际可运行的代码示例
3. 保持中英文版本同步
4. 遵循现有的文档格式

## 许可证 / License

文档与 Backtrader 项目使用相同的许可证。
