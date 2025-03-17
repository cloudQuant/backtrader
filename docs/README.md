# Backtrader 文档中心

欢迎来到 Backtrader 文档中心！这里包含了使用 Backtrader 进行量化交易研究所需的所有文档。

## 文档结构

```
docs/
├── getting_started/        # 入门指南
│   ├── installation.md    # 安装指南
│   ├── quickstart.md      # 快速开始
│   └── configuration.md   # 配置指南
│
├── user_guide/            # 用户指南
│   ├── basic_concepts.md  # 基本概念
│   ├── strategies.md      # 策略开发
│   ├── data_feeds.md      # 数据源
│   ├── indicators.md      # 指标系统
│   └── optimization.md    # 参数优化
│
├── advanced/             # 高级主题
│   ├── crypto_trading.md # 加密货币交易
│   ├── high_freq.md      # 高频交易
│   ├── multi_assets.md   # 多资产交易
│   └── risk_mgmt.md      # 风险管理
│
├── api_reference/        # API 参考
│   ├── cerebro.md       # Cerebro 引擎
│   ├── strategy.md      # Strategy 类
│   ├── indicators.md    # 技术指标
│   └── analyzers.md     # 分析器
│
├── examples/            # 示例代码
│   ├── basic/          # 基础示例
│   ├── advanced/       # 高级示例
│   └── real_cases/     # 实战案例
│
└── contributing/        # 贡献指南
    ├── guidelines.md    # 贡献准则
    ├── development.md   # 开发指南
    └── testing.md       # 测试指南
```

## 快速链接

- [安装指南](./getting_started/installation.md)
- [快速开始](./getting_started/quickstart.md)
- [基本概念](./user_guide/basic_concepts.md)
- [策略开发](./user_guide/strategies.md)
- [API 参考](./api_reference/cerebro.md)
- [示例代码](./examples/README.md)

## 特色功能

1. **高性能回测引擎**
   - 支持多品种、多周期回测
   - 支持 Cython 加速
   - 支持并行计算

2. **丰富的数据源支持**
   - CSV 文件数据
   - 实时数据源
   - 加密货币数据
   - 期货数据

3. **完整的策略开发框架**
   - 内置技术指标库
   - 灵活的策略编写
   - 参数优化支持
   - 风险管理工具

4. **可视化分析工具**
   - 交易结果可视化
   - 性能指标分析
   - 回测报告生成

## 社区资源

- [官方论坛](https://www.backtrader.com/community)
- [CSDN 专栏](https://blog.csdn.net/qq_26948675/category_10220116.html)
- [问题反馈](https://gitee.com/yunjinqi/backtrader/issues)
- [贡献指南](./contributing/guidelines.md)

## 版本说明

当前有两个主要分支：
- `master`: 稳定版本，与官方主流版本对齐，主要进行 bug 修复
- `dev`: 开发版本，包含新特性，正在进行 C++ 重写以支持高频交易

## 许可证

本项目采用 [MIT 许可证](../LICENSE)
