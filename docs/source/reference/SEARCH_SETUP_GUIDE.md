# Algolia DocSearch 配置指南

本指南说明如何为Backtrader文档配置Algolia DocSearch搜索功能。

## 概述

Algolia DocSearch是一个免费的文档搜索服务，为开源项目提供强大的全文搜索功能。

## 申请步骤

### 1. 申请DocSearch

访问 [Algolia DocSearch申请页面](https://docsearch.algolia.com/apply/)

填写以下信息：
- **Website URL**: https://backtrader.readthedocs.io
- **Email**: 项目维护者邮箱
- **Repository**: https://github.com/cloudQuant/backtrader
- **Description**: Python algorithmic trading framework documentation

### 2. 等待审核

Algolia团队会在1-2周内审核申请。审核通过后会收到：
- Application ID
- API Key
- Index Name

### 3. 配置文档

收到凭证后，更新以下文件：

#### 更新 `docs/source/conf.py`

```python
# Algolia DocSearch configuration
html_theme_options = {
    # ... existing options ...
    'algolia': {
        'api_key': 'YOUR_API_KEY',
        'index_name': 'backtrader',
        'app_id': 'YOUR_APP_ID',
    }
}
```

#### 更新 `.algolia-config.json`

已创建配置文件 `.algolia-config.json`，包含：
- 索引配置
- 选择器配置
- 搜索设置

## 本地测试

### 安装DocSearch Scraper

```bash
# 使用Docker运行scraper
docker run -it --env-file=.env -e "CONFIG=$(cat .algolia-config.json | jq -r tostring)" algolia/docsearch-scraper
```

### 创建 `.env` 文件

```env
APPLICATION_ID=YOUR_APP_ID
API_KEY=YOUR_API_KEY
```

## 自动化索引

### GitHub Actions集成

创建 `.github/workflows/algolia-index.yml`:

```yaml
name: Update Algolia Index

on:
  push:
    branches:
      - master
      - development
    paths:
      - 'docs/**'
  workflow_dispatch:

jobs:
  index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run DocSearch Scraper
        env:
          APPLICATION_ID: ${{ secrets.ALGOLIA_APP_ID }}
          API_KEY: ${{ secrets.ALGOLIA_API_KEY }}
        run: |
          docker run \
            -e APPLICATION_ID=$APPLICATION_ID \
            -e API_KEY=$API_KEY \
            -e "CONFIG=$(cat docs/.algolia-config.json | jq -r tostring)" \
            algolia/docsearch-scraper
```

### 配置Secrets

在GitHub仓库设置中添加：
- `ALGOLIA_APP_ID`
- `ALGOLIA_API_KEY`

## 搜索功能集成

### Furo主题集成

Furo主题原生支持搜索，无需额外配置。Algolia会增强搜索体验。

### 自定义搜索UI

如需自定义搜索界面，创建 `docs/source/_static/custom_search.js`:

```javascript
// Custom Algolia DocSearch integration
docsearch({
  apiKey: 'YOUR_API_KEY',
  indexName: 'backtrader',
  appId: 'YOUR_APP_ID',
  container: '#docsearch',
  debug: false,
  searchParameters: {
    facetFilters: ['language:en', 'version:latest']
  }
});
```

## 搜索优化

### 1. 内容优化

- 使用清晰的标题层次结构
- 添加描述性的元数据
- 使用语义化的HTML标签

### 2. 索引优化

配置文件已优化：
- 支持中英文搜索
- 版本过滤
- 标签分类
- 相关性排序

### 3. 性能优化

- 启用缓存
- 使用CDN加速
- 异步加载搜索脚本

## 监控和维护

### 查看索引统计

访问 [Algolia Dashboard](https://www.algolia.com/dashboard)

监控：
- 索引大小
- 搜索请求量
- 搜索性能
- 用户查询

### 定期更新

- 文档更新后自动重新索引
- 每周检查索引健康状况
- 根据用户反馈优化搜索

## 替代方案

如果Algolia申请未通过，可以使用：

### 1. Sphinx内置搜索

已默认启用，无需配置。

### 2. Meilisearch

开源搜索引擎，自托管：

```bash
# 安装Meilisearch
curl -L https://install.meilisearch.com | sh

# 运行
./meilisearch --master-key="YOUR_MASTER_KEY"
```

### 3. Typesense

另一个开源搜索引擎：

```bash
# 使用Docker运行
docker run -p 8108:8108 \
  -v/tmp/typesense-data:/data \
  typesense/typesense:latest \
  --data-dir /data \
  --api-key=YOUR_API_KEY
```

## 故障排除

### 搜索不工作

1. 检查API密钥是否正确
2. 验证索引名称匹配
3. 查看浏览器控制台错误
4. 确认网络连接

### 搜索结果不准确

1. 检查选择器配置
2. 优化内容结构
3. 调整搜索权重
4. 更新索引

### 索引失败

1. 验证配置文件格式
2. 检查权限设置
3. 查看scraper日志
4. 联系Algolia支持

## 资源链接

- [Algolia DocSearch文档](https://docsearch.algolia.com/docs/what-is-docsearch)
- [配置参考](https://docsearch.algolia.com/docs/config-file)
- [最佳实践](https://docsearch.algolia.com/docs/tips)
- [社区支持](https://discourse.algolia.com/)

## 联系方式

如有问题，请：
1. 查看[FAQ](https://docsearch.algolia.com/docs/faq)
2. 在GitHub提Issue
3. 联系Algolia支持团队

---

**更新日期**: 2026-03-01  
**维护者**: Backtrader文档团队
