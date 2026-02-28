- --

stepsCompleted: ["step-01-init", "step-02-discovery", "step-02b-vision", "step-02c-executive-summary", "step-03-success", "step-04-journeys", "step-05-domain", "step-06-innovation", "step-07-project-type", "step-08-scoping", "step-09-functional", "step-10-nonfunctional", "step-11-polish", "step-12-complete"]
status: complete
completedAt: 2026-02-22
inputDocuments: ["product-brief-backtrader-2026-02-22.md"]
documentCounts:
  briefCount: 1
  researchCount: 0
  brainstormingCount: 0
  projectDocsCount: 5
workflowType: 'prd'
classification:
  projectType: Python 库/框架 + 交易平台后端
  domain: 金融科技 / 量化交易
  complexity: 高
  projectContext: brownfield
vision:
  coreStatement: "Backtrader - 世界上最好用的量化交易框架"
  differentiator: "搭积木式设计 + 一次编写全球交易 + 多市场统一 API"
  insight: "通过搭积木式架构设计和多市场统一 API，填补市场上'易用+高性能+全市场覆盖'的空白"

- --

# Product Requirements Document - Backtrader

- *Author:** cloud
- *Date:** 2026-02-22
- *Project Type:** Brownfield (现有项目增强)
- *Version:** 1.0

- --

## Executive Summary

### Product Vision

- *Backtrader - 世界上最好用的量化交易框架**

Backtrader 是一个 Python 量化交易框架，通过"搭积木"式的模块化设计，让量化交易者能够用一套代码在回测和多个市场的实盘交易中无缝切换。本 PRD 定义了 Backtrader 从回测框架升级为全球量化投研一体化平台的完整产品需求。

### What Makes This Special

- *核心差异化优势**: Backtrader 是全球唯一同时实现"极致易用 + 高性能 + 全市场覆盖"的量化框架。

| 维度 | Backtrader | 竞品 |

|------|-----------|------|

| **易用性**| 搭积木式设计，零学习成本迁移 | VN.PY 学习曲线陡 |

|**架构灵活性**| 支持自定义数据列扩展 | 大多数框架固定 OHLCV |

|**回测到实盘**| 一套代码，一键切换 | 需要重写代码 |

|**市场覆盖**| A 股+期货+数字货币+国际市场 | Qlib 仅股票，FreqTrade 仅加密货币 |

|**性能路线** | C++底层 5-10 倍加速 | 纯 Python 框架性能瓶颈 |

### Project Classification

- *项目类型**: Python 库/框架 + 交易平台后端

- *领域**: 金融科技 / 量化交易

- *复杂度**: 高
- 涉及多交易所 API 对接
- 实时交易和高可靠性要求
- 资金安全和风险控制
- 跨市场数据同步

- *项目背景**: Brownfield (现有项目增强)
- 现有 Backtrader 框架已具备 17K+ GitHub 星标
- 完善的回测功能和社区生态
- 已支持 IB 等部分实盘接口
- 本次增强聚焦于扩展实盘对接和性能优化

- --

## Success Criteria

### User Success

- *核心成功定义**: 用户能够用一套策略代码，在 4 个以上交易所进行实盘交易，且回测和实盘结果一致。

- *用户成功时刻**:
- 旧版 Backtrader 代码无需修改即可运行 (API 兼容)
- 回测和实盘使用同一套策略代码
- 在至少 1 个交易所成功执行实盘订单
- 策略在多个市场同时稳定运行

- *用户成功行为指标**:

| 指标 | 定义 | 目标值 |

|------|------|--------|

| 代码迁移成功率 | 旧版代码直接运行比例 | ≥ 95% |

| 实盘启用率 | 从回测切换到实盘的用户比例 | ≥ 60% |

| 多市场使用率 | 同时使用 2+交易所的用户比例 | ≥ 30% |

### Business Success

| 时间节点 | 目标 | 成功标准 |

|----------|------|----------|

| **3 个月**| MVP 发布 | 4 个交易所实盘对接完成 |

|**6 个月**| 社区增长 | GitHub Stars 500+ |

|**12 个月** | 生态成熟 | GitHub Stars 2000+ |

- *技术影响力**:
- 成为 Python 量化交易领域的标准框架之一
- 被至少 5 个其他开源项目引用或集成

### Technical Success

| 标准 | 验收方法 | 目标值 |

|------|----------|--------|

| **交易所覆盖**| 成功对接的交易所数量 | ≥ 4 个 |

|**实盘功能**| 下单、撤单、查询持仓 | 全部正常 |

|**回测兼容性**| 旧版代码测试通过率 | ≥ 95% |

|**实盘稳定性** | 7x24 小时运行无崩溃 | 99.9%可用性 |

- --

## Product Scope

### MVP - Minimum Viable Product

- *MVP 定义**: 完成 4 个交易所的实盘对接，实现回测到实盘的一键切换。

- *核心功能**:
1. CCXT 对接 (OKX、Binance)
2. CTP 接口对接 (国内期货)
3. 国内股票接口对接
4. 统一 Broker API 设计
5. 回测-实盘一致性保证

- *不在 MVP 范围**:
- C++底层重构 (后续版本)
- 高频交易支持 (后续版本)
- Web UI 界面 (后续版本)
- 机器学习集成 (后续版本)

### Growth Features (Post-MVP)

- *MVP 完成后**:
- 扩展更多交易所 (印度、欧洲等)
- C++底层重构实现 5-10 倍性能提升
- 性能优化和并行计算
- 更丰富的技术指标和分析工具

### Vision (Future)

- *长期愿景 (2-3 年)**:
- 成为 Python 量化交易标准框架
- 支持 20+交易所
- Web 管理界面和策略市场
- 企业级支持和培训服务
- 第三方插件生态

- --

## User Journeys

### Journey 1: 李明 - 个人量化交易者

- *开场**: 李明周五晚上，想测试一个新的双均线策略，但苦于回测太慢，且不知道如何在 Binance 上实盘运行。

- *上升动作**:
1. 安装新版 Backtrader，发现旧代码直接运行
2. 回测 10 年数据，几分钟完成
3. 选择"Binance"作为交易所，输入 API 密钥
4. 一键切换到实盘模式

- *高潮**: 策略在 Binance 上成功执行第一笔订单，看到持仓更新

- *结局**: 李明现在可以在 A 股、期货、数字货币上运行同一套策略

### Journey 2: 王芳 - 量化研究员

- *开场**: 王芳团队需要一个既能快速回测，又能实盘交易的框架。现有内部系统慢，商业平台太贵。

- *上升动作**:
1. 团队评估 Backtrader，发现 API 兼容性好
2. 迁移现有因子库，95%代码直接运行
3. 通过 CTP 接口连接期货实盘
4. 策略从研发到上线只需 1 天（原来需要 1 周）

- *高潮**: 第一个实盘策略稳定运行 1 个月，收益率超预期

- *结局**: 团队研发效率提升 5 倍

### Journey 3: 张伟 - 量化开发工程师

- *开场**: 张伟团队维护多套交易系统，代码重复度高，每个新交易所对接需要数周。

- *上升动作**:
1. 评估 Backtrader 的统一 Broker API
2. 用统一接口对接 OKX（1 天完成）
3. 相同代码适配 Binance（只需修改配置）
4. 新增交易所从数周缩短到数天

- *高潮**: 团队用一套代码管理所有市场的交易系统

- *结局**: 维护成本降低 60%

- --

## Domain-Specific Requirements

### Compliance & Regulatory

- *金融交易监管**:
- 各国金融监管不同（中国证监会、美国 SEC、欧盟 MiFID II 等）
- 反洗钱 (AML) 和了解你的客户 (KYC) 要求
- 交易数据需要审计追踪
- 风险披露和投资者保护

### Technical Constraints

- *实时性要求**:
- 订单延迟需控制在毫秒级
- 行情数据需要实时/准实时更新
- 网络断线需要有重连机制

- *可用性要求**:
- 7x24 小时运行（特别是数字货币）
- 99.9%+可用性目标
- 故障恢复和灾难备份

- *资金安全**:
- 订单执行不能出错（资金损失风险）
- 持仓数据必须准确
- 风控限制必须严格执行

### Risk Mitigations

| 风险 | 影响 | 缓解措施 |

|------|------|----------|

| 订单执行失败 | 资金损失 | 本地验证+日志记录+异常告警 |

| API 限流/封禁 | 无法交易 | 限流检测+降级策略 |

| 网络中断 | 无法交易 | 自动重连+本地状态恢复 |

| 数据不一致 | 回测实盘差异 | 数据校验+一致性测试 |

- --

## Functional Requirements

### 策略开发

- FR1: 用户可以创建继承自 Strategy 基类的自定义交易策略
- FR2: 用户可以在策略中访问技术指标（SMA、EMA、RSI 等 60+指标）
- FR3: 用户可以访问 OHLCV 行情数据和自定义数据列
- FR4: 用户可以定义策略参数并在初始化时配置

### 回测引擎

- FR5: 系统可以使用历史数据执行策略回测
- FR6: 系统可以生成回测性能报告（收益率、夏普比率、最大回撤等）
- FR7: 用户可以进行参数优化
- FR8: 系统可以模拟交易成本（滑点、佣金）

### 实盘交易

- FR9: 用户可以通过统一 Broker 接口连接 CCXT 交易所
- FR10: 用户可以通过统一 Broker 接口连接 CTP 期货接口
- FR11: 用户可以通过统一 Broker 接口连接国内股票接口
- FR12: 用户可以执行市价单和限价单
- FR13: 用户可以取消待处理订单
- FR14: 用户可以查询当前持仓和账户余额
- FR15: 系统可以处理订单状态更新和成交回报

### 数据管理

- FR16: 用户可以添加自定义数据列（不限于 OHLCV）
- FR17: 系统支持多种数据源（CSV、Pandas DataFrame、实时数据）
- FR18: 系统可以处理不同时间粒度的数据（tick、分钟、日频）

### 系统兼容

- FR19: 旧版 Backtrader 策略代码无需修改即可运行
- FR20: 系统提供完整的 API 文档和代码示例
- FR21: 系统支持 Python 3.8+版本

- --

## Non-Functional Requirements

### Performance

- *回测性能**:
- NFR-P1: 系统应能在合理时间内完成 10 年日频数据的双均线策略回测
- NFR-P2: 系统应支持参数优化功能
- NFR-P3: 后续 C++重构目标：回测速度提升 5-10 倍

- *实盘性能**:
- NFR-P4: 订单执行延迟应控制在交易所 API 允许的范围内
- NFR-P5: 系统应处理实时行情数据更新

### Security

- *凭据保护**:
- NFR-S1: API 密钥应安全存储，不应在日志或代码中硬编码
- NFR-S2: 敏感配置信息应支持加密存储

- *交易安全**:
- NFR-S3: 系统应在执行订单前进行基本验证（资金充足、参数合法）
- NFR-S4: 系统应记录所有交易操作以便审计

### Reliability

- *稳定性**:
- NFR-R1: 实盘运行应达到 99.9%可用性
- NFR-R2: 系统应能从网络断线中自动恢复
- NFR-R3: 系统应妥善处理交易所 API 错误和限流

- *数据一致性**:
- NFR-R4: 回测和实盘应使用相同的策略逻辑
- NFR-R5: 系统应确保持仓和余额数据的准确性

### Compatibility

- *向后兼容**:
- NFR-C1: 旧版 Backtrader 策略代码应无需修改即可运行
- NFR-C2: 现有 API 接口应保持稳定

- *环境兼容**:
- NFR-C3: 系统应支持 Python 3.8+
- NFR-C4: 系统应在主流操作系统上运行

### Integration

- *交易所集成**:
- NFR-I1: 系统应通过 CCXT 库支持数字货币交易所
- NFR-I2: 系统应通过 CTP 接口支持国内期货
- NFR-I3: 系统应支持国内股票交易接口

- --

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

- *MVP Approach**: 问题解决型 - 4 个交易所实盘对接完成，能够实盘运行

### MVP Feature Set (Phase 1)

- *Core User Journeys Supported**: 个人交易者、量化研究员、开发工程师

- *Must-Have Capabilities**:
- CCXT 对接 (OKX、Binance)
- CTP 国内期货对接
- 国内股票接口对接
- 统一 Broker API
- 基础订单类型（市价单、限价单）
- 回测-实盘一致性保证

### Post-MVP Features

- *Phase 2 (Post-MVP)**:
- 更多交易所（印度、欧洲）
- 高级订单类型（止损、止盈、冰山）
- 性能优化
- 风控系统

- *Phase 3 (Expansion)**:
- C++底层实现
- pybind11 接口
- 5-10 倍性能提升

### Risk Mitigation Strategy

- *Technical Risks**: 统一 Broker 接口抽象层，处理不同交易所的限流和错误

- *Market Risks**: 保持 Backtrader 的易用性优势作为核心竞争力

- *Resource Risks**: 如资源不足，最低需要 2 个交易所实现 MVP

- --

- End of PRD*
