# 环境配置参考

## 本地环境要求

- **Node.js**：版本 >= 20.19.0
- **OpenSpec CLI**（用于提案管理）

## OpenSpec 安装

```bash
npm install -g @fission-ai/openspec@latest
```

安装后可通过技能 `opsx` 初始化 OpenSpec。

## 项目目录结构

```
/
├── docs/                   # 存放所有需求文档（原始 Word/PDF 及转换后的 .md）
├── openspec/               # OpenSpec 自动生成的规格文档（勿手动修改）
├── 前端项目代码/            # 前端项目代码（具体框架不限）
└── 后端项目代码/            # 后端项目代码（具体框架不限）
```
